# Progress, decisions, evidence and blockers

Newest entries first. Each entry gives the time (UTC), what changed, and the evidence or the next step.

## Current state

- **M0 to M8 done, live in production.** #106 was merged on the owner's instruction (`dd61f63`, 28 Oct 23:40) and deployed: the website on Vercel, the Super Admin on Azure with its migrations, and `portal.vitalos.co.uk` bound with a managed certificate. The AI switches are off and no customer has been invited.
- **Next:** the model key and the live evaluation (HANDOFF.md, "Known issues and configuration blockers"), then the first invited customer.

## Facts established (28 Oct 2026, before implementation)

Verified working; no rebuild needed:

- **Enquiry durability (ADR-019):**
  - `submit_enquiry` writes the enquiry and its outbox row in one transaction.
  - The idempotency key is unique; a replay returns the original reference.
  - The AI & Data form already sends `idempotencyKey`, and has a test.
- **Notification delivery:**
  - The outbox has a lease (`FOR UPDATE SKIP LOCKED`), counts attempts, and dead-letters to `failed`.
  - Retryable and permanent errors are told apart.
  - Delivery happens best-effort straight after submit (`after()`), with a daily Vercel cron (`/api/internal/outbox/dispatch`, 06:00) as the fallback.
- **AI:**
  - `apps.aicore` gateway: providers are Anthropic (official SDK), OpenAI-compatible, Simulated, Replay and Recording.
  - It has a kill switch, per-run, daily and monthly caps, schema validation and metering (`ModelExecution`).
  - The demonstrator's offline evaluation AC-1 to AC-13 passes.
