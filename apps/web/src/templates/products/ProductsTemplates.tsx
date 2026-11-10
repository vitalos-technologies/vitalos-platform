import { navLabels, productPath, routes } from "@vitalos/cms";
import type { ProductPoint, ProductSection, ProductView, RoutePageView } from "@vitalos/cms";
import { Button, FeatureGrid, Icon, ProcessJourney, RevealItem } from "@vitalos/ui";
import type { IconName, ProcessJourneyProps, SectionTone } from "@vitalos/ui";
import { MediaSlot } from "../../components/media-slot";
import { isMediaSlotId } from "../../content/media-slots";
import { trail } from "../../lib/view-mapping/breadcrumbs";
import { Band, ClosingBand, PageIntro, renderBands } from "../commercial/bands";
import type { BandFactory } from "../commercial/bands";
import { PageMain } from "../institutional/page-main";

/**
 * The Products section (owner direction, 17 Oct 2026), in the site's patterns. A product page is
 * the product page template (docs/content/PRODUCT-PAGE-TEMPLATE.md, after the Fauward page): the
 * compact dark hero, the snapshot, "What it does" (icon cards), "How it works" (numbered steps on
 * the dark band), "Built for" (tiles), then the closing "Talk to Vitalos" card. Every word comes
 * from `@vitalos/cms` (products.ts and the Products route page); the snapshot is the
 * `products.{slug}.hero` slot.
 */

export const productsTrail = () => trail({ label: navLabels.products, path: routes.products() });

export const productTrail = (product: ProductView) =>
  trail(
    { label: navLabels.products, path: routes.products() },
    { label: product.name, path: productPath(product) },
  );

/** The product's snapshot: its `products.{slug}.hero` slot, or nothing when none is registered. */
function ProductSnapshot({ product, sizes }: Readonly<{ product: ProductView; sizes: string }>) {
  const id = `products.${product.slug}.hero`;
  return isMediaSlotId(id) ? <MediaSlot id={id} sizes={sizes} /> : null;
}

/** A headed section's points: an h3 and a paragraph each, between hairlines, two abreast from md. */
function SectionPoints({ points }: Readonly<{ points: NonNullable<ProductSection["points"]> }>) {
  return (
    <ul className="m-0 grid list-none grid-cols-1 gap-x-(--space-7) p-0 md:grid-cols-2">
      {points.map((point) => (
        <RevealItem
          as="li"
          key={point.title}
          className="min-w-0 border-t border-tone-border py-(--space-5)"
        >
          <h3 className="m-0 text-body-l font-semibold text-balance text-tone-heading">
            {point.title}
          </h3>
          <p className="m-0 mt-(--space-2) text-body text-pretty text-tone-text">{point.text}</p>
        </RevealItem>
      ))}
    </ul>
  );
}

/**
 * Subject icons for section points, by the point's `key` (decorative: the title carries it). A new
 * product adds its keys here; `ProductsTemplates.test.tsx` fails when a card or tile has none.
 */
export const pointIcons: Readonly<Record<string, IconName>> = {
  // Fauward
  shipments: "workflow",
  "white-label": "layers",
  "field-app": "target",
  finance: "document",
  agent: "chip",
  api: "code",
  courier: "compass",
  freight: "server",
  "3pl": "users",
  enterprise: "building",
  // SOB Autofix
  booking: "workflow",
  times: "clock",
  manage: "link",
  quote: "document",
  privacy: "shield",
  admin: "window",
  drivers: "gauge",
  mobile: "compass",
  "car-buyers": "search",
  workshop: "users",
  // Askbridge
  knowledge: "document",
  sources: "link",
  handover: "users",
  inbox: "mail",
  offline: "clock",
  install: "code",
  lettings: "building",
  services: "target",
  "product-questions": "search",
  "support-teams": "chip",
  // Relay
  calendar: "table",
  "per-network": "layers",
  collaboration: "users",
  "social-inbox": "mail",
  analytics: "chart",
  assistant: "chip",
  teams: "person",
  brands: "flag",
  "customer-care": "check",
};

const withIcon = (point: ProductPoint) => ({
  title: point.title,
  text: point.text,
  ...(point.key && pointIcons[point.key] ? { icon: pointIcons[point.key] } : {}),
});

