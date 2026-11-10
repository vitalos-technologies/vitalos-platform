/**
 * The image slot registry (pages redesign, 15 Oct 2026; docs/design/DECISIONS.md). Every
 * `<MediaSlot>` names one of these ids, and the type makes an unregistered id a compile error.
 * `pnpm media:slots` writes docs/design/IMAGE-SLOTS.md from this file, and a unit test fails when
 * the document is out of date.
 *
 * To add the real image: save it as `apps/web/public/media/{file}.{avif,webp,jpg,png}` at the
 * recommended size (for a per-item slot, `{file}` is the id, a dot, then the item's slug). The
 * slot renders it in place of the placeholder; nothing shifts, because the ratio is fixed here.
 *
 * Rules: real photography, screenshots or diagrams of Vitalos work only. No stock or
 * AI-generated imagery, and nothing that implies a client, outcome or person that is not real.
 *
 * This file has no imports, so `node` can load it directly (type stripping) for the doc script.
 */

export type MediaRatio = "16:9" | "4:3" | "1:1" | "3:2" | "21:9" | "5:7";

export interface MediaSlotEntry {
  id: string;
  page: string;
  section: string;
  ratio: MediaRatio;
  /** Recommended pixel size, width × height. */
  size: readonly [number, number];
  /** What the image should show. */
  brief: string;
  /**
   * Draft alt text, for owner review. In a per-item slot, `{name}` is replaced by the item's
   * title (MediaSlot `itemName`), so each image says what it shows (docs/seo/AUDIT.md).
   */
  alt: string;
  /** One image per item (for example per lab asset): the file is `{id}.{slug}`. */
  perItem?: boolean;
  /**
   * A second capture for phones (below 768px), when the wide image would be unreadable there:
   * the file is `{file}.mobile`, at its own ratio and size.
   */
  mobile?: { ratio: MediaRatio; size: readonly [number, number] };
}

export const mediaSlots = [
  {
    id: "labs.asset",
    page: "/labs/[type]/[slug]",
    section: "Hero",
    ratio: "16:9",
    size: [1600, 900],
    brief:
      "A screenshot or diagram of the asset itself (framework page, harness output, assessment template). No decorative imagery.",
    alt: "A view of {name}.",
    perItem: true,
  },
  {
    id: "work.case-study",
    page: "/work/[slug]",
    section: "Hero",
    ratio: "16:9",
    size: [1600, 900],
    brief:
      "A screenshot or photograph of the delivered work, used only with the client's written permission.",
    alt: "The delivered work: {name}.",
    perItem: true,
  },
  {
    id: "insights.article",
    page: "/insights/[slug]",
    section: "Hero (article cover)",
    ratio: "16:9",
    size: [1600, 900],
    brief:
      "A cover that illustrates the article: a diagram, a screenshot or a real photograph. No stock or AI-generated imagery. Covers are uploaded in the Super Admin (Insights › Posts › Cover, ADR-039); an article without one shows no hero image.",
    alt: "Cover image for {name}.",
    perItem: true,
  },
  {
    id: "products.fauward.hero",
    page: "/products/fauward (and its card on /products)",
    section: "Snapshot",
    ratio: "16:9",
    size: [1672, 941],
    brief:
      "The owner's composite of the Fauward tenant portal with sample data: the operations dashboard in front of the finance and Fauward Go screens. The phone version is the dashboard window cropped from it.",
    alt: "Fauward tenant portal: the operations dashboard, with the finance and Fauward Go screens behind it",
    mobile: { ratio: "5:7", size: [672, 941] },
  },
  {
    id: "products.sob-autofix.hero",
    page: "/products/sob-autofix (and its card on /products)",
    section: "Snapshot",
    ratio: "21:9",
    size: [2030, 870],
    brief:
      "Step 1 of the booking flow on sobautofix.com/book, captured with Playwright at 1440 wide (2x) with optional cookies declined, the focus ring and the WhatsApp launcher hidden, and no registration entered. The phone version is the same step at 390 wide.",
    alt: "SOB Autofix booking flow, step 1 of 7: the vehicle registration lookup with a manual-entry option",
    mobile: { ratio: "5:7", size: [733, 1026] },
  },
  {
    id: "products.askbridge.hero",
    page: "/products/askbridge (and its card on /products)",
    section: "Snapshot",
    ratio: "21:9",
    size: [2030, 870],
    brief:
      "The homepage hero of askbridge.vitalos.co.uk, captured with Playwright at 1440 wide (2x) with reduced motion, cropped from 190 CSS px so the headline and the example conversation (fictional Harbour Lettings) both show. The phone version is the same page at 390 wide, from the top.",
    alt: "Askbridge homepage: the headline beside an example chat with numbered sources and a team member joining",
    mobile: { ratio: "5:7", size: [733, 1026] },
  },
  {
    id: "products.relay.hero",
    page: "/products/relay (and its card on /products)",
    section: "Snapshot",
    ratio: "16:9",
    size: [2030, 1142],
    brief:
      "Relay's own capture of its Overview dashboard in a synthetic showcase workspace (example bakery brands, simulated figures), the same image relay.vitalos.co.uk shows in its hero (marketing/overview-light.webp, 2560 x 1600). Cropped to 16:9 from the top; the phone version is the Overview and Upcoming panels cropped from it at 5:7.",
    alt: "Relay's Overview dashboard for an example workspace: scheduled and in-review counts, upcoming posts across several networks, and channel health",
    mobile: { ratio: "5:7", size: [733, 1026] },
  },
] as const satisfies readonly MediaSlotEntry[];

