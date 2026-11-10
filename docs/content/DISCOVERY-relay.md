# Discovery: Relay product page

Evidence for every claim on `/products/relay`. The page was added on the owner's decision (10 Nov 2026: add Relay, Vitalos's social media publishing product, live at https://relay.vitalos.co.uk, to the Products pages).

Source: what relay.vitalos.co.uk showed on 10 Nov 2026 (its homepage, `/`, the product's marketing page), quoted verbatim. Some lines sit in the homepage's "Explore" panels, which are in the served HTML; the Relay repository (`apps/web/components/marketing/content.ts` and `product-demos.tsx`) holds the same copy.

**Naming.** This Relay is the social media product. The older chat assistant for vitalos.co.uk in this repository (`packages/relay-core`, `/api/relay/*`, `docs/relay/`) is labelled "Site assistant (legacy)" in the Super Admin from 10 Nov 2026 (ADR-044 addendum); nothing on this page describes it.

A claim goes on the page only if it has a line here. What was cut is listed at the end.

## The page in the product template

| Band         | Item                                                                               | Evidence rows |
| ------------ | ---------------------------------------------------------------------------------- | ------------- |
| Hero         | "Vitalos builds and operates Relay, a social media publishing platform for teams." | 1, 2          |
| Snapshot     | The Overview dashboard in an example workspace, with sample data                   | 3             |
| What it does | Shared calendar: one calendar for every brand and channel                          | 4             |
| What it does | Write once: tailored per network, checked for length, media and fields             | 5             |
| What it does | Team collaboration: comments, tasks and approvals in context                       | 6             |
| What it does | Social inbox: comments, messages and reviews from supported networks, in one queue | 7             |
| What it does | Analytics with coverage: see what works; missing data shows as missing             | 8             |
| What it does | AI assistant: drafts within your permissions; publishing always needs approval     | 9             |
| How it works | Plan → Publish → Reply → Learn                                                     | 10, 5, 11, 12 |
| Built for    | Teams: plan, publish and reply together                                            | 13            |
| Built for    | Several brands: every brand and channel on one calendar                            | 4             |
| Built for    | Customer care: assignment, internal notes and reply drafts                         | 7, 12         |

"How it works" is the site's own four verbs ("plan, publish, reply and learn"), one step each.

## Claims used on the page

| #   | Page claim                                                | Evidence (relay.vitalos.co.uk, 10 Nov 2026)                                                                                                                                                  |
| --- | --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Social media publishing for teams                         | Hero "Your social world. Working together." "Plan content, manage conversations, and get work done with AI."; "Everything your team needs to plan, publish, reply and learn — in one place." |
| 2   | Built and operated by Vitalos                             | The owner's decision (10 Nov 2026); the site runs on a vitalos.co.uk subdomain. The site itself names only "Relay" (footer "© 2026 Relay").                                                  |
| 3   | The snapshot shows sample data                            | Hero image caption "Illustrative preview with example content."; the workspace is "Relay Showcase · Owner · Demo" and the figure says "simulated"                                            |
| 4   | One calendar for every brand and channel                  | Capability strip "Plan — One calendar for every brand and channel."; "Planner and calendar across brands and channels"                                                                       |
| 5   | Write once, tailored per network, with checks             | "Write once, tailor it per network and schedule it on a shared calendar — with approvals before anything goes out."; "Per-network checks for length, media and required fields"              |
| 6   | Comments, tasks and approvals in context                  | Capability strip "Collaborate — Comments, tasks and approvals in context."                                                                                                                   |
| 7   | Comments, messages and reviews from supported networks    | "Comments, messages, mentions and reviews from supported networks in one queue, with assignment and notes."; "Assignment, internal notes and reply drafts"                                   |
| 8   | See what works; missing data shows as missing             | "See what works by channel and post, with data coverage shown"; "Missing data shows as missing, never as zero."                                                                              |
| 9   | AI drafts within permissions; publishing needs approval   | "Ask Relay to plan a week, turn a brief into drafts or answer unread messages. It works within your permissions and saves drafts for review."; "Publishing and replies always need approval" |
| 10  | Plan: write, tailor and schedule on a shared calendar     | Row 5                                                                                                                                                                                        |
| 11  | Publish: approvals before anything goes out               | "with approvals before anything goes out"                                                                                                                                                    |
| 12  | Reply: assign, add notes, reply where each network allows | Inbox example "Assign, add internal notes and reply where each network allows it."                                                                                                           |
| 13  | Teams plan, publish and reply together                    | Standard plan line "Plan, publish and reply together."; "Bring your team together"                                                                                                           |

## Unverified, partly verified, or cut

- **"Operated" by Vitalos.** The site does not name Vitalos; that Vitalos builds and operates it is the owner's statement.
- **Prices, plans, the free trial, seats and AI allowances.** On the site, but the product template allows no figures.
- **Named networks.** The site lists ten publishing networks, but most say "Needs provider access" or "Limited" (Meta, LinkedIn, Google, X and TikTok approvals). The page says "supported networks" and "where each network allows" and names none.
- **Listening, automation, business integrations and MCP.** On the site as Professional features, several waiting on provider approval. Left out of a short page rather than qualified.
- **Customers and results.** The example bakery brands, people and figures in the demos and the snapshot are the site's own fictional examples, labelled "Example". Nothing on the page names or implies a customer.
- **Legal pages.** On 10 Nov 2026 the site's Privacy and Terms links were marked "(not published yet)". Linking to it from vitalos.co.uk was the owner's decision.
