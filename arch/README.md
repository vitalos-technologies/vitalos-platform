# Vitalos platform architecture

This folder is the visual architecture of `vitalos-technologies/vitalos-platform`, taken from the code at commit `2096148` on 3 Nov 2026.

The repository runs two products for Vitalos Technologies. The first is the public website at vitalos.co.uk: a Next.js 16 app on Vercel with an enquiry pipeline, the Relay assistant and the AI & Data section. The second is the internal Super Admin and client portal: a Django 6 app on Google Cloud Run behind a Cloudflare Worker, with its own PostgreSQL database. The website and the Super Admin share no code and no database. They talk only through signed HTTP APIs. Shared TypeScript packages (`@vitalos/*`) hold the design tokens, UI, content model, security, Relay domain logic and the email layout used by every Vitalos email.

## Views

| View                                                  | What it shows                                                                                          |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| [index.html](index.html)                              | All views on one page, with a hand-drawn container diagram, light and dark themes and zoomable figures |
| [01 Context and containers](01-context-containers.md) | Who uses the platform, the outside systems, and the deployable parts and how they talk                 |
| [02 Data model](02-data-model.md)                     | The website database (enquiries, Relay) and the Super Admin database by domain                         |
| [03 Deployment and CI/CD](03-deployment-cicd.md)      | Where each part runs, environments, the CI pipeline and every workflow                                 |
| [04 Flows and security](04-flows-security.md)         | Five key journeys as sequence diagrams, trust boundaries and the security controls                     |

## Key facts

| Fact               | Value                                                                                                                                                              |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Stack              | TypeScript monorepo (pnpm, Turborepo), Next.js 16, React 19, Node 24; Python and Django 6 for the Super Admin                                                      |
| Hosting            | Website on Vercel (`dub1`); Super Admin on Google Cloud Run (`europe-west2`) behind a Cloudflare Worker; Cloudflare for DNS, Workers and R2                        |
| Data stores        | Website: Supabase PostgreSQL 17 (`public` and `relay` schemas, pgvector). Super Admin: a separate PostgreSQL (Supabase or Neon free plan)                          |
| External providers | Vercel, Supabase, Cloudflare, Google Cloud, GitHub, Resend or Postmark, DeepSeek, Anthropic, Stripe, Microsoft Graph or SMTP                                       |
| Public URLs        | `vitalos.co.uk`, `admin.vitalos.co.uk`, `portal.vitalos.co.uk` (portal domain binding pending)                                                                     |
| Repository         | `vitalos-technologies/vitalos-platform` (public, proprietary licence)                                                                                              |
| Snapshot           | 3 Nov 2026, commit `2096148`                                                                                                                                       |
| Decisions          | 49 ADRs in [`docs/adr/`](../docs/adr/README.md); written architecture in [`ARCHITECTURE.md`](../ARCHITECTURE.md) and [`docs/architecture/`](../docs/architecture/) |

## Documentation drift found

These views follow the code. Where older documents disagree, the code wins:

- `ARCHITECTURE.md` describes the state of 10 Oct 2026. It says no remote Supabase project is used and lists only enquiry data. The `Relay knowledge` workflow now writes to a production Supabase project, and Relay, Insights, Careers, AI & Data, billing and the client portal have landed since.
- `docs/architecture/container-architecture.md` shows Vercel as the "intended host; previews blocked", while the README says the site is live on Vercel.
- ADR-042 and parts of `superadmin/docs/DEPLOY.md` still describe Azure (for example a Container Apps job) after the move to Cloud Run on 1 Nov 2026, and the deploy guide's status line still reads "Not live yet".
- The ADR index says it was last reviewed on 10 Oct 2026 but lists ADRs up to 056. ADR-029, ADR-044 and ADR-045 are still marked Proposed although their code is in the repository.

## Viewing the page

Open `index.html` in a browser. It is a single file with no build step. Every diagram is pre-rendered into the page in light and dark versions, so it works offline and in app file viewers; a diagram edited without re-baking renders live from jsDelivr (`mermaid@11.4.1`) instead. Use **Theme** to switch between light and dark, **Expand** to open a diagram full screen with zoom, and **Source** to see the Mermaid text. After editing a Mermaid diagram, re-bake the page with the Vitalos archkit bake script so it keeps working offline.

## Updating

- Each diagram's Mermaid source is the same in the Markdown file and in `index.html` (`<script type="text/plain" class="mmd">`). Change both together.
- The container diagram in `index.html` is hand-drawn SVG; its Mermaid equivalent is in [01 Context and containers](01-context-containers.md).
- Counts and the snapshot commit are stated for 3 Nov 2026. Refresh them when the architecture changes, alongside the ADR and `docs/architecture/` updates that `AGENTS.md` asks for.
- This repository is public. Keep these views at design level: no secret values, hostnames of private machines, personal data or exploitable detail.
