# Vitalos Super Admin

The internal system of record for the Vitalos company architecture, at **https://admin.vitalos.co.uk** (deployment: [docs/DEPLOY.md](docs/DEPLOY.md)).

It holds the company north star (vision, mission and the ADVISE · BUILD · OPERATE · CREATE business modes) and the six service lines. Each line has its own Practices → Solutions → Offers, team, projects, KPIs and decisions. Records are classified Public, Internal, Confidential or Restricted, archived rather than deleted, and every change is in the history.

Stack: Python 3.12, Django 5.2 LTS, HTMX 2 (django-htmx), Tailwind CSS v4 (standalone CLI, no Node), PostgreSQL 17, django-simple-history, django-axes, django-otp, django-csp, Django REST Framework with drf-spectacular, WhiteNoise and gunicorn. See [ADR-026](../docs/adr/ADR-026-superadmin-django.md).

## Pages

| URL                                                         | What                                                                                                                       |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `/login/`, `/logout/`                                       | Email and password with django-axes lockout. TOTP is required for SuperAdmin                                               |
| `/`                                                         | Overview: north-star header, KPIs, items needing attention and system status                                               |
| `/service-lines/`                                           | Service line cards: modes, active projects, headline KPI, owner (moved from `/`)                                           |
| `/enquiries/`                                               | Enquiries from support@ mail and the website form: inbox, reply, assign, SLA. SuperAdmin and ServiceLead only              |
| `/mail/templates/`                                          | Email templates (SuperAdmin): library with search and filters, block editor, live preview (desktop/mobile, light/dark, plain text), version history, duplicate, archive, send test and Use template (fill details, prefill from an enquiry, copy or download an .eml draft) |
| `/mail/outreach/`                                           | Outreach (SuperAdmin): load leads from a Notion CSV or .xlsx export, queue them, and send an outreach template one at a time (weekdays 09:00 to 17:00, daily limit) through the outreach mailbox only; paused until Start (ADR-051)                                         |
| `/mail/unsubscribe/<token>/`                                | Public, signed unsubscribe for outreach and marketing email (one-click supported)                |
| `/insights/`                                                | Insights (ADR-039): posts list and editor (working copy, editorial checks, publish, schedule, revisions, render preview in a sandboxed frame), authors, topics, homepage section and page copy |
| `/careers/`                                                 | Careers: roles (working copy, open, publish changes, pause, close, reopen, archive), applications (stages, notes, reviewer, CV download, delete) and settings (page copy, policies, candidate email templates, homepage section) |
| `/api/careers/v1/…`                                         | Application intake from the website: upload tickets (scope `submit`), the fallback CV upload target, applications       |
| `/content/sync/`                                            | Website sync log: the last 200 outbox events, Retry, Resync everything; status polls every 5 s while anything is pending |
| `/settings/content/`                                        | Open or close Insights and Careers on the website (SuperAdmin; both closed by default)                                     |
| `/api/content/v1/…`                                         | Signed read API for the website (scheme v1, `contracts/content-api/v1/openapi.yaml`); `POST tick` runs the content tick   |
| `/relay/`                                                   | Vitalos Relay (website chat hand-off, ADR-035): Inbox (needs a person, live, AI, closed; join, assign, reply, notes, hand back, close, delete), Knowledge (entries, gaps, retrieval test, Master FAQ), Insights, Settings (SuperAdmin), My notifications. SuperAdmin and ServiceLead only; hidden while `RELAY_API_BASE_URL` is empty |
| `/api/inbound/relay`                                        | Signed Relay alert webhook from the website (HMAC-SHA256 canonical string, 5-minute window, repeated event ids ignored) |
| `/ai-data/`                                                 | AI & Data (SuperAdmin and ServiceLead): opportunity pipeline with stages, scorecard and intake from AI & Data enquiries, proposed offer prices, budget against the £1,000 ceiling. See [apps/aidata/README.md](apps/aidata/README.md) |
| `/billing/invoices/`, `/billing/payments/`, `/billing/settings/` | Billing (SuperAdmin only): invoices (drafts, issue with INV-YEAR-NNNN numbers, void, payment links, record payments), the print-ready A4 invoice document with QR code, payments (matched and unmatched, Sync from Stripe) and settings. See [apps/billing/README.md](apps/billing/README.md) |
| `/pay/checkout/`                                            | Public form target for vitalos.co.uk/pay: invoice number + payment code → 303 to Stripe Checkout, or back to /pay with an error code |
| `/api/webhooks/stripe/`                                     | Stripe webhook (signature-verified, 5-minute window): checkout completed, async payment succeeded, charge refunded |
| `/products/`, `/products/<key>/`                            | Product Pipeline (ADR-044): product cards with live status from each product's server-side status endpoint (Askbridge, Answerd, Vitalos Workforce, TipSignal, Pitline), details and alerts. SuperAdmin, or a role plus `products.view_product_pipeline`; counts, alerts and Open need the product permission (`products.open_<key>_superadmin`) |
| `/products/<key>/open/`                                     | POST only: checks the product permission, writes an audit event, then redirects to the product's own superadmin (no credentials passed) |
| `/audit/`                                                   | Append-only audit trail with filters and CSV export                                                                        |
| `/help/`                                                    | In-app help                                                                                                                |
| `/settings/email/`, `/settings/notifications/`              | Mail transport status and notification preferences                                                                         |
| `/api/inbound/email`                                        | Signed webhook from the Cloudflare Email Worker (raw MIME, HMAC-SHA256, 5-minute clock window, 25 MiB limit)               |
| `/api/inbound/web-form`                                     | Signed JSON from the website contact form (honeypot, optional Turnstile); answers 201 `{ref}`                              |
| `/api/webhooks/resend`                                      | Resend delivery events (Svix-signed); `email.received` only when `INBOUND_PROVIDER=resend`                                 |
| `/s/<slug>/`                                                | Service dashboard with HTMX tabs: Overview, Structure, Team, Projects, KPIs. Modals, inline edits, archive and restore      |
| `/architecture/`                                            | Whole-company tree. Reorder, add, retire, archive and restore service lines; company-wide decisions                       |
| `/team/`, `/activity/`, `/search/?q=`                       | Team directory, filterable activity feed (from history), full-text search (live in the top bar)                            |
| `/settings/`                                                | Section menu (Organisation, Communication, Website, Developer): company profile, users and roles (Staff, and Client portal users), email, website content, notifications, API tokens, CSV import and export with dry run |
| `/notifications/`                                           | In-app notifications. The bell polls every 60 seconds                                                                      |
| `/api/v1/`, `/api/schema/`, `/api/docs/`                    | Read-only REST API (per-user Bearer tokens), OpenAPI schema, Swagger UI                                                    |
| `/django-admin/`                                            | Verified Django superusers only. The only place a hard delete is possible                                                  |
| `/healthz/`                                                 | Liveness and database probe                                                                                                |