- **Super Admin roles:** SuperAdmin, ServiceLead and Viewer. A user without a role has no access.
- **Payments:** `/pay` and the Super Admin billing are live (#104).

Existing functionality that needs improvement (in scope):

- The `/ai-data` hero is oversized and text-only.
- The demonstrator is explanatory rather than usable.
- The contact page is a plain form.
- The admin AI & Data overview is navigation cards rather than a work queue.
- The opportunity page has no brief, discovery or proposal workspace.

Missing functionality (in scope):

- A guided brief.
- AI-prepared briefs with sources.
- Discovery packs and proposal drafts.
- Durable AI task states in the admin.
- The whole client portal: no customer auth, organisations, projects, deliverables or approvals exist.

Blocked by configuration (not in code):

- **Live AI.** The live provider is off and there is no `AI_DATA_LLM_API_KEY` (the organisation's `ANTHROPIC_API_KEY` is not shared with this repo), so live AI results and the demonstrator's AC-14 cannot be produced. Every AI surface ships with an honest unavailable state and a non-AI path.
- **Stripe.** No Vitalos Stripe key or webhook secret is configured.
- **Turnstile on the Super Admin.** `TURNSTILE_SECRET_KEY` is not set for the Super Admin, so `/pay/checkout/` relies on the honeypot and rate limits only.
- **Outbox fallback cadence.** On the Vercel Hobby plan, cron fallback dispatch is daily; a notification retry may take up to a day if `after()` fails. This is an existing limitation, recorded in ADR-019.

Outside this implementation's scope:

- Live monitoring integrations.
- Contractual e-signature.
- Product-incubation scoring.
- Autonomous outreach.

## Decisions

| Date        | Decision                                                                                                                                                                                                       | Why                                                                                                                                      |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 28 Oct 2026 | Base UI 1.9.0 (MIT) under `@vitalos/ui`, as owned shadcn-style components; no Radix; no lucide (the in-house monoline icon set is extended); no React Flow or Recharts unless real interactive data needs them | One coherent foundation; the existing design system and ADR-023/024 stay valid; small dependencies                                       |
| 28 Oct 2026 | The Super Admin and the portal stay Django, HTMX and template components, with native `<dialog>`, the Popover API and live regions                                                                             | They are not React; no framework rewrite (owner brief)                                                                                   |
| 28 Oct 2026 | The client portal lives inside the Super Admin deployment, host-routed to `portal.vitalos.co.uk` (owner approved the host), with host-only cookies                                                             | It shares records with the admin, so nothing is entered twice; auth, mailer, audit and the AI gateway are reused; no new service or cost |
| 28 Oct 2026 | Website AI assistance goes through the Super Admin `aicore` gateway via an HMAC-signed endpoint; the website falls back to rules                                                                               | AGENTS.md: model calls go only through `apps.aicore`; credentials stay on the server                                                     |
| 28 Oct 2026 | At most three implementation agents at a time; W6 paused until W5 finishes                                                                                                                                     | Owner instruction                                                                                                                        |

## Log

- **2 Nov 11:40: Account pages as section menus, admin and portal (W16; worktree branch, for the lead to integrate).**
  - **Owner's ask:** the settings on a left sidebar with the content on the right, for the Super Admin account page and the portal account page too, like Settings after #117.
  - **Super Admin › Account & security:** Profile (`/account/`), Password (`/account/password/`) and Two-step sign-in (`/account/two-step/`) are separate pages in the Settings layout, now one shared partial. Every form keeps its `action`, validation, messages and audit events, and `/account/` still accepts all of them. Two-step set-up opens inside the shell when chosen from Account; at a required sign-in it keeps the sign-in card. Superadmin decision 136.
  - **Client portal › Your account:** Profile (`/account/`), Sign-in & security (`/account/security/`, with set-up at `/account/security/two-step/`), Notifications on this device (`/account/device/`), Notification preferences and Install the app (`/account/install/`) are separate pages. The push and install hooks live on their own pages, staff preview still hides device and install, and the anchor-tracking script is gone. No service worker or `pwa.py` change.
  - **Phones:** the menu row scrolls the current item, and any item that takes keyboard focus, fully into view, with its focus ring inside the row (admin and portal; Settings benefits too).
  - **Evidence:**
    - The full Super Admin suite passes on PostgreSQL 16 (1863 tests), with 10 new tests in `tests/test_account_sections.py` and the portal shell tests in `tests/test_portal_files_upload_ui.py` rewritten for one page per section (14 tests). Existing tests that opened the device or install card, or two-step set-up, now open their new URLs; their intent is unchanged.
    - Playwright on synthetic seed data: axe WCAG 2.2 AA finds 0 violations over 50 runs (every section of both pages, light and dark, 1440 and 390, plus staff preview and Settings). There is no horizontal overflow at 320, 390 or 1440, and the keyboard focus ring stays whole in the phone menu rows.
    - Screenshots are in the W16 scratchpad (`shots/w16/`).
  - **Next:** the lead integrates and merges; after deploy, check one admin and one portal account page on a phone.

- **30 Oct 11:05: Files upload, Account settings layout, readable email links (W14; merged as vitalos-technologies/vitalos-platform#116).**
  - **Push, confirmed on a real phone:** the owner's own test after the Phase 2 deploy passed on 30 Oct 2026 (Android Chrome or desktop; the owner said "test notification worked"). This closes the "Next" step of the Phase 2 entry below.
  - **Files, "Upload a file":** a primary button at the top right of Files (and in the empty state) opens a native `<dialog>` with the file, the challenge (only this organisation's shared challenges), an optional project (published, grouped by challenge, filtered by the chosen challenge) and an optional title.
    - Before upload it states the accepted types and the 10 MB limit, both built from `files.py`, and the privacy line.
    - Validation stays on the server. A refusal comes back inline in the open dialog, by HTMX or, without JavaScript, as a full page. Success redirects to the file with a toast.
    - Viewers, members with no shared challenge and staff preview see the button disabled with the reason under it.
    - A project from another challenge is now refused by the service, not only by the form.
  - **Account settings:** a section menu beside the content (a sticky chip row at 52rem or narrower). It holds Profile, Sign-in & security, Notifications on this device, Notification preferences and Install the app.
    - The Account sections are anchors on `/account/`, so existing URLs and the push and install hooks are unchanged.
    - Notification preferences keeps its own URL inside the same shell.
    - Two-step setup uses the shell too.
  - **Email links:** the shared layout now links https addresses in text blocks (the invitation's fallback line) and footer links in the link colour, underlined. Dark mode uses `blue100`: 10.47:1 on the card, where a client's default blue was 1.41:1. See ADR-030 (30 Oct note) and `docs/email/README.md`.
  - **Evidence:**
    - `tests/test_portal_files_upload_ui.py` (35 tests), the email layout package (63 tests) and its golden fixtures, the dependants (web, Relay) and the full Super Admin suite (1728 tests on PostgreSQL) all pass.
    - Playwright on synthetic seed data: 32 Files checks and 22 Account checks pass. axe WCAG 2.2 AA finds 0 violations on Files, the open dialog, the dialog with an error, Account and Notification preferences, in light and dark. There is no horizontal overflow at 320, 390 or 768.
    - Screenshots are in the W14 scratchpad (`shots/w14/`).
  - **Website, fixed in the same PR:** the `seo` check had been red on `main` since the #113 push: `/what-we-do` simulated mobile LCP was 4008 to 4069 ms against a 4000 ms budget. The first image of the practice stage and of the solution panel was eager, so phones downloaded it although both are hidden below `lg`, beside the hero photograph (the LCP element). Both are lazy now (`packages/ui`); in CI `/what-we-do` reads 3738 ms and the other templates 3174 to 3720 ms.

- **30 Oct 10:55: Super Admin navigation, Settings menu, and user and member management (W15).**
  - **Sidebar:** Client portal is a child of an AI & Data dropdown (Overview, Client portal). Every `/client-portal/` page highlights it. Role gating is unchanged: SuperAdmin and ServiceLead see it, Viewers see neither.
  - **Demonstrator:** its pages keep the AI & Data tab bar, with Demonstrator current, and show their own menu beneath it as pills.
  - **Settings:** a grouped, sticky section menu of real links (`aria-current`) beside the panel from `lg`, and a scrollable row on phones. The HTMX swaps and every permission condition are kept.
  - **Staff users:** icon actions for Edit, Send a set-password link, Reset two-step sign-in, Suspend or Reactivate, and Delete. Suspend revokes API tokens and ends sessions. Delete is refused for yourself, the primary owner, the last active SuperAdmin, and accounts that own live work or wrote protected project records; the refusal offers Suspend instead. Rules are in `apps/accounts/lifecycle.py`.
  - **Portal members:** state badges (Invited, Invitation expired, Active, Suspended) and organisation-scoped icon actions: role, resend, suspend or restore, cancel invitation, remove. Removal deletes the account when it left no trace, or erases it ("Former member") when it wrote project records (ADR-056, "Member management"). Settings › Users & roles › Client portal users lists customers across organisations, with the same actions.
  - **No migration.** Tests: `test_admin_navigation.py`, `test_user_lifecycle.py` and `test_portal_member_management.py`. Synthetic data only; no email was sent outside the test outbox.

- **30 Oct 10:15: client portal notification delivery status and delivery-record retention (W13; merged as vitalos-technologies/vitalos-platform#115).**
  - **Built:** Client portal › **Notification deliveries** (`/client-portal/deliveries/`, replacing the email-only page at the same address):
    - a summary per channel for 24 hours and 7 days (sent, pending or retrying, failed for good), active push devices and devices turned off in the last 7 days by reason;
    - email and push in one list, newest first, with filters (channel, status, organisation, kind, last N days) and 50 rows a page;
    - a detail page per delivery: the error in plain English, the device's state, a link to the record, and the audit history;
    - Retry now, Cancel and "Retry all failed in this filter" (capped at 100, behind the styled confirmation dialog), all audited.
  - **Rules:**
    - Retries go through `notifications.deliver` / `push.deliver` (`manual=True`) and keep every re-check. The member's current preference is now re-checked at send time too, for automatic retries as well.
    - Push endpoints, keys, payloads and email bodies never reach the page; a test asserts it.
    - No migration: a cancelled delivery is `failed` with the category `cancelled`.
  - **Retention** (policy `docs/ai-data/operations/portal-delivery-retention.md`, ADR-056): sent records go after 90 days, failed or cancelled ones after 180, turned-off devices after 90 once their records are gone. It never touches queued or retrying rows, active devices, notifications or audit. It runs daily in the content tick and is a dry run until `RETENTION_ENFORCE=true`; `manage.py portal_delivery_retention` prints the counts.
  - **Evidence:**
    - `tests/test_portal_deliveries.py` passes (38 tests: counts, filters, pagination, hidden fields, retry and every re-check, cancel, bulk cap, permissions, hosts, query count, retention). The full Super Admin gates pass.
    - Playwright on synthetic seed data (35 checks) covers the list, filters, a gone push device, a failed email, the confirmation dialog, the "Sent." toast and the empty states. axe WCAG 2.2 AA shows no violations (light, and dark for the list and a detail page), and there is no horizontal overflow at 390.
    - Screenshots are in the W13 scratchpad (`shots/w13-deliveries/`).
  - **Owner step:** after deploy, read the first dry run (it should be zero in every category until late January 2027) before setting `RETENTION_ENFORCE=true`, which also enforces the enquiry and recruitment policies.

- **30 Oct 07:50: client portal Phase 2, push notifications (W12; branch `worktree-agent-a16a875ec3d1a6a2a`, not merged).**
  - **Built:** standard Web Push (RFC 8030) with VAPID (RFC 8292) and `aes128gcm` encryption (RFC 8291), on `cryptography` 50.0.2 primitives only. It has:
    - devices per member (`PushSubscription`, at most ten active, a coarse label such as "Chrome on Android") and durable `PushDelivery` records with bounded retries; migration `portal` 0005 is additive;
    - push toggles per kind beside email on Notification preferences;
    - a "Notifications on this device" card on Account (unavailable, iOS not installed, off, on, blocked), a device list and "Send a test notification";
    - service worker handlers for `push`, `notificationclick` (same-origin portal paths only) and `pushsubscriptionchange`. It still caches no workspace data.
  - **Privacy and safety:**
    - A lock screen shows a generic line per kind and nothing else: no names, titles or message text.
    - Endpoints must be real push services (an SSRF allowlist), checked when stored and before every send, and redirects are never followed.
    - Signing out turns notifications off on that browser.
  - **Keys:** the deploy workflow generates the VAPID key once and `deploy.sh` keeps it (`portal-push-vapid-private-key`). With no key, push is off everywhere and the card says so. The owner sets nothing.
  - **Evidence:**
    - `tests/test_portal_push.py` passes (83 tests), including the RFC 8291 Appendix A vector byte for byte and real HTTP to a fake push service on 127.0.0.1. The full Super Admin gates pass too.
    - Playwright on synthetic seed data (49 checks): headless Chromium cannot register with Google's push service, so the browser's subscription was stubbed in the page and pointed at the local fake service. The card states, test sends, a staff question reaching the device, decryption, VAPID verification, the worker's notification (via CDP), the click guard, axe (light and dark) and overflow at 320, 390 and 768 were all checked.
    - Screenshots are in the W12 scratchpad (`shots/w12-push/`).
  - **Next:** after merge and deploy, the owner turns notifications on from Account on a real phone and presses "Send a test notification" (iPhone: install the app first).

- **29 Oct 23:55: client portal Phase 1, the installable app (W11; branch `worktree-agent-aec1d46aca8f6a2d8`, not merged).**
  - **Built:** the portal installs from the browser (no app store). It has:
    - a manifest, service worker and offline page at the portal root, absent on the admin host and in staff preview;
    - icons generated from the Vitalos symbol;
    - a bottom tab bar at 52rem or narrower and in the installed app (Home, Challenges, Questions, Notifications with the unread badge, More);
    - an "Install the app" card on the Account page.
  - **Privacy:** the service worker caches only public static files and the offline page, never workspace pages, partials, downloads or exports, so signing out needs no purge. The rules are in ADR-056, "Phase 1: installable app".
  - **Evidence:**
    - `tests/test_portal_pwa.py` passes, as do the full Super Admin gates.
    - Playwright on synthetic seed data (26 checks): the worker registers and controls the page, and offline navigation, even to visited pages, shows the offline page. The cache holds only `/static/` files and `/portal/offline/`. There is no horizontal overflow at 320, 390 or 768, and desktop at 1440 is unchanged.
    - Screenshots are in the W11 scratchpad (`shots/w11-pwa/`).
  - **Deferred:**
    - Web Push needs VAPID keys and a dependency decision.
    - Native apps need paid store accounts, which the owner must buy.

- **29 Oct 00:05: merged and verified in production.**
  - **Merge:** the owner said "Merge"; #106 was squash-merged as `dd61f63` with all 19 checks green on head `6f544cb`.
  - **Website (Vercel):** `/ai-data` serves the redesign ("AI that takes work off your team's hands"). `/ai-data`, `/ai-data/demonstrator`, `/ai-data/contact` (guided brief), `/ai-data/solutions`, `/ai-data/approach` and `/pay` return 200.
  - **Super Admin (Azure, run 40789960766):**
    - Super Admin CI on `main` was green, and the pre-migration backup succeeded.
    - The release job applied the migrations before the new image took traffic, and the post-deploy check reports healthy on `dd61f63`.
    - The admin answers `/healthz/` 200. `/ai-data/`, `/client-portal/` and `/billing/` redirect to login. An unsigned `POST /api/ai-data/brief-assist/` gets 401.
  - **Portal:**
    - `deploy.sh` wrote the Cloudflare record for `portal.vitalos.co.uk` (DNS only) and bound the free managed certificate ("Portal host live").
    - `/healthz/` and `/sign-in/` return 200, and `/` redirects to sign-in.
    - `/login/`, `/ai-data/`, `/client-portal/`, `/admin/` and the brief-assist API all return 404 on the portal host.
    - The CSRF cookie is host-only (no `Domain`). CSP, HSTS and `X-Frame-Options: DENY` are present.
    - There is no horizontal overflow at 1440 or 390 px.
  - **Found in production and fixed:** the hidden "Skip to content" link cast its shadow into the top-left corner of every portal page. The shadow now shows only while the link is focused. Checked against the live page with the patched stylesheet.
  - **Screenshots:** lead scratchpad `shots/prod2/` (the website pages and the portal sign-in at 1440 and 390, plus the focused skip link).

- **28 Oct 20:35: #106 ready for review; the full CI is green on `2fa8db6`** (all jobs, including e2e and axe, e2e-draft, SEO and Lighthouse, storybook-a11y, visual, pgTAP and the Super Admin container smoke test). M8 is done apart from the merge, which is held for the owner's review (see HANDOFF.md).

- **28 Oct 20:20: review fixes merged (W10, `f3c26c6`); final gates green.**
  - **M1:** a newer shared version blocks every decision on an older one.
  - **M2:** per-workflow daily shares of the AI run cap (brief assist and portal assistant at 30% each, so staff keep headroom). There is also a per-member assistant limit of 10 an hour with an honest compiled answer. A bug was found and fixed along the way: every portal assistant call shared one run ref.
  - **M3:** customers append only to their own files; sharing exposes only the pinned file version (`FileVersion.customer_visible`, migration `portal` 0003).
  - **L1:** non-numeric ids give 404.
  - **L2:** events for unpublished targets are hidden (migration `portal` 0004).
  - **L3:** decisions and brief reviews lock and re-check.
  - **L4:** `.doc` and `.xls` are refused in the portal.
  - **L5:** brief assist writes a pending row before the model call.
  - **L6:** `next` is validated.
  - **Question ids** are renumbered.
  - 50 new tests. The reviewer's suspicions about cookie tossing and reset timing are recorded as follow-ups in ADR-056.
  - **Lead gate on the final tree:** ruff, format, the email guard, `makemigrations --check`, **pytest 1565 passed**, `recon_eval`, `aidata_eval`, bandit, the migration guard and Prettier, all PASS. gitleaks over history is clean.

- **28 Oct 21:15: integration complete (W5, W6, W7, W8, W9); independent review done; fixes in progress.**
  - **Merges:** W6 (guided brief) `471a52f`, W9 (seams, AC-1 to AC-12 journey test, `experience_seed_demo`, DEMO.md) `c906942`.
  - **Lead gates on the full tree:**
    - Web, all PASS: `format:check`, `check:raw-colours`, `check:turbo-env`, `content:types:check`, lint, typecheck, `pnpm test`, `check:boundaries`, `check:security`, `check:email`, and the `web` build.
    - Super Admin, all PASS: ruff, format, the email guard, `makemigrations --check`, **pytest 1514 passed**, `recon_eval`, `aidata_eval`, bandit, and the migration guard.
    - CI on #106 is green for every job that runs on a draft.
  - **gitleaks false positive fixed** (`a62b69c`): a sessionStorage key name was allowlisted by exact value. Reproduced locally (1 finding without the entry, 0 with it).
  - **Provenance fix (lead, `aea77e4`).** Found reviewing W9's screenshots, and flagged independently by the review. The portal showed the whole notification email (marker, contact rows) or a staff paste as "Your words", and "What you told us" read "No problem description was recorded". Now:
    - Only customer-authored text is a customer statement.
    - A paste never is.
    - Opportunities without an enquiry carry Vitalos's wording as agreed facts.
    - The portal and experience tests pass (175).
  - **Independent review (M7) of `471a52f`:** no critical or high findings. Isolation, the customer/staff boundary, invitations, file downloads, the signed brief-assist endpoint, XSS and AI safety held up.
    - Medium: M1, contractual acceptance of a superseded version; M2, public and customer callers can exhaust the shared daily AI run cap; M3, customer versions appended to staff files, and earlier internal versions of a shared file downloadable.
    - Low: L1, 500 on non-numeric ids; L2, events after unpublish; L3, approval and brief races; L4, legacy `.doc`/`.xls`; L5, brief-assist burst counting; L6, staff open redirect; plus a question-id mismatch.
    - W10 is fixing them test-first.

- **28 Oct 20:30: operational quality.**
  - **Lead web gate on W5 + W7 + W8** (`801cb75`), all PASS: `check:turbo-env`, `content:types:check`, lint, typecheck, `pnpm test`, `check:boundaries`, `check:security`, `check:email`, and the `web` production build. `format:check` failed only on ADR-056 (W8 had not run Prettier); fixed and re-checked.
  - **Dependency advisories** (`a3e1f82`, `30bbb33`):
    - `postcss` override raised to 8.5.23.
    - `fast-uri` override added at 3.1.9.
    - `filelock` 4.2.1 (dev requirements).
    - `pnpm audit`: no known vulnerabilities at any level. `pip-audit --strict` is clean for both requirements files.
    - Recorded in `docs/security/dependency-advisories.md`.
  - **Pre-existing defect fixed** (`1da310e`): two raw `rgb()` shadows in the Relay widget became `--relay-shadow-*` tokens, so `pnpm check:raw-colours` (and the documented local `pnpm check`) passes again. Values are unchanged.

- **28 Oct 20:05: W5 (marketing and design) merged** (`33c5fc6`).
  - **Conflicts:** docs only. The ADR index is now the union of rows (48).
  - **Seam caught by W7's drift test:** W5 added a teal `signal` token role, so the Super Admin token CSS was regenerated (`e28d3a1`). Marketing and admin now share it.
  - **Lead review of the screenshots:**
    - The hero is a click-through and labelled "Synthetic data" and "Scripted example, not live AI".
    - Checks expand to the cited source line.
    - The demonstrator shows the source beside the results, marks exceptions in text and colour, and keeps evaluation tables in a secondary Evidence section.
  - **Copy check:** "a fixed fee agreed in writing" is pre-existing approved copy (`copy.ts`), not a new commitment.
  - **Bundle:** `/ai-data` went from 195,982 to 205,166 B gzip. The budget was raised to 222,000, with the justification in ADR-054. The demonstrator rose to 200,106 B (budget 206,000). Solutions and approach dropped to 191,076 B (`sideEffects: false`).
  - **Noted:** on 390 px phones the existing "Ask Vitalos" launcher overlaps the end of the hero bullet list, as it does site-wide. This is pre-existing and left as is.
  - **W6** was told to merge `e28d3a1` and use `@vitalos/ui/interactive`.

- **28 Oct 19:40: W8 (client portal) merged** (`39524ce`).
  - **Conflicts resolved:**
    - `opportunity.html`: kept W7's tabbed layout; the portal panel comes in through `_opportunity_extensions.html` in the workspace tab.
    - The ADR index, PLAN and TASKS: kept both lanes' sections.
  - **Deploy:** `PORTAL_DOMAIN` now follows W8's `PORTAL_HOST` (`28e3d45`).
  - **Lead gate on main plus W7** (`07ddb65`), all PASS:
    - ruff and format, the email guard, `makemigrations --check`;
    - pytest 1340 passed on PostgreSQL 16;
    - `recon_eval`, `aidata_eval` (22/22), bandit;
    - the migration guard.
  - **Lead review of W8 screenshots:** the dashboard leads with "What we need from you"; blockers name who is responsible; managed systems are labelled manually reported or stale; approvals are version-specific (v1 approved, v2 awaiting a decision).
  - **W9 started** on `28e3d45`: admin ↔ portal seams (brief continuity, proposal → project, portal items in the work queue, stage visibility), the AC-1 to AC-12 journey test, `experience_seed_demo` and DEMO.md. Running: W5, W6, W9.

- **28 Oct 19:00: W7 (admin workspace) reported and was merged** into `claude/amazing-cray-miqs1x` (merge `cd98ceb`, 87 files).
  - **Lead review:** the brief-assist endpoint checks the signature before reading any field or switch, fails closed with no keys, rate-limits per visitor and globally, and stores hashes only. Every workspace view is gated to SuperAdmin or ServiceLead. The `mark_safe` call only wraps static icon markup. The migrations (`aidata` 0003, `aicore` 0002) are additive.
  - **Decision kept:** Viewers stay refused on all AI & Data pages (ADR-026: opportunities hold personal data). A redacted read-only view would be an owner decision.
  - **Pre-existing defect found** (not in CI): `pnpm check:raw-colours` fails on `main` because of two raw `rgb()` shadows in `packages/relay-widget/src/panel.css`. It is outside this scope and logged for a follow-up.
  - **W6 resumed** (the cap allows three: W5, W6, W8) with the amended signing contract: the existing v1 scheme with the new scope `assist`.

- **28 Oct 18:10:**
  - The owner approved `portal.vitalos.co.uk` and the overnight execution brief.
  - W6 paused at a checkpoint.
  - The additional requirements (durable tasks, visibility surfaces, notification retries, evaluation cases, funnel) were sent to W5, W7 and W8.
  - `portal.vitalos.co.uk` currently has no DNS records (checked over DoH), so it is free to create.
- **28 Oct 17:56:** #105 (docs checkpoint) merged.
- **28 Oct 17:50:** W5 to W8 started, each with the shared brief (lead scratchpad `briefs/shared.md`, summarised in MILESTONES.md).

- **28 Oct 19:30: W9 (integration seams and demonstration).** Full Super Admin gate green on the combined tree before changes (1486 passed). Added: the approved brief and the original enquiry carry into a linked challenge as a draft with provenance tags; "Create portal project from proposal" (idempotent, unpublished, no prices); portal items and stuck AI tasks in the work queue; the opportunity-stage to customer-stage map with an audited "Update customer-visible stage"; a status strip for staff; `experience_seed_demo`; `tests/test_experience_journey.py` (AC-1 to AC-12 plus failure recovery); [DEMO.md](DEMO.md). Migration `portal` 0002 is additive. Screenshots: lead scratchpad `shots/w9-journey/`.
