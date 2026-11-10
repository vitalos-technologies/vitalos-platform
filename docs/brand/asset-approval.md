# Brand asset approval

## Canonical source

- Figma file: `Vitalos Brand System — Direction 01`
- File ID: `8NzuSwlDp1TpchZ5BUZHLO`
- Approved page: `Vitalos — Direction 01`
- Review date: 2026-09-16

## Approved

The converging-path `X` symbol, `VITALOS` wordmark, horizontal lockup, and the
descriptor `Technology Consulting & Engineering` are approved as the canonical
vector identity direction. Production exports must come from this Figma source,
not from raster files found in Drive or Downloads.

## Reconciliation required before asset export

The Figma board labels its primary blue as Cobalt `#2F6BFF`; the strategy source
locks Vitalos Blue to `#2457FF`. The strategy value remains authoritative until
the Figma styles are reconciled. Midnight remains `#081A2A`.

## Production imagery

No production photography or image library is present in the reviewed Figma
file. Imagery is therefore not approved by this record. It requires a separate
rights-cleared asset handoff and approval before publication.

## Interim raster logos (owner direction, 12 and 15 Oct 2026)

The owner directed that the supplied raster logo (`vitalos-logo (8).png`, 2172x724) be used on
the site in place of the text wordmark. Both files are interim until the Figma vector exports
above are produced, when SVGs should replace them.

- **Footer (12 Oct 2026).** `apps/web/public/brand/vitalos-logo-white.png` (937x160) is that file
  with every visible pixel set to white, its alpha kept and the transparent margin trimmed.
- **Header (15 Oct 2026).** `apps/web/public/brand/vitalos-logo.png` (940x160) is that file in full
  colour, with the transparent margin trimmed and the colours reduced to a 256-colour palette. A
  logo supplied in site settings takes precedence over it.
- **Site icon (15 Oct 2026).** The owner directed that the supplied symbol (`vitalos-logo (7).png`,
  1254x1254, the V mark alone) be the site icon. `apps/web/app/favicon.ico` (16, 32 and 48 px),
  `apps/web/app/icon.png` (512 px, transparent) and `apps/web/app/apple-icon.png` (180 px, on white)
  are that mark trimmed and centred on a square canvas. The same mark, trimmed and 128px high
  (`apps/web/public/brand/vitalos-mark.png`), replaces the header lockup below 400px wide, where
  the lockup would push the menu and action off screen.

## Homepage hero photograph (owner direction, 15 Oct 2026)

The owner supplied `Futuristic Cloud Infrastructure at Sunrise.png` (1672x941) and directed that it
be the homepage hero background under a solid black overlay. It is served as WebP at 1672 and 960 px
wide from `apps/web/public/images/hero/`, under a 72% black overlay (darkened from 60% on the same day), with the hero copy on the dark
tone. This record covers that one placement only. Other imagery still needs the separate
rights-cleared handoff described above.

## Practice illustrations (owner direction, 15 Oct 2026)

The owner supplied five illustrations (`ChatGPT Image Oct 15, 2026, …-1.png` to `-5.png`, each
1672x941) for the homepage "Five practices, one firm" section. They are served as WebP at 1672
and 960 px wide from `apps/web/public/images/practices/` and chosen by the locked practice names
(`apps/web/src/lib/view-mapping/practice-images.ts`). The files were not labelled, so each was
matched to the practice it depicts: 1 Consulting (analytics, architecture layers, a roadmap to a
target), 5 Engineering (code, platform layers, servers, database), 4 AI & Data (data sources into
a model, then charts), 2 Experience (mobile and web screens, accessibility, commerce) and 3 Managed
Services (dashboards, security, support, cloud). This record covers that section only.

## Solution illustrations (owner direction, 15 Oct 2026)

The owner supplied six square illustrations on transparent backgrounds (`ChatGPT Image Oct 15,
2026, 11_51_…-1.png` to `-5.png` and `Reliable Uptime Recovery Icon.png`, each 1254x1254) for the
homepage "Problems we solve" panel. They are served as WebP at 800 and 480 px from
`apps/web/public/images/solutions/` and chosen by the locked solution names
(`apps/web/src/lib/view-mapping/solution-images.ts`). Matched by what each depicts: 1 AI
Transformation (an AI chip between data and charts), 4 Business Process Modernisation (checked
process steps around a gear), 3 Digital Product Transformation (web and mobile screens, a rocket),
5 Application Modernisation (an application moving to servers and cloud), 2 Data & Intelligence
Transformation (a database feeding dashboards), and the uptime icon Technology Recovery &
Reliability (a server, a health monitor, a shield and recovery arrows).

## Delivery lifecycle discs (owner direction, 15 Oct 2026)

The owner supplied `Blue Circular Workflow Cycle.png` (1254x1254) for the homepage "From strategy
to production" band and asked for its white background to be removed. Its nine discs already run
clockwise from the top in the locked stage order (Qualify, Discover, Define, Design, Engineer,
Validate, Release, Operate, Improve), so each disc was cut out with a circular mask (no
background survives) and saved as a 192 px transparent WebP in
`apps/web/public/images/how-we-work/`. The ring, arrows and labels are drawn by the page
(`ProcessCycle`), so each stage can be interactive.

## Industry photographs (owner direction, 15 Oct 2026)

