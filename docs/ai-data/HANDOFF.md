# Handoff: Vitalos platform, AI & Data and client portal (10 Nov 2026)

For the next Claude session. Read this first, then `AGENTS.md` (the authority on approvals), `docs/ai-data/PLAN.md` (Checkpoint), `docs/ai-data/TASKS.md` and the top of the Log in `docs/ai-data/experience/PROGRESS.md`. The earlier handoff for the connected experience (#106) is `docs/ai-data/experience/HANDOFF.md`.

## 1. State right now

**Production is healthy (10 Nov 2026).**

- `https://admin.vitalos.co.uk/healthz/` returns 200. Keep the trailing slash; `/healthz` without it is 404.
- The 10 Nov deploy of `main` `2096148` succeeded: Super Admin deploy run 41495129964, attempt 3, after a fresh pre-migration backup. It put these live:
  - **vitalos-technologies/vitalos-platform#123:** account pages as section menus.
    - Super Admin Account & security has Profile `/account/`, Password `/account/password/` and Two-step `/account/two-step/`.
    - Portal Your account has `/account/`, `/account/security/` (with setup at `/account/security/two-step/`), `/account/device/`, `/account/install/` and Notification preferences.
  - **vitalos-technologies/vitalos-platform#124:** WS-006. AI & Data › Delivery and Operations read client-portal records (counts, "Needs attention" with a 7-day threshold from DECISIONS 137, a projects table, managed-service status with the portal's 72-hour stale rule). It also corrects the VAD-010 row.
- **Checked after the deploy:** admin `/account/password/`, `/account/two-step/` and `/ai-data/lifecycle/delivery/` redirect to `/login/`; portal `/account/device/` and `/account/security/two-step/` redirect to `/sign-in/`.

**The outage, 2–10 Nov 2026, for the record.**

- From 2 Nov (between 08:43 and 17:00 UTC) the Super Admin could not reach its Supabase database:
  - `/healthz/` returned 503;
  - nightly backups and deploys failed at the backup gate, with `aws-0-eu-west-2.pooler.supabase.com ... FATAL: (ENOTFOUND) tenant/user backup_reader.uhvcjsnuxdthjfainvmm not found`.
- The owner restored the Supabase project `vitalos-superadmin` (ref `uhvcjsnuxdthjfainvmm`; the dashboard now shows Healthy). On 10 Nov `/healthz/` was back to 200 and the backup and deploy passed.
- **If it happens again:**
  1. Check the project in the Supabase dashboard (paused, restricted, or a changed Session pooler host).
  2. If the host changed, update the GitHub secrets `SUPERADMIN_DATABASE_URL` (`production`) and `DATABASE_URL` (`backup`); DEPLOY.md §2.3 and §6.1 cover recreating `backup_reader`.
  3. Re-run the failed deploy.
- **This sandbox can't connect to Postgres:** outbound 5432 is blocked; only HTTPS goes through the proxy. Diagnose through the Actions logs and the public endpoints.

**Also live** (earlier, all on `main`):

| PR   | What                                                                                                                                                                                                                                                 |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #107 | Production deploy recorded; portal skip-link shadow                                                                                                                                                                                                  |
| #112 | Provider keeps the API error reason; AC-14 passes live in CI                                                                                                                                                                                         |
| #113 | Client portal installable app (PWA, Phase 1)                                                                                                                                                                                                         |
| #114 | Web Push (Phase 2); owner confirmed a real phone push on 30 Oct                                                                                                                                                                                      |
| #115 | Notification delivery status page and delivery-record retention (dry run until `RETENTION_ENFORCE`)                                                                                                                                                  |
| #116 | Customer "Upload a file"; Account settings menu; email layout v3 links; `/what-we-do` LCP fix (lazy showcase stage images)                                                                                                                           |
| #117 | Client portal under AI & Data in the sidebar; Settings section menu; staff suspend/delete with safeguards; portal member cancel/remove (kept, deleted or erased to "Former member"); Client portal users list; Demonstrator keeps the AI & Data tabs |
| #118 | Task register and checkpoint docs                                                                                                                                                                                                                    |

#119 and #120 were made in another session: they moved the Super Admin to Cloud Run (project `vitalos-workforce`, `europe-west2`, service `vitalos-superadmin`) behind a Cloudflare Worker, with Workload Identity Federation, Secret Manager and GCS backups. See `superadmin/docs/DEPLOY.md`.

## 2. Owner items still open

- **Rotate the keys** the owner pasted in chat earlier: the Anthropic key, and the Stripe `sk_test`/`pk_test` keys. Never repeat or store their values.
- **`TURNSTILE_SECRET_KEY`** (production) is still empty, so `/pay/checkout/` relies on the honeypot and rate limits only.
- **Turning on AI:** "Live model path" and "Website brief assist" in Super Admin › AI settings, then record the spend in AI & Data › Budget.
- **Stripe is in test mode.** Real invoices need a live restricted key and a live webhook (ADR-053, `superadmin/apps/billing/README.md`).
- **Retention:** read the dry-run counts first, then decide `RETENTION_ENFORCE=true`. It also enforces the enquiry and recruitment policies (`docs/ai-data/operations/portal-delivery-retention.md`).
- **The mistyped invitation** `engineerirng@…`: cancel it on its organisation's Members list once the site is up. It is the owner's click, because deleting production data by hand is on the AGENTS.md stop list.
- **Optional:** Cloudflare Email Routing subaddressing, so that `+portal@vitalos.co.uk` aliases deliver. Staff accounts cannot be portal members by design.

## 3. How work is done here

- **Approvals.** AGENTS.md pre-authorises merging your own PRs once every required check is green on the head:
  - squash, pinned to the head SHA;
  - then the automatic deploy (Super Admin CI → Super Admin deploy);
  - additive Supabase migrations.

  Stop and ask for: logins or 2FA, money, terms, DNS or account security, manual production deletions, external messages.

- **Branch.** The cloud sessions used `claude/amazing-cray-miqs1x`, reset to `origin/main` after each merge. GitHub auto-deletes merged branches, so push again to recreate the branch.
- **Batches.** The lead integrates; agents build. Each batch went to a general-purpose agent in its own worktree with no push. The lead then:
  - merges the branch onto `main`;
  - resolves `PROGRESS.md`, `DECISIONS.md` and ADR conflicts (keep both entries, newest first, renumber DECISIONS; parallel agents have collided on numbers);
  - runs the gates and sends screenshots (the owner reviews progress by screenshots; send desktop 1440 and phone 390, light and dark, synthetic data only);
  - opens the PR, subscribes to its activity and merges on green.
- **Gates** (mirror CI):
  - From `superadmin/`: `ruff check .`, `ruff format --check .`, `node ../tooling/scripts/check-email-senders.mjs`, `python manage.py makemigrations --check --dry-run`, `bandit -q -r apps config -c pyproject.toml`, `pytest -q -p no:cacheprovider` (about 1,860 tests, around 10 minutes on PostgreSQL).
  - From the root: `pnpm format:check`, `pnpm check:security`, `pnpm check:email`, `pnpm check:raw-colours`.
  - gitleaks on each changed file, one path per call.
- **Local setup:** PostgreSQL 16, `DJANGO_SETTINGS_MODULE=config.settings.test`. Synthetic seed commands are `portal_seed_demo` and `experience_seed_demo` (both refuse outside DEBUG); see `docs/ai-data/experience/DEMO.md` and DEPLOY.md §8. Playwright and Chromium are preinstalled in cloud sessions (`executablePath: '/opt/pw-browsers/chromium'` if the versions differ; never `playwright install`).
- **Known traps:**
  - `tests/test_content_hardening.py::test_slug_misses_do_not_use_up_the_read_limit` can fail on a minute boundary. Re-run once and report both results.
  - gitleaks flags the published RFC 8291 test vector in `tests/test_portal_push.py`. It has been there since #114 and is not a secret.
  - The website `seo` job enforces Lighthouse budgets in `tooling/seo/budgets.json`. Shared JavaScript dominates simulated LCP; never load hidden images eagerly.
  - `pkill -f <pattern>` kills your own shell when the pattern is in the command line. Use `pgrep -f "[n]ext-server"` or PIDs.
  - Never print, commit or message secret values; refer to them by name.
- **Email:** the shared layout lives only in `packages/email-layout`, mirrored in `superadmin/apps/mailer/layout.py`, with the fixtures regenerated by `vitest run -u` (ADR-030). Test sends go only to `@vitalos.co.uk`.

## 4. What to pick up next

1. Ask the owner to look at the new account pages and AI & Data › Delivery/Operations on the live site (signed-in pages need their login; agents only see the sign-in redirect).
2. **Open Dependabot PRs:**
   - vitalos-technologies/vitalos-platform#121 (Python minor/patch) and #91 (GitHub Actions): branches updated on 10 Nov. Merge them once green; the Python one deploys the Super Admin.
   - #122 (npm minor/patch): `e2e`, `e2e-sparse`, `e2e-draft` and `storybook-a11y` failed on 1 Nov (run 41360238059). The bumps include `@axe-core/playwright` 4.14 and `@playwright/test` 1.64.1. Root-cause the failures; don't skip tests or loosen axe.
3. **Old PRs to triage with the owner** (stale since mid-October): #87 (Health & Care launch pages), #82 (Relay case ID), #70 (sitemap revalidate), #69 (17 Oct review fixes).
4. **Task register, things Vitalos can build without a customer:**
   - WS-006 still lacks tasks and test cases per milestone and AI-drafted progress summaries with a human approval step.
   - PORTAL-14 is later phases: email OTP sign-in, contractual e-signature, live monitoring integrations, and retention jobs (each needs a documented policy first).
   - WS-007 is deliberately not started.
   - VAD-011 onward need the owner or a customer. Never mark them done without real evidence.
5. **AI & Data working record:** keep the PLAN.md checkpoint, TASKS.md and the PROGRESS.md log current at every stage.
