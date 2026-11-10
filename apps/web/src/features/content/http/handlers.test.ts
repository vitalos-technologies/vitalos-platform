import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import { ContentNotFoundError, ContentUnavailableError } from "../client";
import type { ContentClient } from "../client";
import { signLookup } from "../lookup/auth";
import { renderMarkdown } from "../markdown/render";
import { CLOSED_SITE_STATE, createReaders } from "../readers";
import type { ContentReaders } from "../readers";
import { signPreviewToken, signRequest } from "../signing";
import type { SigningKey, SigningScope } from "../signing";
import { MemoryRateLimiter } from "./guards";
import { handleLookupRequest } from "./handle-lookup";
import {
  handleEnterPreview,
  handleExitPreview,
  previewCookie,
  safeReturnPath,
} from "./handle-preview";
import { MAX_RENDER_BYTES, handleRenderRequest } from "./handle-render";
import { handleRevalidateRequest, warmPaths } from "./handle-revalidate";
import { handleTickRequest } from "./handle-tick";

const origin = "https://www.example.test";
const now = 1_800_000_000;
const revalidateKey: SigningKey = { id: "rev-1", secret: "v".repeat(40) };
const renderKey: SigningKey = { id: "render-1", secret: "w".repeat(40) };
const previewKey: SigningKey = { id: "preview-1", secret: "p".repeat(40) };
const fixture = (name: string): unknown =>
  JSON.parse(
    readFileSync(
      new URL(`../../../../../../contracts/content-api/v1/fixtures/${name}.json`, import.meta.url),
      "utf8",
    ),
  );