The owner supplied four photographs (`ChatGPT Image Oct 15, 2026, 01_28_16 PM-1.png` to
`01_28_18 PM-4.png`, each 1448x1086, AI-generated scenes of people at work) for the homepage
Industries panels. In order they show a clinical team (Health & Care), a store checkout (Retail,
Commerce & Consumer), a warehouse (Operations, Industry & Logistics) and a team at a data
dashboard (Growth & Technology). They are served as WebP at 1200 and 640 px wide from
`apps/web/public/images/industries/`, chosen by the locked industry names
(`apps/web/src/lib/view-mapping/industry-images.ts`), as decorative backgrounds under a midnight
gradient. They illustrate the sectors only; they are not clients or case studies and must not be
captioned or used as if they were.

## Fauward snapshot (owner direction, 17 Oct 2026)

The owner asked for a real snapshot of fauward.com (a Vitalos product) for the Products pages. The dashboard illustration in the fauward.com hero was captured with Playwright on 17 Oct 2026, at 1440x900 and 390x844 (device scale 2). The cookie banner was dismissed with "Essential only" and the chat launcher was hidden. Nothing else was changed. The images were cropped to the slot ratios (21:9, and 5:7 for phones), trimming about 9 px of edge, and saved as AVIF and WebP at full and half width as `apps/web/public/media/products.fauward.hero[.mobile][@1x].{avif,webp}` (slot `products.fauward.hero`). The figures in the illustration (shipments, drivers, revenue, SLA) are the sample data fauward.com itself shows. They are not Vitalos or client results and must not be quoted as such. Recapture when the fauward.com hero changes.

**Update, 19 Oct 2026 (owner direction):** the owner replaced this capture with their own composite of the Fauward tenant portal ("Fauward Tenant Portal Dashboard.png", 1672x941): the operations dashboard in front of the finance and Fauward Go screens. The slot is now 16:9 at that size, saved as AVIF and WebP at full and half width; the phone version (5:7, 672x941) is the dashboard window cropped from it, with nothing else changed. The tenant (Harbourline), people, addresses and figures in it are the portal's sample data, not a client, person or result, and must not be quoted as such.

## SOB Autofix snapshots (owner direction, 17 Oct 2026)

Three public pages of sobautofix.com (a Vitalos product) were captured with Playwright on 17 Oct 2026, at 1440x900 and 390x844 (device scale 2): booking step 1 (`/book`), the homepage and Get a Quote (`/get-a-quote`). Optional cookies were declined with "Essential only". The floating WhatsApp launcher and the focus ring the booking wizard puts on its heading at load were hidden. No registration was entered, and Manage Booking was not opened. Nothing else was changed.

The images were cropped to the slot ratios and saved as AVIF and WebP at full and half width, as `apps/web/public/media/products.sob-autofix.{hero,home,quote}[.mobile][@1x].{avif,webp}`:

- booking: 21:9, with a 5:7 phone version
- homepage and quote: 16:9, each with a 5:7 phone version

"AB12 CDE" is the site's own placeholder registration, not a real vehicle. The photograph in the homepage hero is SOB Autofix's own. Recapture when those pages change.

**Update, 17 Oct 2026 (product page template):** the homepage and quote captures were retired with the page's "More of the site" band; only the booking snapshot (`products.sob-autofix.hero`) remains. The snapshot of any product can now be recaptured with `pnpm media:product-snapshot` (`docs/content/PRODUCT-PAGE-TEMPLATE.md`); this one with `--url https://sobautofix.com/book --consent "Essential only" --hide 'a[href*="wa.me"]' --top 95 --mobile-top 85`.

## Askbridge snapshot (owner request, 22 Oct 2026)

The homepage of askbridge.vitalos.co.uk (a Vitalos product) was captured on 22 Oct 2026 with `pnpm media:product-snapshot --slug askbridge --url https://askbridge.vitalos.co.uk/ --top 190 --mobile-top 0 --wait 6000`, at 1440x900 and 390x844 (device scale 2) with reduced motion. The site has no cookie banner or chat launcher, so nothing was declined or hidden, and nothing was signed in to or typed. The 21:9 wide crop starts 190 CSS px down so the headline and the example conversation both show; the 5:7 phone version is the top of the page. Files: `apps/web/public/media/products.askbridge.hero[.mobile][@1x].{avif,webp}`.

"Harbour Lettings", "Sam" and the conversation are the site's own fictional example, labelled "Example" on the page. Recapture when the homepage hero changes.

## Relay snapshot (owner decision, 10 Nov 2026)

Relay (relay.vitalos.co.uk, Vitalos's social media publishing product) supplied its own image: the Overview dashboard captured from its synthetic "Relay Showcase" workspace (Relay repository, `apps/web/public/marketing/overview-light.webp`, 2560x1600, produced by its `scripts/seed-marketing-showcase.ts` and `scripts/marketing-capture.mjs`). It is the same image relay.vitalos.co.uk shows in its hero, captioned there "Illustrative preview with example content." It was cropped to 16:9 from the top (2560x1440, the bottom 160 px trimmed) and saved at 2030x1142; the 5:7 phone version (733x1026) is the Overview and Upcoming panels cropped from it (x 545, full height). Both are AVIF and WebP at full and half width, with Next's sharp at the snapshot script's settings: `apps/web/public/media/products.relay.hero[.mobile][@1x].{avif,webp}` (slot `products.relay.hero`). Nothing else was changed.

The workspace, brands ("Lumen Lane Bakery", "Lumen Lane Events"), posts and figures (scheduled, in review, published "simulated") are sample data, not a client, person or result, and must not be quoted as such; the page caption says "with sample data". Replace it when Relay's hero image changes.
