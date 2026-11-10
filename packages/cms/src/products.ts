/**
 * Products Vitalos builds and operates (owner direction, 17 Oct 2026). The single source for the
 * Products pages, the Who We Are menu, the footer, the About sentence, llms.txt and the
 * SoftwareApplication markup. Each product says only what its own site shows: no customer
 * numbers, features or prices.
 */
import { routes } from "./routes";

export interface ProductView {
  slug: string;
  /** The product's name: the h1 of its page and the title of its card. */
  name: string;
  /** Menu label: the name and what it is. */
  navLabel: string;
  /** One quiet line under the menu label. */
  navDescription: string;
  /** One line for the Products card. */
  summary: string;
  /** The one-sentence description: the About sentence and the lead of the product's page. */
  description: string;
  /** The product's own site (external, opened in the same tab). */
  url: string;
  /** Label of the action that opens the product's site. */
  urlLabel: string;
  /** Label of the card link to the product's page. */
  viewLabel: string;
  /** Caption of the snapshot on the product's page: what the image shows, nothing more. */
  snapshotCaption: string;
  /** schema.org `applicationCategory`. */
  applicationCategory: "BusinessApplication";
  seo: { title: string; description: string };
  /** The sector, after "Products" in the page's eyebrow. */
  sector: string;
  /**
   * The body bands after the snapshot, in the product page template's order
   * (docs/content/PRODUCT-PAGE-TEMPLATE.md): "What it does" (cards), "How it works" (steps) and
   * "Built for" (tiles). `products.test.ts` holds every product to that shape.
   */
  sections: readonly ProductSection[];
}

/**
 * A headed band: an introduction, then optional headed points. `layout` sets how the points show:
 * `points` (default) as headed paragraphs between hairlines; `cards` as icon cards; `steps` as a
 * numbered sequence; `tiles` as a row of short icon cards. Cards, steps and tiles suit short
 * points (a title of four words or fewer and a line of ten).
 */
export interface ProductSection {
  heading: string;
  intro?: string;
  layout?: "points" | "cards" | "steps" | "tiles";
  points?: readonly ProductPoint[];
}

/** One point of a section. `key` is stable: the web app picks the point's icon by it. */
export interface ProductPoint {
  key?: string;
  title: string;
  text: string;
}