## Staff accounts

Settings › Users & roles (SuperAdmin only) lists staff. Each row has icon actions; the rules live in `apps/accounts/lifecycle.py`, and every action is a CSRF-protected POST, audited, with the styled confirmation for anything destructive.

- **Suspend** sets `is_active=False`. It also revokes the person's API tokens and ends their sessions immediately, so their next request is signed out and API calls are refused. **Reactivate** restores sign-in but not the old tokens. The Active box in the edit form follows the same rules.
- **Reset two-step sign-in** removes their authenticator and signs them out, so they enrol a new one at their next sign-in. You reset your own from Account & security, which asks for your password.
- **Send a set-password link** emails a single-use, 30-minute link through `apps.mailer`, at most three an hour per person, to active accounts only.
- **Delete** removes the account and its personal data: profile, API tokens, authenticators, preferences and inbox. Records that pointed at the person keep their row and lose the link. The audit trail keeps its own email snapshot, and the deletion is recorded as "Deleted user #<id>".
  - Delete is refused, with what to do instead, while the person still owns live work: service lines, open opportunities, enquiries, job applications, careers roles or customer questions. Reassign the work first.
  - It is also refused while the person wrote records that are part of a customer project (client portal messages) or has Django admin history. Suspend instead.
- **Refused for everyone:** acting on your own account, the primary owner, or the last active SuperAdmin. Deleting a Django superuser is refused too (remove the flag in Django admin first). Once a primary owner exists, only they can delete another SuperAdmin.

Client portal customers are listed separately under **Client portal users**. Removing one follows ADR-056, "Member management": the account is deleted, or erased when the person wrote project records, which then show "Former member".

## Layout

```
config/            settings (base, dev, test, prod), urls, wsgi
apps/core/         governance model mixin, middleware (request ID, health, headers), template tags, admin site
apps/accounts/     email User, roles (has_service_access, role_required), TOTP, API tokens, users settings
apps/notifications in-app notifications
apps/audit/        append-only audit trail
apps/mailer/       MailProvider interface, log and Resend email backends, Resend webhook
apps/enquiries/    enquiry model, MIME ingest, inbound endpoints, selectors, SLA, notifications
apps/content_sync/ outbox (SyncEvent), signing (scheme v1, preview tokens), read API, tick, render client, site state
apps/insights/     posts, authors, topics, revisions, editorial checks, read-API builders, admin views
apps/careers/      roles, applications, intake API, alerts, retention, careers settings, admin views
apps/relay/        Relay tab: signed admin API client (+ in-memory fake), webhook alerts, emails, views
apps/aidata/       AI & Data: opportunities, scorecard, enquiry intake, offer prices, budget, retention
apps/billing/      Billing: invoices, payments, Stripe client (stdlib), webhook, /pay checkout, invoice document
apps/products/     Product Pipeline: product registry (config), status adapter + validation + cache, access, views
apps/architecture/ models, services (write rules), selectors (visibility), search, activity, CSV, views
apps/api/          DRF read-only API
templates/, static/, assets/tailwind.css
bin/               tailwind.sh, release.sh (migrate + seed + bootstrap admin), backup.sh (pg_dump)
deploy/gcp/        deploy.sh (idempotent Cloud Run deploy; --dry-run prints the plan)
tests/             pytest-django suite
e2e/smoke.py       Playwright browser smoke test (local or live)
docs/              DEPLOY.md, email-setup.md, DECISIONS.md, PHASE2.md, screenshots/
../infra/cloudflare-email-worker/   inbound mail Worker (prepared, not deployed)
```