/** A section's points in its layout (ProductSection `layout`). */
function SectionBody({ section }: Readonly<{ section: ProductSection }>) {
  const points = section.points ?? [];
  const [first, ...rest] = points;
  if (!first) return null;
  switch (section.layout ?? "points") {
    case "cards":
      return <FeatureGrid items={points.map(withIcon)} columns={3} headingLevel={3} />;
    case "tiles":
      return <FeatureGrid items={points.map(withIcon)} columns={4} headingLevel={3} />;
    case "steps": {
      const stage = (point: ProductPoint) => ({ title: point.title, summary: point.text });
      const stages: ProcessJourneyProps["stages"] = [stage(first), ...rest.map(stage)];
      return <ProcessJourney aria-label={section.heading} stages={stages} />;
    }
    case "points":
      return <SectionPoints points={points} />;
  }
}

/** The product's sections after the snapshot, each a headed band in its layout. */
function productBands(product: ProductView): BandFactory[] {
  return product.sections.map((section): BandFactory => {
    function sectionBand(tone: SectionTone) {
      return (
        <Band
          // Numbered steps sit on the dark tone, like the homepage lifecycle band.
          tone={section.layout === "steps" ? "dark" : tone}
          heading={section.heading}
          eyebrow={product.name}
          intro={section.intro}
        >
          <SectionBody section={section} />
        </Band>
      );
    }
    return sectionBand;
  });
}

/** One product as a card: the snapshot, the name, one line and the link to its page. */
function ProductCard({ product }: Readonly<{ product: ProductView }>) {
  return (
    <article className="group relative flex h-full min-w-0 flex-col gap-(--space-5) overflow-hidden rounded-2xl border border-tone-border bg-tone-bg p-(--space-5) transition-[border-color,translate] duration-(--duration-feedback) ease-(--ease-emphasis) focus-within:-translate-y-1 focus-within:border-tone-action hover:-translate-y-1 hover:border-tone-action motion-reduce:focus-within:translate-y-0 motion-reduce:hover:translate-y-0">
      <ProductSnapshot product={product} sizes="(min-width: 1024px) 40vw, 92vw" />
      <div className="flex min-w-0 flex-1 flex-col gap-(--space-3)">
        <h2 className="m-0 text-h3 text-balance text-tone-heading">{product.name}</h2>
        <p className="m-0 text-body text-pretty text-tone-text">{product.summary}</p>
        <a
          href={productPath(product)}
          className="mt-auto inline-flex min-h-11 items-center gap-(--space-2) self-start text-small font-semibold text-tone-link no-underline after:absolute after:inset-0 after:content-[''] hover:underline"
        >
          {product.viewLabel}
          <Icon
            name="arrow-right"
            size={16}
            className="transition-transform duration-(--duration-feedback) ease-(--ease-standard) group-hover:translate-x-0.5"
          />
        </a>
      </div>
    </article>
  );
}

export function ProductsIndexTemplate({
  page,
  products,
}: Readonly<{ page: RoutePageView | null; products: readonly ProductView[] }>) {
  return (
    <PageMain>
      <PageIntro
        crumbs={productsTrail()}
        compact
        title={page?.heading ?? navLabels.products}
        lead={page?.intro}
      />
      {renderBands(
        [
          (tone) =>
            products.length > 0 ? (
              <Band tone={tone}>
                <ul className="m-0 grid list-none grid-cols-1 gap-(--space-4) p-0 lg:grid-cols-2">
                  {products.map((product) => (
                    <li key={product.slug} className="min-w-0">
                      <ProductCard product={product} />
                    </li>
                  ))}
                </ul>
              </Band>
            ) : null,
        ],
        "light",
      )}
      <ClosingBand />
    </PageMain>
  );
}

export function ProductTemplate({ product }: Readonly<{ product: ProductView }>) {
  return (
    <PageMain>
      <PageIntro
        crumbs={productTrail(product)}
        compact
        eyebrow={`${navLabels.products} · ${product.sector}`}
        title={product.name}
        lead={product.description}
        actions={
          // Its own site, in the same tab: it is a Vitalos product.
          <Button href={product.url} rel="noopener" data-product={product.slug} size="lg" arrow>
            {product.urlLabel}
          </Button>
        }
      />
      {renderBands(
        [
          (tone) => (
            <Band tone={tone}>
              <figure className="mx-auto my-0 max-w-[64rem]">
                <ProductSnapshot product={product} sizes="(min-width: 70rem) 64rem, 92vw" />
                <figcaption className="mt-(--space-4) max-w-(--container-prose) text-small text-pretty text-tone-muted">
                  {product.snapshotCaption}
                </figcaption>
              </figure>
            </Band>
          ),
          ...productBands(product),
        ],
        "light",
      )}
      <ClosingBand />
    </PageMain>
  );
}