export const products: readonly ProductView[] = [
  {
    slug: "fauward",
    name: "Fauward",
    navLabel: "Fauward — logistics SaaS",
    navDescription: "Built and operated by Vitalos",
    summary: "A logistics SaaS platform, built and operated by Vitalos.",
    description: "Vitalos builds and operates Fauward, a logistics SaaS platform.",
    url: "https://fauward.com",
    urlLabel: "Open fauward.com",
    viewLabel: "View Fauward",
    snapshotCaption:
      "The Fauward tenant portal: dashboard, finance and Fauward Go, with sample data.",
    applicationCategory: "BusinessApplication",
    seo: {
      title: "Fauward: Logistics SaaS Platform",
      description:
        "Fauward is the white-label logistics platform Vitalos builds and operates: shipments, branded tracking, a field app, invoicing and an operations agent.",
    },
    sector: "Logistics",
    // From fauward.com (17 Oct 2026): its services, its eight-step shipment workflow (in four
    // steps here) and the businesses it names. No prices, uptime or speed figures.
    sections: [
      {
        heading: "What it does",
        layout: "cards",
        points: [
          {
            key: "shipments",
            title: "Shipment operations",
            text: "Booking to proof of delivery, in one lifecycle.",
          },
          {
            key: "white-label",
            title: "White-label portal",
            text: "Your domain, colours and logo. Tracking with no login.",
          },
          {
            key: "field-app",
            title: "Fauward Go",
            text: "Offline-first field app: QR scans, photos, signatures.",
          },
          {
            key: "finance",
            title: "Finance & invoicing",
            text: "Invoices raised on delivery, payments reconciled.",
          },
          {
            key: "agent",
            title: "Fauward Agent",
            text: "Flags SLA risks and suggests actions. Dispatchers approve.",
          },
          {
            key: "api",
            title: "API & integrations",
            text: "REST API, webhooks and carrier integrations.",
          },
        ],
      },
      {
        heading: "How it works",
        layout: "steps",
        points: [
          { title: "Book and assign", text: "Each booking goes to an operator." },
          { title: "Collect and track", text: "Live GPS. Customers kept updated." },
          { title: "Deliver with proof", text: "Photo, signature or one-time code." },
          { title: "Invoice and reconcile", text: "Invoiced on delivery, then paid." },
        ],
      },
      {
        heading: "Built for",
        layout: "tiles",
        points: [
          { key: "courier", title: "Courier start-ups", text: "Launch under your own brand." },
          { key: "freight", title: "Freight operators", text: "Many depots, one source of truth." },
          { key: "3pl", title: "3PL providers", text: "A branded portal for each client." },
          { key: "enterprise", title: "Enterprise fleets", text: "SSO, audit logs and support." },
        ],
      },
    ],
  },
  // Every claim maps to a line in docs/content/DISCOVERY-sob-autofix.md (the SOB Autofix
  // repository and the live site, 17 Oct 2026): its booking flow (seven steps, in four here),
  // its other systems and the people it serves. No outcome figures: none are evidenced.
  {
    slug: "sob-autofix",
    name: "SOB Autofix",
    navLabel: "SOB Autofix — workshop platform",
    navDescription: "Built and operated by Vitalos",
    summary:
      "A booking and operations platform for a diagnostics-led vehicle workshop, built and operated by Vitalos.",
    description:
      "Vitalos builds and operates SOB Autofix, a booking and operations platform for a diagnostics-led vehicle workshop in Doncaster.",
    url: "https://sobautofix.com",
    urlLabel: "Open sobautofix.com",
    viewLabel: "View SOB Autofix",
    snapshotCaption: "Step 1 of 7 of the SOB Autofix booking flow, as sobautofix.com shows it.",
    applicationCategory: "BusinessApplication",
    seo: {
      title: "SOB Autofix: Workshop Booking and Operations",
      description:
        "SOB Autofix is the vehicle-first booking and operations platform Vitalos built and runs for a diagnostics-led vehicle workshop in Doncaster.",
    },
    sector: "Automotive services",
    sections: [
      {
        heading: "What it does",
        layout: "cards",
        points: [
          {
            key: "booking",
            title: "Vehicle-first booking",
            text: "Seven steps from registration lookup. No account needed.",
          },
          {
            key: "times",
            title: "Live appointment times",
            text: "From the workshop calendar, re-checked before confirming.",
          },
          {
            key: "manage",
            title: "Manage Booking",
            text: "Reschedule or cancel with reference and registration.",
          },
          {
            key: "quote",
            title: "Get a Quote",
            text: "Quote requests that start with the vehicle.",
          },
          {
            key: "privacy",
            title: "Private by design",
            text: "Registrations kept out of page addresses and analytics.",
          },
          {
            key: "admin",
            title: "Workshop admin",
            text: "Bookings, enquiries, content, stock and invoices together.",
          },
        ],
      },
      {
        heading: "How it works",
        layout: "steps",
        points: [
          { title: "Vehicle first", text: "Registration lookup, or the details by hand." },
          { title: "Work and symptoms", text: "Choose the service, describe the problem." },
          { title: "Place and time", text: "Workshop or mobile, then a live slot." },
          { title: "Review and confirm", text: "Book as a guest; manage it later." },
        ],
      },
      {
        heading: "Built for",
        layout: "tiles",
        points: [
          { key: "drivers", title: "Drivers", text: "Book a diagnosis without an account." },
          { key: "mobile", title: "Mobile visits", text: "Where the service allows it." },
          { key: "car-buyers", title: "Car buyers", text: "Cars for sale, with enquiries." },
          { key: "workshop", title: "Workshop staff", text: "One admin, with two-factor sign-in." },
        ],
      },
    ],
  },
  // Every claim maps to a line in docs/content/DISCOVERY-askbridge.md (the live site,
  // askbridge.vitalos.co.uk, 22 Oct 2026): its features, its three set-up steps plus the hand-off
  // (four here) and the businesses it names. No prices, allowances or outcome figures.
  {
    slug: "askbridge",
    name: "Askbridge",
    navLabel: "Askbridge — AI website assistant",
    navDescription: "Built and operated by Vitalos",
    summary: "An AI website assistant and live chat, built and operated by Vitalos.",
    description: "Vitalos builds and operates Askbridge, an AI website assistant and live chat.",
    url: "https://askbridge.vitalos.co.uk",
    urlLabel: "Open askbridge.vitalos.co.uk",
    viewLabel: "View Askbridge",
    snapshotCaption: "The Askbridge homepage, with its example conversation.",
    applicationCategory: "BusinessApplication",
    seo: {
      title: "Askbridge: AI Website Assistant and Live Chat",
      description:
        "Askbridge is the AI website assistant and live chat Vitalos builds and operates: answers from a business's own content, with sources, and a person on hand.",
    },
    sector: "Customer service",
    sections: [
      {
        heading: "What it does",
        layout: "cards",
        points: [
          {
            key: "knowledge",
            title: "Your own content",
            text: "Answers from your pages, documents and FAQs only.",
          },
          {
            key: "sources",
            title: "Sources visitors can check",
            text: "Each answer shows numbered sources with the quoted text.",
          },
          {
            key: "handover",
            title: "A named person",
            text: "Visitors can ask for a person at any time.",
          },
          {
            key: "inbox",
            title: "Team inbox",
            text: "Hand-offs arrive with a summary; one person takes each.",
          },
          {
            key: "offline",
            title: "Out-of-hours messages",
            text: "A message form when nobody is available.",
          },
          {
            key: "install",
            title: "One script tag",
            text: "Guides for WordPress, Wix, Squarespace, Shopify and Tag Manager.",
          },
        ],
      },
      {
        heading: "How it works",
        layout: "steps",
        points: [
          {
            title: "Add your content",
            text: "Your website, documents and FAQs.",
          },
          {
            title: "Test the answers",
            text: "Save Answer checks; re-run them when content changes.",
          },
          {
            title: "Install the widget",
            text: "Paste one tag; choose colours, greeting and who answers.",
          },
          { title: "Hand over to people", text: "Your team picks up with a summary, by name." },
        ],
      },
      {
        heading: "Built for",
        layout: "tiles",
        points: [
          {
            key: "lettings",
            title: "Lettings agents",
            text: "Fees, deposits, pets and repairs, often in the evening.",
          },
          {
            key: "services",
            title: "Service businesses",
            text: "The same everyday questions, answered from your pages.",
          },
          {
            key: "product-questions",
            title: "Product businesses",
            text: "Questions about what you sell, with sources.",
          },
          {
            key: "support-teams",
            title: "Customer-facing teams",
            text: "One inbox for hand-offs and messages.",
          },
        ],
      },
    ],
  },
  // Every claim maps to a line in docs/content/DISCOVERY-relay.md (the live site,
  // relay.vitalos.co.uk, 10 Nov 2026): its capability strip and four product cards, its "plan,
  // publish, reply and learn" flow (four steps here) and the people it names. Not the older chat
  // assistant also called Relay in this repo (now "Site assistant (legacy)", ADR-044 addendum).
  // No prices, trial, allowances or networks' approval states.
  {
    slug: "relay",
    name: "Relay",
    navLabel: "Relay — social media publishing",
    navDescription: "Built and operated by Vitalos",
    summary:
      "Social media publishing, a shared inbox and an AI assistant for teams, built and operated by Vitalos.",
    description: "Vitalos builds and operates Relay, a social media publishing platform for teams.",
    url: "https://relay.vitalos.co.uk",
    urlLabel: "Open relay.vitalos.co.uk",
    viewLabel: "View Relay",
    snapshotCaption: "The Relay Overview dashboard in an example workspace, with sample data.",
    applicationCategory: "BusinessApplication",
    seo: {
      title: "Relay: Social Media Publishing for Teams",
      description:
        "Relay is the social media platform Vitalos builds and operates: plan and schedule posts, reply from one inbox and draft with an AI assistant.",
    },
    sector: "Social media",
    sections: [
      {
        heading: "What it does",
        layout: "cards",
        points: [
          {
            key: "calendar",
            title: "Shared calendar",
            text: "One calendar for every brand and channel.",
          },
          {
            key: "per-network",
            title: "Write once",
            text: "Tailored per network, checked for length, media and fields.",
          },
          {
            key: "collaboration",
            title: "Team collaboration",
            text: "Comments, tasks and approvals in context.",
          },
          {
            key: "social-inbox",
            title: "Social inbox",
            text: "Comments, messages and reviews from supported networks, in one queue.",
          },
          {
            key: "analytics",
            title: "Analytics with coverage",
            text: "See what works; missing data shows as missing.",
          },
          {
            key: "assistant",
            title: "AI assistant",
            text: "Drafts within your permissions; publishing always needs approval.",
          },
        ],
      },
      {
        heading: "How it works",
        layout: "steps",
        points: [
          { title: "Plan", text: "Write, tailor and schedule on a shared calendar." },
          { title: "Publish", text: "Approvals before anything goes out." },
          { title: "Reply", text: "Assign, add notes, reply where each network allows." },
          { title: "Learn", text: "See what works by channel and post." },
        ],
      },
      {
        heading: "Built for",
        layout: "tiles",
        points: [
          { key: "teams", title: "Teams", text: "Plan, publish and reply together." },
          {
            key: "brands",
            title: "Several brands",
            text: "Every brand and channel on one calendar.",
          },
          {
            key: "customer-care",
            title: "Customer care",
            text: "Assignment, internal notes and reply drafts.",
          },
        ],
      },
    ],
  },
];

export const productBySlug = (slug: string): ProductView | undefined =>
  products.find((product) => product.slug === slug);

export const productPath = (product: Pick<ProductView, "slug">): string =>
  routes.product(product.slug);
