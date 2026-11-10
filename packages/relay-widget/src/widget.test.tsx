import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseFrame } from "./api";
import { RelayLauncher } from "./launcher";
import { Markdown } from "./markdown";
import {
  clearConversation,
  hasSeen,
  loadConversation,
  markSeen,
  saveConversation,
} from "./storage";

describe("Markdown (safe subset)", () => {
  it("renders paragraphs, bold and lists, never raw HTML", () => {
    const { container } = render(
      <Markdown
        text={"Hello **there** <img src=x onerror=alert(1)>\n\n- one\n- two\n\n1. first\n2. second"}
      />,
    );
    expect(container.querySelectorAll("p")).toHaveLength(1);
    expect(container.querySelector("strong")?.textContent).toBe("there");
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
    expect(container.querySelectorAll("ul li")).toHaveLength(2);
    expect(container.querySelectorAll("ol li")).toHaveLength(2);
  });

  it("links only to vitalos.co.uk and same-site paths", () => {
    const { container } = render(
      <Markdown
        text={
          "[Offer](/offers/engineering-rescue) [Site](https://www.vitalos.co.uk/trust) [Bad](https://evil.example/x) [JS](javascript:alert(1)) [Proto](//evil.example)"
        }
      />,
    );
    const hrefs = [...container.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/offers/engineering-rescue", "https://www.vitalos.co.uk/trust"]);
    expect(container.textContent).toContain("Bad");
    expect(container.textContent).toContain("JS");
  });

  it("turns known citation markers into superscript links and drops unknown ones", () => {
    const { container } = render(
      <Markdown text="Yes [1]. Also [3]." sourceAnchor={(n) => (n === 1 ? "#src-1" : null)} />,
    );
    const sup = container.querySelectorAll("sup a");
    expect(sup).toHaveLength(1);
    expect(sup[0]?.getAttribute("href")).toBe("#src-1");
    expect(container.textContent).toBe("Yes 1. Also .");
  });
});

describe("SSE frames", () => {
  it("parses events and ignores malformed frames", () => {
    expect(parseFrame('event: delta\ndata: {"text":"Hi"}')).toEqual({
      event: "delta",
      data: { text: "Hi" },
    });
    expect(parseFrame("event: delta")).toBeNull();
    expect(parseFrame("data: {}")).toBeNull();
    expect(parseFrame("event: done\ndata: {not json")).toBeNull();
  });
});

describe("storage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("round-trips and expires after 30 days", () => {
    const value = {
      conversationId: "c",
      visitorToken: "t",
      channelKey: "k",
      realtime: null,
      lastSeenAt: new Date().toISOString(),
    };
    saveConversation(value);
    expect(loadConversation()).toEqual(value);
    saveConversation({
      ...value,
      lastSeenAt: new Date(Date.now() - 31 * 86_400_000).toISOString(),
    });
    expect(loadConversation()).toBeNull();
    clearConversation();
    markSeen();
    expect(hasSeen()).toBe(true);
  });

  it("works when storage throws (private windows, blocked storage)", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(loadConversation()).toBeNull();
    expect(hasSeen()).toBe(false);
    expect(() =>
      saveConversation({
        conversationId: "c",
        visitorToken: "t",
        channelKey: "k",
        realtime: null,
        lastSeenAt: "",
      }),
    ).not.toThrow();
  });
});

describe("RelayLauncher accessible name (WCAG 2.5.3 Label in Name)", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
  });

  it("starts with the visible label while it shows (first visit)", async () => {
    render(<RelayLauncher symbolSrc="/brand/vitalos-symbol.png" privacyUrl="/legal/privacy" />);
    const launcher = await screen.findByRole("button", {
      name: "Ask Vitalos. Open chat with Relay, the Vitalos assistant",
    });
    expect(launcher.textContent).toBe("Ask Vitalos");
  });

  it("is the plain action once the label is gone (returning visitor)", () => {
    markSeen();
    render(<RelayLauncher symbolSrc="/brand/vitalos-symbol.png" privacyUrl="/legal/privacy" />);
    const launcher = screen.getByRole("button", {
      name: "Open chat with Relay, the Vitalos assistant",
    });
    expect(launcher.textContent).toBe("");
  });
});