function signedPost(
  path: string,
  body: string,
  options: {
    key?: SigningKey;
    scope?: SigningScope;
    timestamp?: number;
    headers?: Record<string, string>;
  } = {},
): Request {
  const headers = signRequest({
    key: options.key ?? revalidateKey,
    scope: options.scope ?? "revalidate",
    method: "POST",
    pathAndQuery: path,
    body,
    timestamp: options.timestamp ?? now,
  });
  return new Request(`${origin}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...headers, ...options.headers },
    body,
  });
}

describe("POST /api/content/revalidate", () => {
  const event = fixture("revalidate-request") as {
    eventId: string;
    kind: string;
    tags: string[];
    paths: string[];
  };
  const harness = (keys: SigningKey[] = [revalidateKey]) => {
    const deps = {
      keys,
      // The limiter's fixed one-minute window reads the test clock, not the wall clock: 121 calls
      // that crossed a minute boundary used to reset the count and get 200 instead of 429.
      limiter: new MemoryRateLimiter(() => now * 1000),
      revalidateTag: vi.fn(),
      revalidatePath: vi.fn(),
      warm: vi.fn(),
      clearLookupVerdicts: vi.fn(),
      notifyIndexNow: vi.fn(),
      now: () => now,
    };
    return { deps, call: (request: Request) => handleRevalidateRequest(request, deps) };
  };
  const path = "/api/content/revalidate";

  it("publish: stale-while-revalidate every tag, warm the paths, clear the proxy verdicts", async () => {
    const { deps, call } = harness();
    const response = await call(signedPost(path, JSON.stringify(event)));
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.json()).toEqual({ revalidated: event.tags });
    expect(deps.revalidateTag.mock.calls).toEqual(
      event.tags.map((tag) => [tag, tag === "sitemap" ? { expire: 0 } : "max"]),
    );
    expect(deps.warm).toHaveBeenCalledWith(event.paths);
    expect(deps.revalidatePath).not.toHaveBeenCalled();
    expect(deps.clearLookupVerdicts).toHaveBeenCalledTimes(1);
  });

  it("remove: expire every tag immediately and revalidate every path", async () => {
    const { deps, call } = harness();
    const body = JSON.stringify({ ...event, kind: "remove", paths: ["/insights/old", "/"] });
    const response = await call(signedPost(path, body));
    expect(response.status).toBe(200);
    expect(deps.revalidateTag.mock.calls).toEqual(event.tags.map((tag) => [tag, { expire: 0 }]));
    expect(deps.revalidatePath.mock.calls).toEqual([["/insights/old"], ["/"]]);
    expect(deps.warm).not.toHaveBeenCalled();
  });

  it("refreshes the Insights and Careers sitemap children with the index (ADR-043)", async () => {
    const { deps, call } = harness();
    const body = JSON.stringify({ ...event, paths: ["/insights/example-post-1", "/sitemap.xml"] });
    expect((await call(signedPost(path, body))).status).toBe(200);
    expect(deps.warm).toHaveBeenCalledWith([
      "/insights/example-post-1",
      "/sitemap.xml",
      "/sitemaps/insights.xml",
      "/sitemaps/careers.xml",
    ]);
    const removed = JSON.stringify({ ...event, kind: "remove", paths: ["/sitemaps/careers.xml"] });
    expect((await call(signedPost(path, removed))).status).toBe(200);
    expect(deps.revalidatePath).toHaveBeenCalledWith("/sitemaps/careers.xml");
  });

  it("sends the changed Insights and Careers pages to IndexNow, never feeds or sitemaps", async () => {
    const { deps, call } = harness();
    const body = JSON.stringify({
      ...event,
      paths: ["/", "/insights", "/insights/example-post-1", "/insights/feed.xml", "/sitemap.xml"],
    });
    expect((await call(signedPost(path, body))).status).toBe(200);
    expect(deps.notifyIndexNow).toHaveBeenCalledWith(["/insights", "/insights/example-post-1"]);
    const removed = JSON.stringify({ ...event, kind: "remove", paths: ["/careers/old-role"] });
    expect((await call(signedPost(path, removed))).status).toBe(200);
    expect(deps.notifyIndexNow).toHaveBeenLastCalledWith(["/careers/old-role"]);
  });

  it.each([
    [
      "tampered body",
      () => {
        const request = signedPost(path, JSON.stringify(event));
        return new Request(request.url, {
          method: "POST",
          headers: request.headers,
          body: JSON.stringify({ ...event, tags: ["home"] }),
        });
      },
    ],
    [
      "tampered path",
      () => {
        const signed = signedPost("/api/content/render", JSON.stringify(event));
        return new Request(`${origin}${path}`, {
          method: "POST",
          headers: signed.headers,
          body: JSON.stringify(event),
        });
      },
    ],
    ["stale timestamp", () => signedPost(path, JSON.stringify(event), { timestamp: now - 301 })],
    ["wrong scope", () => signedPost(path, JSON.stringify(event), { scope: "render" })],
    [
      "another scope's key",
      () => signedPost(path, JSON.stringify(event), { key: renderKey, scope: "revalidate" }),
    ],
    [
      "no signature",
      () => new Request(`${origin}${path}`, { method: "POST", body: JSON.stringify(event) }),
    ],
  ])("401 for a %s, and nothing is revalidated", async (_label, build) => {
    const { deps, call } = harness();
    const response = await call(build());
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "unauthorized" });
    expect(deps.revalidateTag).not.toHaveBeenCalled();
  });

  it("accepts either key during rotation", async () => {
    const next = { id: "rev-2", secret: "x".repeat(40) };
    const { call } = harness([next, revalidateKey]);
    expect((await call(signedPost(path, JSON.stringify(event)))).status).toBe(200);
    expect((await call(signedPost(path, JSON.stringify(event), { key: next }))).status).toBe(200);
  });

  it.each([
    ["an unknown tag", { tags: ["insights", "unknown:thing"] }, "unknown_tag"],
    ["a malformed tag", { tags: ["Insights"] }, "invalid"],
    ["an unknown path", { paths: ["/about"] }, "unknown_path"],
    ["an absolute path", { paths: ["https://evil.example/insights"] }, "unknown_path"],
    ["an extra field", { extra: true }, "invalid"],
    ["a bad kind", { kind: "purge" }, "invalid"],
  ])("400 for %s, before anything is revalidated", async (_label, change, error) => {
    const { deps, call } = harness();
    const response = await call(signedPost(path, JSON.stringify({ ...event, ...change })));
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error });
    expect(deps.revalidateTag).not.toHaveBeenCalled();
  });

  it("400 for a signed body that is not JSON", async () => {
    const { call } = harness();
    expect((await call(signedPost(path, "{nope"))).status).toBe(400);
  });

  it("413 for an oversized body", async () => {
    const { call } = harness();
    const body = JSON.stringify({ ...event, pad: "x".repeat(70 * 1024) });
    expect((await call(signedPost(path, body))).status).toBe(413);
  });

  it("503 when no revalidate key is configured", async () => {
    const { call } = harness([]);
    expect((await call(signedPost(path, JSON.stringify(event)))).status).toBe(503);
  });

  it("429 with Retry-After once the per-IP budget is spent", async () => {
    const { call } = harness();
    let last: Response | undefined;
    for (let i = 0; i < 121; i += 1) {
      last = await call(
        signedPost(path, JSON.stringify(event), { headers: { "x-forwarded-for": "198.51.100.7" } }),
      );
    }
    expect(last?.status).toBe(429);
    expect(Number(last?.headers.get("retry-after"))).toBeGreaterThan(0);
  }, 30_000);
});

describe("warmPaths", () => {
  it("GETs each path on the site's origin with bounded concurrency and never throws", async () => {
    let active = 0;
    let peak = 0;
    const fetchMock = vi.fn(async (url: URL) => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, 5));
      active -= 1;
      if (url.pathname === "/fail") throw new Error("down");
      return new Response("ok", { status: url.pathname === "/missing" ? 404 : 200 });
    });
    const result = await warmPaths(origin, ["/a", "/b", "/c", "/d", "/e", "/fail", "/missing"], {
      fetch: fetchMock as unknown as typeof fetch,
      concurrency: 2,
    });
    expect(result).toEqual({ warmed: 5, failed: 2 });
    expect(peak).toBeLessThanOrEqual(2);
    expect(String(fetchMock.mock.calls[0]![0])).toBe(`${origin}/a`);
  });
});

describe("POST /api/content/render", () => {
  const path = "/api/content/render";
  const deps = (keys: SigningKey[] = [renderKey]) => ({
    keys,
    limiter: new MemoryRateLimiter(),
    render: renderMarkdown,
    mediaOrigin: "https://media.example.test",
    siteHosts: ["www.example.test"],
    now: () => now,
  });
  const sign = (body: string, options: { scope?: SigningScope; timestamp?: number } = {}) =>
    signedPost(path, body, { key: renderKey, scope: options.scope ?? "render", ...options });

  it("renders signed Markdown and returns the contract's shape", async () => {
    const body = JSON.stringify(fixture("render-request"));
    const response = await handleRenderRequest(sign(body), deps());
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    const result = (await response.json()) as { html: string };
    expect(result).toEqual({
      html: '<h2 id="example-heading">Example heading</h2>\n<p>Example paragraph.</p>',
      toc: [{ id: "example-heading", text: "Example heading", depth: 2 }],
      footnotes: 0,
      warnings: [],
      faq: [],
    });
  });

  it("sanitises what it renders", async () => {
    const body = JSON.stringify({
      markdown: "<script>alert(1)</script>\n\n[x](javascript:alert(1))",
      context: "post",
    });
    const result = (await (await handleRenderRequest(sign(body), deps())).json()) as {
      html: string;
      warnings: { code: string }[];
    };
    expect(result.html).toBe("<p>x</p>");
    expect(result.warnings.map((w) => w.code)).toEqual(["html_stripped"]);
  });

  it("401 for tampered, stale and wrong-scope requests", async () => {
    const body = JSON.stringify(fixture("render-request"));
    const tampered = sign(body);
    const forged = new Request(tampered.url, {
      method: "POST",
      headers: tampered.headers,
      body: body.replace("Example", "Changed"),
    });
    for (const request of [
      forged,
      sign(body, { timestamp: now + 301 }),
      sign(body, { scope: "revalidate" }),
    ]) {
      expect((await handleRenderRequest(request, deps())).status).toBe(401);
    }
  });

  it("413 above 200 KB, 400 for an invalid body, 503 when not configured", async () => {
    const big = JSON.stringify({ markdown: "x".repeat(MAX_RENDER_BYTES), context: "post" });
    expect((await handleRenderRequest(sign(big), deps())).status).toBe(413);
    const bad = JSON.stringify({ markdown: "x", context: "email" });
    expect((await handleRenderRequest(sign(bad), deps())).status).toBe(400);
    expect((await handleRenderRequest(sign("{}"), deps([]))).status).toBe(503);
  });
});

describe("GET /api/content/preview", () => {
  const id = "00000000-0000-4000-8000-000000000101";
  const preview = fixture("preview-post") as { post: { slug: string } };
  const readersFor = (result: () => Promise<unknown>) =>
    ({ readPreview: vi.fn(result) }) as unknown as Pick<ContentReaders, "readPreview"> & {
      readPreview: ReturnType<typeof vi.fn>;
    };
  const deps = (
    readers = readersFor(() => Promise.resolve({ kind: "ok", data: preview })),
    keys = [previewKey],
  ) => ({
    keys,
    limiter: new MemoryRateLimiter(),
    readers,
    enableDraftMode: vi.fn(() => Promise.resolve()),
    secureCookies: true,
    now: () => now,
  });
  const enter = (token: string) =>
    new Request(`${origin}/api/content/preview?token=${encodeURIComponent(token)}`);

  it("verifies the token, enables Draft Mode, sets the cookie and redirects to the item", async () => {
    const token = signPreviewToken({ entity: "post", id, rev: "abc" }, previewKey, now);
    const d = deps();
    const response = await handleEnterPreview(enter(token), d);
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(`/insights/${preview.post.slug}`);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(response.headers.get("x-robots-tag")).toBe("noindex");
    expect(response.headers.get("set-cookie")).toBe(
      `vitalos_preview=${token}; Path=/; Max-Age=900; HttpOnly; SameSite=Lax; Secure`,
    );
    expect(d.enableDraftMode).toHaveBeenCalledTimes(1);
    expect(d.readers.readPreview).toHaveBeenCalledWith("post", id, token);
  });

  it("redirects a role preview to the role page", async () => {
    const token = signPreviewToken({ entity: "role", id, rev: "abc" }, previewKey, now);
    const role = fixture("preview-role") as { role: { slug: string } };
    const response = await handleEnterPreview(
      enter(token),
      deps(readersFor(() => Promise.resolve({ kind: "ok", data: role }))),
    );
    expect(response.headers.get("location")).toBe(`/careers/${role.role.slug}`);
  });

  it("401 for a missing, tampered, expired or foreign-key token; Draft Mode stays off", async () => {
    const valid = signPreviewToken({ entity: "post", id, rev: "abc" }, previewKey, now);
    const foreign = signPreviewToken({ entity: "post", id, rev: "abc" }, revalidateKey, now);
    const expired = signPreviewToken(
      { entity: "post", id, rev: "abc", exp: now - 1 },
      previewKey,
      now,
    );
    for (const token of ["", `${valid}x`, expired, foreign]) {
      const d = deps();
      const response = await handleEnterPreview(enter(token), d);
      expect(response.status, token).toBe(401);
      expect(response.headers.get("x-robots-tag")).toBe("noindex");
      expect(d.enableDraftMode).not.toHaveBeenCalled();
    }
  });

  it("404 when the admin does not know the item, 503 when it is unreachable", async () => {
    const token = signPreviewToken({ entity: "post", id, rev: "abc" }, previewKey, now);
    const missing = deps(readersFor(() => Promise.resolve({ kind: "missing" })));
    expect((await handleEnterPreview(enter(token), missing)).status).toBe(404);
    const down = deps(readersFor(() => Promise.reject(new ContentUnavailableError("timeout"))));
    expect((await handleEnterPreview(enter(token), down)).status).toBe(503);
    expect(down.enableDraftMode).not.toHaveBeenCalled();
    expect((await handleEnterPreview(enter(token), deps(undefined, []))).status).toBe(503);
  });

  it("exit disables Draft Mode, clears the cookie and only returns to relative paths", async () => {
    const disableDraftMode = vi.fn(() => Promise.resolve());
    const exit = (path: string) =>
      handleExitPreview(
        new Request(`${origin}/api/content/preview/exit?path=${encodeURIComponent(path)}`),
        { limiter: new MemoryRateLimiter(), disableDraftMode, secureCookies: false },
      );
    const response = await exit("/insights/a-post");
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("/insights/a-post");
    expect(response.headers.get("set-cookie")).toBe(
      "vitalos_preview=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax",
    );
    expect(disableDraftMode).toHaveBeenCalledTimes(1);
    for (const bad of [
      "https://evil.example",
      "//evil.example",
      "/\\evil.example",
      "javascript:x",
      "",
    ]) {
      expect((await exit(bad)).headers.get("location"), bad).toBe("/");
    }
  });

  it("safeReturnPath and previewCookie", () => {
    expect(safeReturnPath("/careers/x?y=1")).toBe("/careers/x?y=1");
    expect(safeReturnPath("/ space")).toBe("/");
    expect(previewCookie("t", -5, true)).toContain("Max-Age=0");
  });
});

describe("GET /api/content/lookup", () => {
  const secret = "r".repeat(40);
  const readers = createReaders({
    client: {
      get: vi.fn(async (pathAndQuery: string, schema: { parse(v: unknown): unknown }) => {
        if (pathAndQuery === "/api/content/v1/site-state")
          return schema.parse(fixture("site-state"));
        if (pathAndQuery === "/api/content/v1/insights/posts/example-post-1") {
          return schema.parse(fixture("post-detail"));
        }
        throw new ContentNotFoundError();
      }),
      post: vi.fn(),
    } as unknown as ContentClient,
    cache: (fn) => fn,
    ttlSeconds: 600,
  });
  const lookup = (
    path: string,
    header?: string | null,
    ip = "198.51.100.1",
    limiter = new MemoryRateLimiter(),
  ) =>
    handleLookupRequest(
      new Request(`${origin}/api/content/lookup?path=${encodeURIComponent(path)}`, {
        headers: header ? { "x-vitalos-lookup": header, "x-vitalos-lookup-ip": ip } : {},
      }),
      { readSecret: secret, limiter, readers },
    );

  it("rate-limits per visitor address (signed by the proxy), not per proxy", async () => {
    const limiter = new MemoryRateLimiter();
    const path = "/insights/example-post-1";
    const ask = (ip: string) =>
      lookup(path, signLookup(secret, { path, clientIp: ip }), ip, limiter);
    let last: Response | undefined;
    for (let i = 0; i < 301; i += 1) last = await ask("198.51.100.7");
    expect(last?.status).toBe(429);
    expect((await ask("198.51.100.8")).status).toBe(200);
    // A visitor address the proxy did not sign is refused outright.
    const forged = await lookup(
      path,
      signLookup(secret, { path, clientIp: "198.51.100.7" }),
      "198.51.100.9",
      limiter,
    );
    expect(forged.status).toBe(404);
  }, 30_000);

  it("answers the proxy's signed question with the pages' readers", async () => {
    const ok = await lookup(
      "/insights/example-post-1",
      signLookup(secret, { path: "/insights/example-post-1", clientIp: "198.51.100.1" }),
    );
    expect(ok.status).toBe(200);
    expect(ok.headers.get("cache-control")).toBe("no-store");
    expect(await ok.json()).toEqual({ verdict: "ok" });
    const missing = await lookup(
      "/insights/nope",
      signLookup(secret, { path: "/insights/nope", clientIp: "198.51.100.1" }),
    );
    expect(await missing.json()).toEqual({ verdict: "missing" });
  });

  it("is a 404 to anyone else, and 400 for a path it does not handle", async () => {
    expect((await lookup("/insights/example-post-1")).status).toBe(404);
    expect(
      (
        await lookup(
          "/insights/example-post-1",
          signLookup("s".repeat(40), {
            path: "/insights/example-post-1",
            clientIp: "198.51.100.1",
          }),
        )
      ).status,
    ).toBe(404);
    expect(
      (
        await lookup(
          "/insights/example-post-1",
          signLookup(secret, { path: "/insights/other", clientIp: "198.51.100.1" }),
        )
      ).status,
    ).toBe(404);
    expect(
      (await lookup("/about", signLookup(secret, { path: "/about", clientIp: "198.51.100.1" })))
        .status,
    ).toBe(400);
  });
});

describe("GET /api/content/cron/tick", () => {
  const cronSecret = "c".repeat(40);
  const tickSecret = "t".repeat(40);
  const tick = { promoted: 1, closed: 2, delivered: 3, nextDueAt: null };
  const deps = (
    nextDueAt: string | null,
    options: { fail?: boolean; configured?: boolean } = {},
  ) => ({
    secrets: [cronSecret, tickSecret],
    limiter: new MemoryRateLimiter(),
    readers: {
      siteState: vi.fn(() =>
        options.fail
          ? Promise.reject(new ContentUnavailableError("network"))
          : Promise.resolve({ ...CLOSED_SITE_STATE, nextDueAt }),
      ),
    },
    client:
      options.configured === false
        ? null
        : ({
            post: vi.fn((_path: string, _body: unknown, schema: { parse(v: unknown): unknown }) =>
              Promise.resolve(schema.parse(tick)),
            ),
          } as unknown as Pick<ContentClient, "post">),
    expireSiteState: vi.fn(),
    now: () => Date.parse("2026-10-15T12:00:00Z"),
  });
  const request = (secret = cronSecret) =>
    new Request(`${origin}/api/content/cron/tick`, {
      headers: { authorization: `Bearer ${secret}` },
    });

  it("does not contact the admin when nothing is due", async () => {
    for (const due of [null, "2026-10-15T12:00:01Z"]) {
      const d = deps(due);
      const response = await handleTickRequest(request(), d);
      expect(await response.json()).toEqual({ status: "ok", ticked: false });
      expect(d.client?.post).not.toHaveBeenCalled();
    }
  });

  it("ticks the admin, signed with scope tick, once nextDueAt has passed, then expires site state", async () => {
    const d = deps("2026-10-15T11:59:00Z");
    const response = await handleTickRequest(request(), d);
    expect(await response.json()).toEqual({
      status: "ok",
      ticked: true,
      promoted: 1,
      closed: 2,
      delivered: 3,
    });
    expect(d.client?.post).toHaveBeenCalledWith("/api/content/v1/tick", {}, expect.anything(), {
      scope: "tick",
    });
    expect(d.expireSiteState).toHaveBeenCalledTimes(1);
  });

  it("accepts CRON_SECRET (Vercel Cron) and CONTENT_TICK_SECRET (the Worker)", async () => {
    expect((await handleTickRequest(request(cronSecret), deps(null))).status).toBe(200);
    expect((await handleTickRequest(request(tickSecret), deps(null))).status).toBe(200);
    expect(
      (
        await handleTickRequest(request(tickSecret), {
          ...deps(null),
          secrets: [undefined, tickSecret],
        })
      ).status,
    ).toBe(200);
  });

  it("401 for a wrong bearer, 503 without any secret or when the admin is down", async () => {
    expect((await handleTickRequest(request("wrong"), deps(null))).status).toBe(401);
    expect(
      (await handleTickRequest(request(), { ...deps(null), secrets: [undefined, undefined] }))
        .status,
    ).toBe(503);
    expect((await handleTickRequest(request(), deps(null, { fail: true }))).status).toBe(503);
  });

  it("does nothing when content is not configured", async () => {
    const response = await handleTickRequest(
      request(),
      deps("2026-10-15T11:00:00Z", { configured: false }),
    );
    expect(await response.json()).toEqual({ status: "not_configured", ticked: false });
  });
});
