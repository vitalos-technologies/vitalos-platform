import { describe, expect, it } from "vitest";
import { productBySlug, productPath, products } from "./products";
import { isValidSlug } from "./routes";

const words = (value: string) => value.trim().split(/\s+/).length;

describe("products", () => {
  it("each product has a valid slug, an https site and a description that names it once", () => {
    for (const product of products) {
      expect(isValidSlug(product.slug)).toBe(true);
      expect(new URL(product.url).protocol).toBe("https:");
      expect(product.description.split(product.name)).toHaveLength(2);
      // The site's description limits (content-seo.test.ts).
      expect(product.seo.description.length).toBeGreaterThanOrEqual(120);
      expect(product.seo.description.length).toBeLessThanOrEqual(155);
    }
  });

  it("lists Fauward, then SOB Autofix, then Askbridge, then Relay", () => {
    expect(products.map((product) => product.slug)).toEqual([
      "fauward",
      "sob-autofix",
      "askbridge",
      "relay",
    ]);
  });

  it("Fauward is at /products/fauward", () => {
    const fauward = productBySlug("fauward");
    expect(fauward?.description).toBe(
      "Vitalos builds and operates Fauward, a logistics SaaS platform.",
    );
    expect(fauward?.navLabel).toBe("Fauward — logistics SaaS");
    expect(fauward && productPath(fauward)).toBe("/products/fauward");
  });
});

/**
 * The product page template (docs/content/PRODUCT-PAGE-TEMPLATE.md), after the Fauward page:
 * every product, including the next one, has the same three bands in the same layouts.
 */
describe("product page template", () => {
  const shape = [
    { heading: "What it does", layout: "cards", min: 3, max: 6 },
    { heading: "How it works", layout: "steps", min: 3, max: 5 },
    { heading: "Built for", layout: "tiles", min: 2, max: 4 },
  ] as const;

  it.each(products.map((product) => [product.name, product] as const))(
    "%s has What it does (cards), How it works (steps) and Built for (tiles)",
    (_name, product) => {
      expect(product.sector.trim()).not.toBe("");
      expect(product.navDescription).toBe("Built and operated by Vitalos");
      expect(product.description).toMatch(
        new RegExp(`^Vitalos builds and operates ${product.name}, `),
      );
      expect(product.sections.map((section) => [section.heading, section.layout])).toEqual(
        shape.map((band) => [band.heading, band.layout]),
      );
      product.sections.forEach((section, index) => {
        const band = shape[index]!;
        const points = section.points ?? [];
        expect(points.length, section.heading).toBeGreaterThanOrEqual(band.min);
        expect(points.length, section.heading).toBeLessThanOrEqual(band.max);
        for (const point of points) {
          expect(words(point.title), point.title).toBeLessThanOrEqual(4);
          expect(words(point.text), point.text).toBeLessThanOrEqual(10);
        }
        // Cards and tiles carry an icon, chosen by key (ProductsTemplates.tsx `pointIcons`).
        if (band.layout !== "steps") {
          const keys = points.map((point) => point.key);
          expect(keys.every(Boolean), section.heading).toBe(true);
          expect(new Set(keys).size, section.heading).toBe(keys.length);
        }
      });
    },
  );

  it("repeats no prices, percentages or speed figures", () => {
    for (const product of products) {
      expect(JSON.stringify(product.sections), product.name).not.toMatch(
        /£|\$|€|\d+\s?%|\d+\s?(min|ms|seconds?)\b|uplift/i,
      );
    }
  });
});

describe("SOB Autofix", () => {
  const sob = productBySlug("sob-autofix")!;

  it("is at /products/sob-autofix, with its menu label and site", () => {
    expect(productPath(sob)).toBe("/products/sob-autofix");
    expect(sob.navLabel).toBe("SOB Autofix — workshop platform");
    expect(sob.url).toBe("https://sobautofix.com");
    expect(sob.sector).toBe("Automotive services");
  });

  it("states only the verified claims (docs/content/DISCOVERY-sob-autofix.md)", () => {
    const text = JSON.stringify(sob);
    // The booking wizard's seven steps, grouped into four on the page.
    expect(text).toContain("Seven steps");
    // Claims the evidence does not support stay out: no mobile eligibility check, no email in
    // Manage Booking, one area page.
    expect(text).not.toMatch(/eligib|postcode|radius/i);
    expect(text).not.toMatch(/email/i);
    expect(text).not.toMatch(/area pages/i);
  });
});

describe("Askbridge", () => {
  const askbridge = productBySlug("askbridge")!;

  it("is at /products/askbridge, with its menu label and site", () => {
    expect(productPath(askbridge)).toBe("/products/askbridge");
    expect(askbridge.navLabel).toBe("Askbridge — AI website assistant");
    expect(askbridge.url).toBe("https://askbridge.vitalos.co.uk");
    expect(askbridge.sector).toBe("Customer service");
  });

  it("states only the verified claims (docs/content/DISCOVERY-askbridge.md)", () => {
    const text = JSON.stringify(askbridge);
    expect(text).toContain("numbered sources");
    // Claims the evidence does not support stay out: no plan prices or allowances, no customer
    // results (the site's businesses are fictional), no calendar booking, no languages.
    expect(text).not.toMatch(/£|conversations a month|trial/i);
    expect(text).not.toMatch(/customers? (say|use)|case stud|harbour lettings/i);
    expect(text).not.toMatch(/calendar|books? viewings/i);
    expect(text).not.toMatch(/languages|multilingual/i);
  });
});

describe("Relay", () => {
  const relay = productBySlug("relay")!;

  it("is at /products/relay, with its menu label and site", () => {
    expect(productPath(relay)).toBe("/products/relay");
    expect(relay.navLabel).toBe("Relay — social media publishing");
    expect(relay.url).toBe("https://relay.vitalos.co.uk");
    expect(relay.sector).toBe("Social media");
    // The snapshot is a capture of an example workspace: the caption says so.
    expect(relay.snapshotCaption).toMatch(/sample data/);
  });

  it("states only the verified claims (docs/content/DISCOVERY-relay.md)", () => {
    const text = JSON.stringify(relay);
    expect(text).toContain("One calendar for every brand and channel.");
    // Claims the evidence does not support, or the template does not allow, stay out: no plan
    // prices, trial or allowances; no named networks (each waits on its provider's approval); no
    // listening, automation, integrations or MCP (Professional-only, not on this page); no
    // customers or results (the showcase workspace is synthetic); not the legacy chat assistant.
    expect(text).not.toMatch(/£|trial|free|per user|allowance|unlimited/i);
    expect(text).not.toMatch(/instagram|facebook|linkedin|tiktok|threads|youtube|bluesky|\bx\b/i);
    expect(text).not.toMatch(/listening|automation|integrations?|mcp/i);
    expect(text).not.toMatch(/customers? (say|use)|case stud|lumen lane|bakery/i);
    expect(text).not.toMatch(/website assistant|vitalos\.co\.uk chat|askbridge/i);
  });
});
