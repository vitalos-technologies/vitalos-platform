import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { productBySlug, products } from "@vitalos/cms";
import { ProductTemplate, ProductsIndexTemplate, pointIcons } from "./ProductsTemplates";

const html = (node: React.ReactNode) => renderToStaticMarkup(<>{node}</>);
const fauward = productBySlug("fauward")!;

/** The product page template (docs/content/PRODUCT-PAGE-TEMPLATE.md), for every product. */
describe("product template", () => {
  it.each(products.map((product) => [product.name, product] as const))(
    "%s renders as the template: hero, snapshot, cards, steps, tiles, closing card",
    (_name, product) => {
      const markup = html(<ProductTemplate product={product} />);
      expect(markup).toContain(`Products · ${product.sector}`);
      expect(markup.match(/<h1[\s>]/g)).toHaveLength(1);
      // The bands in order, then the closing card.
      const order = ["What it does", "How it works", "Built for"].map((heading) =>
        markup.indexOf(`>${heading}</h2>`),
      );
      expect(order.every((index) => index > -1)).toBe(true);
      expect([...order].sort((a, b) => a - b)).toEqual(order);
      // Every card and tile title, as an h3.
      for (const section of product.sections) {
        if (section.layout === "steps") continue;
        for (const point of section.points ?? []) {
          expect(markup).toContain(`>${point.title.replaceAll("&", "&amp;")}</h3>`);
        }
      }
      // Steps: one ordered list, named by its heading, numbered from 01.
      const steps = product.sections.find((section) => section.layout === "steps")!;
      expect(markup).toMatch(/<ol[^>]*aria-label="How it works"/);
      expect(markup).toContain(`>0${steps.points!.length}<`);
      // Its own site, in the same tab, marked for outbound_click.
      expect(markup).toContain(`data-product="${product.slug}"`);
      expect(markup).not.toContain('target="_blank"');
    },
  );

  it("has an icon for every card and tile key", () => {
    for (const product of products) {
      for (const section of product.sections) {
        if (section.layout === "steps") continue;
        for (const point of section.points ?? []) {
          expect(pointIcons[point.key ?? ""], `${product.name}: ${point.title}`).toBeDefined();
        }
      }
    }
  });

  it("keeps each page short: at most 180 words of body copy", () => {
    for (const product of products) {
      const words = [
        product.description,
        product.snapshotCaption,
        ...product.sections.flatMap((section) => [
          section.heading,
          ...(section.points ?? []).flatMap((point) => [point.title, point.text]),
        ]),
      ]
        .join(" ")
        .split(/\s+/)
        .filter(Boolean);
      expect(words.length, product.name).toBeLessThanOrEqual(180);
    }
  });

  it("shows the SOB Autofix booking snapshot", () => {
    const markup = html(<ProductTemplate product={productBySlug("sob-autofix")!} />);
    expect(markup).toContain("SOB Autofix booking flow, step 1 of 7");
    expect(markup).toMatch(/href="https:\/\/sobautofix\.com"[^>]*rel="noopener"/);
  });

  it("shows the Askbridge homepage snapshot and links to its site", () => {
    const markup = html(<ProductTemplate product={productBySlug("askbridge")!} />);
    expect(markup).toContain("Askbridge homepage: the headline beside an example chat");
    expect(markup).toMatch(/href="https:\/\/askbridge\.vitalos\.co\.uk"[^>]*rel="noopener"/);
  });

  it("shows the Relay dashboard snapshot, captioned as sample data, and links to its site", () => {
    const markup = html(<ProductTemplate product={productBySlug("relay")!} />);
    expect(markup).toContain("Overview dashboard for an example workspace");
    expect(markup).toContain("with sample data");
    expect(markup).toMatch(/href="https:\/\/relay\.vitalos\.co\.uk"[^>]*rel="noopener"/);
  });

  it("still shows Fauward's tenant portal snapshot", () => {
    expect(html(<ProductTemplate product={fauward} />)).toContain(
      "Fauward tenant portal: the operations dashboard, with the finance and Fauward Go screens behind it",
    );
  });
});

describe("products index", () => {
  it("shows Fauward, then SOB Autofix, then Askbridge, then Relay", () => {
    const markup = html(<ProductsIndexTemplate page={null} products={products} />);
    expect(markup.indexOf("View Fauward")).toBeGreaterThan(-1);
    expect(markup.indexOf("View Fauward")).toBeLessThan(markup.indexOf("View SOB Autofix"));
    expect(markup).toContain('href="/products/sob-autofix"');
    expect(markup.indexOf("View SOB Autofix")).toBeLessThan(markup.indexOf("View Askbridge"));
    expect(markup).toContain('href="/products/askbridge"');
    expect(markup.indexOf("View Askbridge")).toBeLessThan(markup.indexOf("View Relay"));
    expect(markup).toContain('href="/products/relay"');
  });
});
