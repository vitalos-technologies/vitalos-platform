# Vitalos AI & Data — launch milestone plan

Milestone: blueprint VAD-001 to VAD-010, in proportion to the first sale (blueprint §21, §23.1), plus the processes VAD-011 onward need. Owner of plan and integration: the lead agent session. Decisions: [DECISIONS.md](DECISIONS.md). Tasks: [TASKS.md](TASKS.md).

## Outcome

1. A public AI & Data presence with a working enquiry flow.
2. Enquiries become opportunities in an authenticated internal pipeline.
3. Usable commercial and delivery templates.
4. One demonstrator (supplier statement reconciliation) with reproducible evaluation evidence.
5. A minimal reusable AI engineering core.
6. Tested deployment, monitoring, configuration and recovery documentation.

Out of scope: the twenty-product catalogue, a general agent platform, Kubernetes, GPUs, model training, new paid services, contacting prospects, sending proposals or making commercial commitments.

## Architecture (ADR-052)

```text
Visitor ──> vitalos.co.uk/ai-data  (Next.js, Vercel; apps/web route group "(ai-data)")
              │ AI & Data form → server action → existing enquiry service (ADR-019)
              ▼
         Supabase: enquiries + notification_outbox  (record first, then notify)
              │ outbox dispatch → email (Resend) with X-Vitalos-Pipeline: ai-data
              ▼
         support@ → Cloudflare Email Worker → Super Admin ingest (admin.vitalos.co.uk)
              │ Enquiry (form relay) → Opportunity (stage New), idempotent per enquiry
              ▼
         Super Admin /ai-data/: Pipeline · Offers (proposed prices) · Budget · Demonstrator
                                                          │
                                       apps/recon_demo ── apps/aicore (gateway, limits,
                                                          metering, evaluation, redaction)
                                                          │ provider: OpenAI-compatible
                                                          ▼ (off until AI_DATA_LLM_API_KEY)
```

### Shared contracts

| Contract                               | Producer → consumer                   | Definition                                                                                                                                                    |
| -------------------------------------- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Enquiry body                           | AI & Data form → enquiry service      | Existing `EnquiryInputV2`: `intent: "ai"`, `sourcePath: "/ai-data/contact"`, optional `offerSlug` (offer keys below), composed `goal` (labelled sections)     |
| Notification headers                   | Website notifier → Super Admin ingest | `X-Vitalos-Pipeline: ai-data` when the source path starts with `/ai-data`; `X-Vitalos-Offer: <offer key>` when one was chosen; existing `X-Vitalos-Reference` |
| Offer keys                             | Site, form, Super Admin               | `ai-opportunity-assessment`, `ai-proof-of-value`, `production-ai-engineering`, `managed-ai-operations`                                                        |
| Sector keys                            | Form, Super Admin                     | `accounting-bookkeeping`, `property`, `automotive`, `professional-services`, `trades-field-services`, `retail-ecommerce`, `other`                             |
| Budget band keys (AI & Data form only) | Form → composed text                  | `under-1k` (Under £1,000), `1k-5k` (£1,000–£5,000), `5k-15k` (£5,000–£15,000), `over-15k` (Over £15,000), `not-sure` (Not sure yet)                           |
| Demonstrator report                    | `recon_eval` command → website page   | `apps/web/src/features/ai-data/demonstrator-report.json` (schema in `engineering/demonstrator.md`); `status: "pending"` until a real evaluation run writes it |

### Composed enquiry text (`goal`)

```text
Vitalos AI & Data enquiry
Sector: <label>
Business problem or workflow:
<text>
Current tools and process:
<text or "Not given">
Desired outcome:
<text>
Indicative budget: <label or "Not given"> (enquirer's estimate)
```

## Workstreams and ownership

| Workstream                                    | Owner              | Files                                                                                                                                                                                                                       |
| --------------------------------------------- | ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| W1 Public site and AI & Data form             | Agent A (worktree) | `apps/web/app/(ai-data)/**`, `apps/web/src/features/ai-data/**`, `apps/web/src/components/ai-data/**`, notifier headers, `packages/validation` (AI & Data schema), design tokens (AI & Data tokens), sitemap entries, tests |
| W2 Pipeline, offers, budget                   | Agent B (worktree) | `superadmin/apps/aidata/**`, its templates, nav entry in `templates/base.html`, ingest hook, "Create opportunity" on enquiry detail, tests                                                                                  |
| W3 AI core, demonstrator, evaluation          | Agent C (worktree) | `superadmin/apps/aicore/**`, `superadmin/apps/recon_demo/**`, their templates, eval CI step, tests                                                                                                                          |
| W4 Commercial assets                          | Agent D (worktree) | `docs/ai-data/commercial/**`                                                                                                                                                                                                |
| Integration, docs, ADR, CLAUDE/AGENTS, deploy | Lead               | `docs/**` (except commercial), `AGENTS.md`, `superadmin/config/**` merges, CI, PR, deploy                                                                                                                                   |

## Completion checklist (persistent)