Business rules live in `services.py` (writes) and `selectors.py` (reads and visibility), never in views or templates. Server-only settings and secrets come from environment variables ([.env.example](.env.example)).

## Develop

```sh
cd superadmin
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install -r requirements.txt -r requirements-dev.txt
bin/tailwind.sh --watch &                        # builds static/css/app.css
python manage.py migrate && python manage.py seed_architecture
BOOTSTRAP_ADMIN_PASSWORD='<12+ characters>' python manage.py create_superadmin --email you@vitalos.co.uk
python manage.py runserver
```

Windows: `bin/tailwind.sh` has no Windows binary. Download the `tailwindcss-windows-x64.exe` release of the pinned version (see `VERSION` in `bin/tailwind.sh`) from the Tailwind CSS GitHub releases and run it manually with the same arguments as the script (`-i assets/tailwind.css -o static/css/app.css`, plus `--watch` or `--minify`).

Refreshing the pinned dependencies (the lockfiles must match the Linux image, so always pass `--python-platform linux`):

```sh
uv pip compile requirements.in -o requirements.txt --python-version 3.12 --python-platform linux
uv pip compile requirements-dev.in -o requirements-dev.txt --python-version 3.12 --python-platform linux
```

Or run `docker compose up --build`, which gives PostgreSQL 17 plus the app on http://localhost:8000.

## Quality gates (CI: `.github/workflows/superadmin.yml`)

```sh
ruff check . && ruff format --check .
pytest                                          # 110 tests; DATABASE_URL=postgres://… to match CI
DJANGO_SETTINGS_MODULE=config.settings.prod … python manage.py check --deploy --fail-level WARNING
pip-audit --strict -r requirements.txt
bandit -r apps config -c pyproject.toml
```

CI also builds the image, runs the release job twice, checks a backup, and drives `e2e/smoke.py` against the production container.

## Management commands

- `seed_architecture` loads the company profile, roles and six service lines. It is idempotent and never overwrites edits.
- `create_superadmin [--email EMAIL] [--password]` creates the bootstrap SuperAdmin if it is missing, and otherwise leaves the account unchanged. The password is read **only** from `$BOOTSTRAP_ADMIN_PASSWORD`. `--password` is a flag that resets only an existing account's password from that variable.
- `create_owner` creates or confirms the primary owner (`$PRIMARY_OWNER_EMAIL`, `admin@vitalos.co.uk`) with no password. The release job runs it when the variable is set. Idempotent; other SuperAdmins are untouched.
- `issue_setup_link --email admin@vitalos.co.uk` prints a single-use set-password link, valid for 30 minutes, to the terminal only.
- `send_enquiry_notifications` flushes pending enquiry notifications and sends the 08:00 digest. Schedule it every 5 minutes (a Container Apps job, [docs/email-setup.md](docs/email-setup.md) section 8).
- `enforce_enquiry_retention` applies the 24-month retention. It is a dry run unless `RETENTION_ENFORCE=true`.
- `portal_delivery_retention` applies the client portal delivery-record retention (sent records after 90 days, failed or cancelled after 180, turned-off push devices after 90; ADR-056). The content tick runs it daily. It is a dry run unless `RETENTION_ENFORCE=true`.
- `aidata_retention [--apply]` anonymises AI & Data opportunities closed more than 24 months ago (dry run without `--apply`; not scheduled).
- `import_repo_content <file.json> [--apply]` imports Insights and roles exported from the repo content source as drafts (dry run by default; idempotent by source path; placeholders refused).
- `product_access --email EMAIL [--grant CODENAME | --revoke CODENAME]` shows, grants or revokes a user's Product Pipeline permissions (`view_product_pipeline`, `open_askbridge_superadmin`, `open_answerd_superadmin`, `open_workforce_superadmin`, `open_tipsignal_superadmin`, `open_autofix_superadmin`) and audits each change. Granting a product permission also grants `view_product_pipeline`. SuperAdmins already hold them all.
- `billing_sync_stripe [--days N]` records completed Stripe Checkout Sessions that name a Vitalos invoice (idempotent). The content tick also runs it at most every 10 minutes when `BILLING_STRIPE_SECRET_KEY` is set.
- `content_tick [--loop]` promotes due scheduled posts, closes roles past their closing date and delivers pending website sync events (ADR-042). `--loop` runs it every 60 seconds for local development. The admin also runs it in the background, at most once a minute, when it serves the content API or an Insights, Careers or Content page.

Mail (inbound Worker, Resend, DNS, secrets) is set up by the owner with [docs/email-setup.md](docs/email-setup.md); design in [ADR-029](../docs/adr/ADR-029-superadmin-enquiries-mail-console.md).

Decisions and assumptions: [docs/DECISIONS.md](docs/DECISIONS.md). Next phase: [docs/PHASE2.md](docs/PHASE2.md).