export type MediaSlotId = (typeof mediaSlots)[number]["id"];

/** True when `value` names a registered slot (for ids built from a slug, such as `products.{slug}.hero`). */
export function isMediaSlotId(value: string): value is MediaSlotId {
  return mediaSlots.some((slot) => slot.id === value);
}

/** The registry entry for an id. */
export function mediaSlot(id: MediaSlotId): MediaSlotEntry {
  const entry = mediaSlots.find((slot) => slot.id === id);
  if (!entry) throw new Error(`Unregistered media slot: ${id}`);
  return entry;
}

const cell = (value: string): string => value.replaceAll("|", "\\|");

/** docs/design/IMAGE-SLOTS.md, generated from the registry (`pnpm media:slots`). */
export function renderImageSlotsDoc(): string {
  const rows = mediaSlots.map((slot: MediaSlotEntry) =>
    [
      `\`${slot.id}${slot.perItem ? ".{slug}" : ""}\``,
      `\`${slot.page}\``,
      slot.section,
      slot.mobile ? `${slot.ratio} (phones: ${slot.mobile.ratio})` : slot.ratio,
      slot.mobile
        ? `${slot.size[0]} × ${slot.size[1]} (phones: ${slot.mobile.size[0]} × ${slot.mobile.size[1]})`
        : `${slot.size[0]} × ${slot.size[1]}`,
      cell(slot.brief),
      cell(slot.alt),
    ].join(" | "),
  );
  return [
    "# Image slots",
    "",
    "Generated from `apps/web/src/content/media-slots.ts` by `pnpm media:slots`. Do not edit by hand.",
    "",
    "To add an image: save it as `apps/web/public/media/{id}.webp` (or `.avif`, `.jpg`, `.png`) at the recommended size; for a per-item slot, use `{id}.{slug}`, for example `labs.asset.production-ai-evaluation-harness.webp`. A slot with a phone version also takes `{file}.mobile.{ext}`; add both `.avif` and `.webp` and the page offers each browser the best it supports.",
    "The slot shows it in place of the placeholder at the same ratio, so nothing shifts. Real photography, screenshots or diagrams only: no stock or AI-generated imagery.",
    "",
    "| Id | Page | Section | Ratio | Size (px) | Brief | Draft alt |",
    "| --- | --- | --- | --- | --- | --- | --- |",
    ...rows.map((row) => `| ${row} |`),
    "",
  ].join("\n");
}