Update the boxes as work lands. A box is ticked only with evidence in TASKS.md.

- [x] Blueprint read; workspace, repos, hosting, enquiry pipeline, Super Admin and credentials inspected
- [x] Plan, decision log, task register, demonstrator acceptance criteria committed before evaluation
- [x] W1 public site pages built, responsive, accessible; AI & Data form submits through the existing pipeline
- [x] W2 pipeline (stages, owner, next action, notes, dates, scorecard), offers, budget in the Super Admin; intake from enquiries
- [x] W3 AI core (provider interface, validation, versioning, timeouts/retries, ids/audit, metering, limits, kill switch) and demonstrator; offline evaluation report
- [x] W4 commercial templates and checklists
- [x] ADR-052, architecture docs, operations runbook, AGENTS.md/CLAUDE.md autonomy section
- [x] Integrated branch: format, lint, typecheck, unit tests, boundaries, build, Super Admin ruff/pytest/migrations check, evaluation gate
- [x] Screenshots of site and Super Admin pages (desktop and mobile)
- [x] PR opened, CI green, squash-merged (vitalos-technologies/vitalos-platform#102 → `ed64d58`)
- [x] Production verified: vitalos.co.uk/ai-data pages (200, sitemap, headers) and Super Admin deploy healthy; a live enquiry through the human check is an owner step (below)
- [x] Completion report with external prerequisites

## Checkpoint

_Session handoff, 8 Nov 2026: read [HANDOFF.md](HANDOFF.md) first. Production Super Admin cannot reach its database since 2 Nov (owner step: refresh the Supabase connection strings); #123 and #124 are merged and wait for the next deploy._

_Last updated: 29 Oct 2026. The connected experience (marketing redesign, guided brief, admin workspace, client portal) is merged as `dd61f63` (vitalos-technologies/vitalos-platform#106) and live, including `portal.vitalos.co.uk`; evidence in `experience/PROGRESS.md`. The billing, `/pay` and Claude provider entries below are from #104._

_Workspace update, 28 Oct 2026:_ the admin is now an AI-assisted delivery workspace (ADR-055): paste an enquiry, review an evidence-linked brief, discovery pack, proposal draft with human approval, assistant, durable AI tasks, signed website brief-assist endpoint (off by default), shared tokens. Live provider still off; no live model-quality evidence. Next (owner): website client signs `assist`, key and switches, live evaluation, retention schedule. Tasks WS-001 to WS-007 in TASKS.md.

_Delivery and Operations, 2 Nov 2026 (W17, WS-006):_ AI & Data › Delivery and Operations now show client portal records instead of empty states: counts, needs attention and projects in delivery; managed services with their latest status and the portal's stale rule. They are read-only and staff-only, and show no internal notes. Tasks, test cases, progress summaries, incidents, exceptions and the monthly report are still not built. VAD-010 is Done (AC-14 run 40972825725, below).

- #104 merged as `162f58e` (squash-merged after every check passed on its head).
- **Website** (Vercel deployed from the merge; the Git integration is reconnected):
  - `vitalos.co.uk/pay` and `/pay/thank-you` answer 200 and are `noindex`.
  - The `/pay` form posts to `https://admin.vitalos.co.uk/pay/checkout/`. Only `/pay` has the wider CSP, `form-action 'self' https://admin.vitalos.co.uk https://checkout.stripe.com`; `/contact` keeps `'self'`.
  - The "See the demonstrator" button is gone from the AI & Data thank-you page.
- **Super Admin** (`Super Admin deploy` for `162f58e` succeeded):
  - `/healthz/` returns 200.
  - `/billing/` redirects to sign-in.
  - `GET /pay/checkout/` and `GET /api/webhooks/stripe/` return 405.
  - A POST with an unknown invoice returns 303 to `vitalos.co.uk/pay?...&error=not-found`.
- **AC-14 (live provider) passes, in CI too.**
  - **Owner's key:** after the owner replaced `AI_DATA_LLM_API_KEY` in the `production` environment, live evaluation run 40972825725 (29 Oct 2026, 23:24 UTC) passed AC-14. Results: 7/7 model-path calls answered, model-path field accuracy 100%, unsafe accepts 0, about £0.0028 per model-path case (threshold £0.01). The data is synthetic (dataset v1).
  - **Earlier runs:** a lead run through the gateway gave the same result. Run 40968966484 failed with HTTP 400 on the previously stored key. Run 40735552845 had no key at all.
  - **Spend:** about £0.04 across both passing runs.
  - **Provider change:** the provider now keeps the API's error type and message, so a refused call names its cause.
  - **Owner step:** turn on "Live model path" (and "Website brief assist" if wanted) in Super Admin › AI settings, and record the spend in AI & Data › Budget.
- **Production settings (deploy run 40974031499, 29 Oct 2026):** these are now set:
  - `AI_DATA_LLM_API_KEY`;
  - `BILLING_STRIPE_SECRET_KEY` (Stripe **test mode**, Vitalos account);
  - `BILLING_STRIPE_WEBHOOK_SECRET`, for the test-mode endpoint `https://admin.vitalos.co.uk/api/webhooks/stripe/` (created 29 Oct with `checkout.session.completed`, `checkout.session.async_payment_succeeded` and `charge.refunded`). An unsigned POST gets 400 "Invalid signature";
  - `PORTAL_FILES_BUCKET=vitalos-portal-files`.

  Still empty: `TURNSTILE_SECRET_KEY`. Before real payments, switch to a live restricted Stripe key and a live-mode webhook.

- **Billing owner steps** (ADR-053; `superadmin/apps/billing/README.md`):
  - Create a restricted key in Vitalos's own Stripe account and store it as `BILLING_STRIPE_SECRET_KEY`.
  - Add a webhook to `https://admin.vitalos.co.uk/api/webhooks/stripe/` for `checkout.session.completed`, `checkout.session.async_payment_succeeded` and `charge.refunded`, and store its signing secret as `BILLING_STRIPE_WEBHOOK_SECRET`.
  - Set `TURNSTILE_SECRET_KEY` as a `production` secret, with the same value as on Vercel, so that `/pay/checkout/` verifies the human check. Without it, only the honeypot and rate limits apply.
  - Review Billing › Settings.
- **Still not verified in production:** a real enquiry end to end, a live Stripe payment, and the live model path.

## Client portal (ADR-056)

Workstream W8, 28 Oct 2026. A customer portal inside the Super Admin (`apps.portal`) that follows the journey Submitted challenge, Discovery, Assessment, Proposal, Active project, Handover, Managed operations, keeping the original opportunity and its discussion attached.

- **Where:** `https://portal.vitalos.co.uk` (owner decision; only portal URLs are served on that host). `/portal/` path mounting is local preview only. Staff tools are at `/client-portal/` and a "Client portal" panel sits in the opportunity workspace.
- **Access:** staff invite members (single-use, expiring, hashed token through `apps.mailer`); roles viewer, contributor, approver, authorised signatory; axes lockout; optional TOTP. An enquiry never creates access.
- **Visibility:** explicit publication per record, scoped selectors, internal fields never rendered, searched, emailed, exported or sent to the AI. Deliverable approvals are version-specific; change requests are request-only with a review trail.
- **AI:** six read-only activities through `apps.aicore` with a deterministic, labelled fallback (today's production state: no model).
- **Not built (later phases):** live monitoring integrations (status is manual, labelled, goes stale), contractual e-signature, email OTP and customer SSO, retention jobs other than for delivery records, customer-side organisation administration.
- **Delivery status (W13, 30 Oct 2026, merged as vitalos-technologies/vitalos-platform#115):** Client portal › Notification deliveries shows email and push deliveries with a summary, filters, detail, Retry now, Cancel and a capped bulk retry. Old delivery records and turned-off devices are deleted daily under a documented policy (`operations/portal-delivery-retention.md`), as a dry run until `RETENTION_ENFORCE=true`. Task PORTAL-15.
- **Upload and member management (W14 and W15, 30 Oct 2026, merged as vitalos-technologies/vitalos-platform#116 and #117):** customers upload files from Files; Account has a settings menu; staff cancel invitations and remove members (the account is kept, deleted, or erased to "Former member" when it wrote project records; ADR-056 "Member management"); Settings › Users & roles lists Client portal users. Tasks PORTAL-16 and PORTAL-17.
- **Owner steps before customers use it:** a private bucket and `PORTAL_FILES_BUCKET` for file uploads; optional `PORTAL_HOST` / `PORTAL_ENABLED` variables (see `superadmin/apps/portal/README.md`). The DNS record and the Azure custom-domain binding were made by the deploy on 28–29 Oct 2026.
- **Checkpoint:** live since 29 Oct 2026 (merged as `dd61f63`; see the task register, PORTAL-01 to PORTAL-17). Push notifications were confirmed on the owner's phone on 30 Oct 2026. `superadmin/deploy/azure/deploy.sh` created the DNS record and the managed certificate. Sign-in answers on `https://portal.vitalos.co.uk` and admin routes return 404 there. No customer has been invited yet.

- **W6 note (28 Oct 2026):** `/ai-data/contact` is a guided brief (describe, questions, editable cards with provenance, share) over the unchanged enquiry pipeline; AI assist is opt-in, server-side and falls back to a labelled checklist. Production AI stays off until the Super Admin "Website brief assist" switch and a provider key exist. See `engineering/guided-brief.md` and the W6 section of ADR-054.
- **W5 note (28 Oct 2026):** the public pages were redesigned as AI work surfaces (ADR-054): scripted, labelled hero walkthrough, workflow explorer with the four shared topic slugs, reconciliation preview and a usable demonstrator with three synthetic samples. Base UI 1.9.0 is wrapped in `@vitalos/ui/interactive` and loaded on demand. Home JavaScript +9.2 KB gzip (budget raised to 222,000 B with reasons in `tests/performance/budgets.json`). Not changed: `/ai-data/contact`, the brief, the Super Admin.
