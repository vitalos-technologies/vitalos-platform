import { expect, test } from "@playwright/test";
import { expectNoA11yViolations } from "../support/axe";
import { isDraftRun } from "../support/content-source";
import { expectNoHorizontalOverflowAt320 } from "../support/overflow";

// The Products section (owner direction, 17 Oct 2026; ADR-031 amendment). Products live in
// @vitalos/cms, not the content source, so these run under every source.
test.use({ reducedMotion: "reduce" });

const isDesktop = (width: number | undefined) => (width ?? 0) >= 1024;

test.describe("Products", () => {
  test("Who We Are lists Products: the heading to /products, then Fauward, SOB Autofix, Askbridge and Relay", async ({
    page,
  }) => {
    await page.goto("/");
    if (isDesktop(page.viewportSize()?.width)) {
      await page.getByRole("button", { name: "Who We Are menu" }).click();
      const panel = page.getByRole("group", { name: "Who We Are" });
      await expect(panel.getByRole("link", { name: "Products", exact: true })).toHaveAttribute(
        "href",
        "/products",
      );
      const fauward = panel.getByRole("link", { name: /^Fauward — logistics SaaS/ });
      await expect(fauward).toHaveAttribute("href", "/products/fauward");
      const sob = panel.getByRole("link", { name: /^SOB Autofix — workshop platform/ });
      await expect(sob).toHaveAttribute("href", "/products/sob-autofix");
      const askbridge = panel.getByRole("link", { name: /^Askbridge — AI website assistant/ });
      await expect(askbridge).toHaveAttribute("href", "/products/askbridge");
      const relay = panel.getByRole("link", { name: /^Relay — social media publishing/ });
      await expect(relay).toHaveAttribute("href", "/products/relay");
      // Fauward first, then SOB Autofix, then Askbridge, then Relay.
      const hrefs = await panel
        .locator('a[href^="/products/"]')
        .evaluateAll((links) => links.map((link) => link.getAttribute("href")));
      expect(hrefs).toEqual([
        "/products/fauward",
        "/products/sob-autofix",
        "/products/askbridge",
        "/products/relay",
      ]);
      await expectNoA11yViolations(page);
    } else {
      // The mobile sheet renders the same columns; collapsed disclosures hide them from roles.
      await expect(page.locator('header a[href="/products/fauward"]').first()).toBeAttached();
      await expect(page.locator('header a[href="/products/sob-autofix"]').first()).toBeAttached();
      await expect(page.locator('header a[href="/products/askbridge"]').first()).toBeAttached();
      await expect(page.locator('header a[href="/products/relay"]').first()).toBeAttached();
      await expect(page.locator('header a[href="/products"]').first()).toBeAttached();
    }
  });

  test("the footer's Explore column links to /products", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('footer a[href="/products"]')).toHaveCount(1);
    await expect(page.locator('footer a[href="/products"]')).toHaveText("Products");
  });

  test("/products shows the Fauward, SOB Autofix, Askbridge and Relay cards, each with its snapshot and page", async ({
    page,
  }) => {
    const response = await page.goto("/products");
    expect(response?.status()).toBe(200);
    // The route page's heading: "Products" in the repo copy, "Products (fixture)" in the fixtures.
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^Products/);
    const main = page.locator("main");
    await expect(main.getByRole("heading", { level: 2, name: "Fauward" })).toHaveCount(1);
    await expect(
      main.getByRole("img", {
        name: "Fauward tenant portal: the operations dashboard, with the finance and Fauward Go screens behind it",
      }),
    ).toBeVisible();
    await expect(main.getByRole("link", { name: "View Fauward" })).toHaveAttribute(
      "href",
      "/products/fauward",
    );
    await expect(main.getByRole("heading", { level: 2, name: "SOB Autofix" })).toHaveCount(1);
    await expect(
      main.getByRole("img", { name: /^SOB Autofix booking flow, step 1 of 7/ }),
    ).toBeVisible();
    await expect(main.getByRole("link", { name: "View SOB Autofix" })).toHaveAttribute(
      "href",
      "/products/sob-autofix",
    );
    await expect(main.getByRole("heading", { level: 2, name: "Askbridge" })).toHaveCount(1);
    await expect(
      main.getByRole("img", { name: /^Askbridge homepage: the headline beside an example chat/ }),
    ).toBeVisible();
    await expect(main.getByRole("link", { name: "View Askbridge" })).toHaveAttribute(
      "href",
      "/products/askbridge",
    );
    await expect(main.getByRole("heading", { level: 2, name: "Relay" })).toHaveCount(1);
    await expect(
      main.getByRole("img", { name: /^Relay's Overview dashboard for an example workspace/ }),
    ).toBeVisible();
    await expect(main.getByRole("link", { name: "View Relay" })).toHaveAttribute(
      "href",
      "/products/relay",
    );
    // The four cards in order, then the closing card.
    await expect(main.getByRole("heading", { level: 2 })).toHaveText([
      "Fauward",
      "SOB Autofix",
      "Askbridge",
      "Relay",
      /.+/,
    ]);
    await expectNoA11yViolations(page);
    await expectNoHorizontalOverflowAt320(page);
  });

  test("/products/fauward: the sentence, the snapshot, and fauward.com in the same tab", async ({
    page,
  }) => {
    const response = await page.goto("/products/fauward");
    expect(response?.status()).toBe(200);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Fauward");
    await expect(page.locator("main")).toContainText(
      "Vitalos builds and operates Fauward, a logistics SaaS platform.",
    );
    const cta = page.getByRole("link", { name: "Open fauward.com" });
    await expect(cta).toHaveAttribute("href", "https://fauward.com");
    await expect(cta).toHaveAttribute("rel", "noopener");
    await expect(cta).not.toHaveAttribute("target", /.+/);
    const graph = JSON.parse(
      (await page.locator('script[type="application/ld+json"]').first().textContent()) ?? "{}",
    ) as { "@graph": { "@type": string; url?: string }[] };
    const software = graph["@graph"].find((node) => node["@type"] === "SoftwareApplication");
    expect(software?.url).toBe("https://fauward.com");
    await expectNoA11yViolations(page);
    await expectNoHorizontalOverflowAt320(page);
  });

  test("/products/askbridge: the sentence, the snapshot, and askbridge.vitalos.co.uk in the same tab", async ({
    page,
  }) => {
    const response = await page.goto("/products/askbridge");
    expect(response?.status()).toBe(200);
    await expect(page).toHaveTitle("Askbridge: AI Website Assistant and Live Chat | Vitalos");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Askbridge");
    await expect(page.locator("main")).toContainText(
      "Vitalos builds and operates Askbridge, an AI website assistant and live chat.",
    );
    const cta = page.getByRole("link", { name: "Open askbridge.vitalos.co.uk" });
    await expect(cta).toHaveAttribute("href", "https://askbridge.vitalos.co.uk");
    await expect(cta).toHaveAttribute("rel", "noopener");
    await expect(cta).not.toHaveAttribute("target", /.+/);
    await expect(cta).toHaveAttribute("data-product", "askbridge");
    await expectNoA11yViolations(page);
    await expectNoHorizontalOverflowAt320(page);
  });

  test("/products/relay: the sentence, the sample-data snapshot, and relay.vitalos.co.uk in the same tab", async ({
    page,
  }) => {
    const response = await page.goto("/products/relay");
    expect(response?.status()).toBe(200);
    await expect(page).toHaveTitle("Relay: Social Media Publishing for Teams | Vitalos");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Relay");
    const main = page.locator("main");
    await expect(main).toContainText("Products · Social media");
    await expect(main).toContainText(
      "Vitalos builds and operates Relay, a social media publishing platform for teams.",
    );
    await expect(main).toContainText("with sample data");
    await expect(
      main.getByRole("img", { name: /^Relay's Overview dashboard for an example workspace/ }),
    ).toBeVisible();
    const cta = page.getByRole("link", { name: "Open relay.vitalos.co.uk" });
    await expect(cta).toHaveAttribute("href", "https://relay.vitalos.co.uk");
    await expect(cta).toHaveAttribute("rel", "noopener");
    await expect(cta).not.toHaveAttribute("target", /.+/);
    await expect(cta).toHaveAttribute("data-product", "relay");
    const graph = JSON.parse(
      (await page.locator('script[type="application/ld+json"]').first().textContent()) ?? "{}",
    ) as { "@graph": { "@type": string; url?: string }[] };
    const software = graph["@graph"].find((node) => node["@type"] === "SoftwareApplication");
    expect(software?.url).toBe("https://relay.vitalos.co.uk");
    await expectNoA11yViolations(page);
    await expectNoHorizontalOverflowAt320(page);
  });

  test("/products/sob-autofix: the product page template, and sobautofix.com in the same tab", async ({
    page,
  }) => {
    // Collect layout shifts from the first paint.
    await page.addInitScript(() => {
      (window as unknown as { __cls: number }).__cls = 0;
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries() as unknown as {
          value: number;
          hadRecentInput: boolean;
        }[]) {
          if (!entry.hadRecentInput) (window as unknown as { __cls: number }).__cls += entry.value;
        }
      }).observe({ type: "layout-shift", buffered: true });
    });
    const response = await page.goto("/products/sob-autofix");
    expect(response?.status()).toBe(200);
    await expect(page).toHaveTitle("SOB Autofix: Workshop Booking and Operations | Vitalos");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("SOB Autofix");
    const main = page.locator("main");
    await expect(main).toContainText("Products · Automotive services");
    // The product page template (docs/content/PRODUCT-PAGE-TEMPLATE.md), as on Fauward.
    await expect(main.getByRole("heading", { level: 2 })).toHaveText([
      "What it does",
      "How it works",
      "Built for",
      // The closing card.
      /.+/,
    ]);
    await expect(
      main.getByRole("list", { name: "How it works" }).getByRole("listitem"),
    ).toHaveCount(4);
    const image = main.getByRole("img", { name: /^SOB Autofix booking flow, step 1 of 7/ });
    await expect(image).toBeVisible();
    // Sized by the slot, so the frame is reserved before the file loads.
    await expect(image).toHaveAttribute("width", /\d+/);
    await expect(image).toHaveAttribute("height", /\d+/);
    const cta = page.getByRole("link", { name: "Open sobautofix.com" });
    await expect(cta).toHaveAttribute("href", "https://sobautofix.com");
    await expect(cta).toHaveAttribute("rel", "noopener");
    await expect(cta).not.toHaveAttribute("target", /.+/);
    // outbound_click reads the slug from the link (the product copy stays out of the client bundle).
    await expect(cta).toHaveAttribute("data-product", "sob-autofix");
    const graph = JSON.parse(
      (await page.locator('script[type="application/ld+json"]').first().textContent()) ?? "{}",
    ) as { "@graph": { "@type": string; url?: string; applicationCategory?: string }[] };
    const software = graph["@graph"].find((node) => node["@type"] === "SoftwareApplication");
    expect(software?.url).toBe("https://sobautofix.com");
    expect(software?.applicationCategory).toBe("BusinessApplication");
    expect(graph["@graph"].some((node) => node["@type"] === "BreadcrumbList")).toBe(true);
    await expectNoA11yViolations(page);
    await expectNoHorizontalOverflowAt320(page);
    const cls = await page.evaluate(() => (window as unknown as { __cls: number }).__cls);
    expect(cls).toBeLessThanOrEqual(0.1);
  });

  test("an unknown product is a 404", async ({ page }) => {
    const response = await page.goto("/products/not-a-product");
    expect(response?.status()).toBe(404);
  });

  test("About says once that Vitalos builds and operates Fauward, linked to its page", async ({
    page,
  }) => {
    test.skip(!isDraftRun, "the fixture About body is generic; the sentence is repo copy");
    await page.goto("/about");
    const text = ((await page.locator("main").textContent()) ?? "").replace(/\s+/g, " ");
    expect(
      text.split("Vitalos builds and operates Fauward, a logistics SaaS platform."),
    ).toHaveLength(2);
    await expect(
      page.locator("main").getByRole("link", { name: "Fauward", exact: true }),
    ).toHaveAttribute("href", "/products/fauward");
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    // About is unchanged by the second product.
    expect(text).not.toContain("SOB Autofix");
  });
});
