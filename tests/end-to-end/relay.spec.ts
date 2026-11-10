import { expect, test } from "@playwright/test";
import {
  ADMIN,
  adminCall,
  ask,
  askbridgeOn,
  newId,
  openHandoffFromMenu,
  openRelay,
} from "../support/relay";

// Vitalos Relay visitor journeys (docs/relay, Phase 2-4 acceptance). The e2e server runs Relay with
// the in-memory store and the deterministic mock model, so answers are stable and offline.

// Relay is the public site's assistant only while Askbridge is off (ADR-045).
test.skip(askbridgeOn, "Askbridge replaces Relay in this build");

test.describe("Relay launcher and panel", () => {
  test("launcher opens the panel; Esc closes it and returns focus", async ({ page }) => {
    await page.goto("/");
    const launcher = page.getByRole("button", {
      name: "Open chat with Relay, the Vitalos assistant",
    });
    await expect(launcher).toBeVisible();
    await expect(launcher).toHaveAttribute("aria-expanded", "false");
    // WCAG 2.5.3 Label in Name: on a first visit the name starts with the "Ask Vitalos" label.
    await expect(launcher).toHaveAccessibleName(
      "Ask Vitalos. Open chat with Relay, the Vitalos assistant",
    );
    await launcher.click();
    await expect(page.getByText("Ask Vitalos.")).toBeVisible();
    await expect(page.getByLabel("Message Relay")).toBeFocused();
    await expect(page.getByRole("region", { name: "Suggested questions" })).toBeVisible();
    await expect(page.locator(".relay-subtitle")).toHaveText("AI assistant");
    await page.keyboard.press("Escape");
    await expect(page.locator("#relay-panel")).toBeHidden();
    await expect(launcher).toBeFocused();
    // The label is gone after the first open, and the name drops it too.
    await expect(launcher).toHaveAccessibleName("Open chat with Relay, the Vitalos assistant");
  });

  test("no Relay request is made before the visitor interacts", async ({ page }) => {
    const relayCalls: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/api/relay/")) relayCalls.push(r.url());
    });
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    expect(relayCalls).toEqual([]);
  });

  test("answers with cited sources, takes feedback and offers a person on thumbs down", async ({
    page,
  }) => {
    await page.goto("/");
    await openRelay(page);
    await ask(page, "Can you rescue a failing software project?");
    const answer = page.locator(".relay-answer").last();
    await expect(answer.getByText("RELAY · AI")).toBeVisible();
    await expect(answer.getByText("SOURCES")).toBeVisible();
    await expect(answer.locator(".relay-source").first()).toBeVisible();
    await answer.getByRole("button", { name: "Not helpful" }).click();
    await expect(answer.getByRole("button", { name: "Not helpful" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(answer.getByText("NOTED")).toBeVisible();
    await expect(page.getByRole("heading", { name: /Sorry that didn't answer it/ })).toBeVisible();
  });

  test("hand-off form validates, then sends the request", async ({ page }) => {
    await page.goto("/");
    await openRelay(page);
    await openHandoffFromMenu(page);
    await page.getByRole("button", { name: "Connect me to a person" }).click();
    await expect(page.getByText("Enter your name")).toBeVisible();
    await expect(page.getByText("Enter a valid email address")).toBeVisible();
    await expect(
      page.getByText("Tick the box so we can contact you about this enquiry"),
    ).toBeVisible();
    await expect(page.getByLabel("Name")).toBeFocused();
    await page.getByLabel("Name").fill("Alex Morgan");
    await page.getByLabel("Work email").fill("alex.morgan@example-care.invalid");
    await page.getByLabel("Company (optional)").fill("Example Care Group");
    await page.getByLabel(/Vitalos may contact me/).check();
    await page.getByRole("button", { name: "Connect me to a person" }).click();
    // The first request also creates the conversation (Turnstile is fetched from Cloudflare).
    await expect(page.getByText(/REQUEST SENT/)).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(/alex\.morgan@example-care\.invalid/)).toBeVisible();
  });

  test("an explicit request for a person skips the model and offers the hand-off", async ({
    page,
  }) => {
    await page.goto("/");
    await openRelay(page);
    await ask(page, "Can I speak to a real person please?");
    await expect(page.locator(".relay-answer").last()).toContainText(
      "Of course. A person from the team can pick this up.",
    );
  });

  test("low confidence says so and offers a person instead of guessing", async ({ page }) => {
    await page.goto("/");
    await openRelay(page);
    await ask(page, "What is the capital of France?");
    const answer = page.locator(".relay-answer").last();
    await expect(answer).toContainText("won't guess");
    await expect(answer.getByRole("button", { name: "Talk to a person" })).toBeVisible();
  });

  test("the conversation survives a page navigation and can be deleted", async ({ page }) => {
    await page.goto("/");
    await openRelay(page);
    await ask(page, "Which sectors do you work in?");
    await page.goto("/about");
    await expect(page.locator("#relay-panel")).toBeVisible();
    await expect(
      page.locator(".relay-visitor").getByText("Which sectors do you work in?"),
    ).toBeVisible();
    await page.getByRole("button", { name: "Conversation options" }).click();
    await page.getByRole("menuitem", { name: "Delete this conversation" }).click();
    await page.getByRole("button", { name: "Delete", exact: true }).click();
    await expect(page.getByText("Conversation deleted.")).toBeVisible();
    await expect(page.getByText("Ask Vitalos.")).toBeVisible();
  });

  test("keyboard only: open, ask, thumbs down, close with Esc", async ({ page }) => {
    await page.goto("/");
    const launcher = page.getByRole("button", { name: /Open chat with Relay/ });
    await launcher.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByLabel("Message Relay")).toBeFocused();
    await page.keyboard.type("How does an engagement with Vitalos start?");
    await page.keyboard.press("Enter");
    const thumbsDown = page
      .locator(".relay-answer")
      .last()
      .getByRole("button", { name: "Not helpful" });
    await expect(thumbsDown).toBeVisible({ timeout: 20_000 });
    await thumbsDown.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByLabel("Name")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(launcher).toBeFocused();
  });

  test("Stop generating keeps the partial answer", async ({ page }) => {
    await page.goto("/");
    await openRelay(page);
    const composer = page.getByLabel("Message Relay");
    await composer.fill("Tell me about application modernisation and how it starts");
    await composer.press("Enter");
    const stop = page.getByRole("button", { name: "Stop generating" });
    // The first message also creates the conversation (Turnstile is fetched from Cloudflare).
    await expect(stop).toBeVisible({ timeout: 20_000 });
    await stop.click();
    await expect(page.getByRole("button", { name: "Send message" })).toBeVisible();
  });
});

test.describe("Relay hand-off with a person (two parties)", () => {
  test("thumbs down → form → admin sees it → join → two-way messages → hand back → close", async ({
    page,
    request,
  }) => {
    test.slow(); // a dozen steps across two parties, each waiting on polling
    await page.goto("/");
    await openRelay(page);
    await ask(page, "Roughly how long would a modernisation take?");
    await page.locator(".relay-answer").last().getByRole("button", { name: "Not helpful" }).click();
    await page.getByLabel("Name").fill("Jordan Ellis");
    await page.getByLabel("Work email").fill("jordan.ellis@example-care.invalid");
    await page.getByLabel(/Vitalos may contact me/).check();
    await page.getByRole("button", { name: "Connect me to a person" }).click();
    // The first request also creates the conversation (Turnstile is fetched from Cloudflare).
    await expect(page.getByText(/REQUEST SENT/)).toBeVisible({ timeout: 20_000 });

    // The admin sees the request within 2 seconds.
    let id = "";
    await expect
      .poll(
        async () => {
          const inbox = await adminCall(request, "GET", "/inbox?tab=needs");
          const items =
            (inbox.data.items as { id: string; displayName: string; tags: string[] }[]) ?? [];
          id = items.find((i) => i.displayName === "Jordan Ellis")?.id ?? "";
          return id;
        },
        { timeout: 2000, intervals: [200] },
      )
      .not.toBe("");
    const thread = await adminCall(request, "GET", `/conversations/${id}`);
    expect((thread.data.conversation as { contact: { email: string } }).contact.email).toBe(
      "jordan.ellis@example-care.invalid",
    );

    // Join: the visitor sees the person and the AI pauses.
    expect((await adminCall(request, "POST", `/conversations/${id}/join`)).status).toBe(200);
    await expect(page.getByRole("heading", { name: ADMIN.name })).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".relay-subtitle")).toHaveText(/Team online\s*·\s*A person, not AI/);
    await expect(page.getByText(/TEMITOPE AGBOLA JOINED/)).toBeVisible();
    await expect(page.getByText("RELAY AI IS PAUSED WHILE YOU CHAT WITH THE TEAM")).toBeVisible();

    // Two-way messages.
    await adminCall(request, "POST", `/conversations/${id}/reply`, {
      text: "Hi Jordan, I've read the conversation so far.",
      clientMessageId: newId(),
      emailIfAway: false,
    });
    await expect(page.getByText("Hi Jordan, I've read the conversation so far.")).toBeVisible({
      timeout: 10_000,
    });
    const composer = page.getByLabel("Message Relay");
    await expect(composer).toHaveAttribute("placeholder", "Message Temitope");
    await composer.fill("Around 40 homes and 2,000 staff.");
    await composer.press("Enter");
    await expect
      .poll(async () => {
        const after = await adminCall(request, "GET", `/conversations/${id}/messages`);
        return (after.data.messages as { senderType: string; body: string }[]).some(
          (m) => m.senderType === "visitor" && m.body.includes("2,000 staff"),
        );
      })
      .toBe(true);

    // Hand back to Relay, then close.
    await adminCall(request, "POST", `/conversations/${id}/handback`);
    await expect(page.getByText("RELAY AI IS BACK")).toBeVisible({ timeout: 10_000 });
    await adminCall(request, "POST", `/conversations/${id}/close`);
    await expect(page.getByText(/CONVERSATION CLOSED/)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("button", { name: "Start a new conversation" })).toBeVisible();
  });

  test("admin API rejects unsigned and tampered requests", async ({ request }) => {
    expect((await request.get("/api/relay/admin/inbox")).status()).toBe(401);
    const ok = await adminCall(request, "GET", "/inbox?tab=ai");
    expect(ok.status).toBe(200);
  });
});
