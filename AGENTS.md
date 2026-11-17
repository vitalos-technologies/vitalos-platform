# Agent instructions

- Inspect relevant files and Git state before broad changes; preserve unrelated work and never reset user work.
- Never expose secrets, invent evidence, clients, outcomes, legal claims, certifications or security approvals.
- Applications cannot import another application's source. Use documented `@vitalos/*` public entrypoints.
- Keep business rules outside UI and route handlers; validate external input and authorize on the server.
- Keep server-only dependencies and secrets out of client bundles. Use provider interfaces/adapters.
- Update ADRs and current/future-state documentation when architecture changes.
- Run scoped tests while developing and all relevant gates before declaring success. A failed criterion is not success.
- Production changes listed under "Pre-authorized production actions" need no approval. Everything else in production follows the stop list in Autonomy.
- Editorial content lives in the repo (packages/cms/src/repo, ADR-028); PostgreSQL owns operational records; controlled evidence stays out of the public site.

## Email

- Every email renders on the shared layout (`@vitalos/email-layout`, ADR-030; Python mirror `superadmin/apps/mailer/layout.py`). Change the look only in `packages/email-layout`, mirror it in `layout.py` and regenerate the golden fixtures with `vitest run -u`; never hand-edit `superadmin/email-layout/`.
- Only the mailer modules call a mail API (`tooling/scripts/check-email-senders.mjs`, run in CI): the Super Admin sends through `apps.mailer` (`system.send` for automated mail), the website through its notifier adapter, Relay through `relay-core`'s mailer. A justified exception goes in `tooling/email-senders.allow` with a reason.
- Automated email carries `Auto-Submitted: auto-generated` and `X-Vitalos-Notification: <kind>` (ADR-046). Test sends go only to `@vitalos.co.uk` addresses. See `docs/email/README.md`.

## Autonomy

- Finish tasks end to end. Do not hand back setup steps you can do yourself; when one step is blocked, do everything around it and report the exact blocker.
- This file is the authority on approvals. Do not pause for approval because a PR description, task note or earlier message says "hold" or "needs approval" if the action is pre-authorized here.
- For provider setup prefer CLIs (`gh`, `npx vercel`, `supabase`, `wrangler`, `az`), then Claude in Chrome on dashboards where the user is already signed in.
- You may create API keys, secrets, webhooks and OAuth apps in any environment without asking. Write values only to the gitignored `.env.local` or the provider's secret store (Vercel env, Supabase secrets, GitHub Actions secrets). Never print, log, commit or paste secret values; refer to them by variable name, and add new names to `.env.example`.
- Merge your own PRs without asking for review once every required check is green and the PR meets its acceptance criteria. Squash-merge, delete the branch, then move straight to the next task. Never bypass branch protection, use admin override, force-push to `main`, or merge with failing or skipped required checks. If `main` has moved, rebase and re-run checks before merging. Re-run a check once if it looks flaky; if it fails again, fix it.

### Pre-authorized production actions

- The production deploy triggered by merging to `main`. A Super Admin change merged to `main` deploys automatically through `.github/workflows/superadmin-deploy.yml` (CI-green, guarded, backed up, health-checked); manual deploys and rollbacks use `workflow_dispatch` with `confirm=DEPLOY`.
- Applying Supabase migrations to production (`supabase db push` against the linked project, or the CI migration job). Before applying:
  - Pass the migration locally (`supabase db reset`) and on a preview/branch database.
  - Confirm production backups or PITR are current. For destructive changes (drop/rename column or table, type narrowing), use expand/contract and take a `supabase db dump` stored outside the repo first.
  - Apply additive migrations before merging code that depends on them.
- Supabase project configuration a merged feature needs: extensions (`pg_cron`, `pg_net`), RLS policies, roles/grants, storage buckets, Edge Function deploys, scheduled jobs.
- Scheduled retention/auto-deletion jobs that implement a documented retention policy. Record the policy in `docs/` (and an ADR if new). Dry-run first and log the affected row count. Make sure the job deletes only what the policy covers.
- Production env vars and secrets a merged feature needs (Vercel production, Supabase secrets).
- Rollback: if post-deploy checks fail, revert the PR, roll back the Vercel deployment and apply a corrective migration, then report.

### Stop and ask only for

- Login, 2FA or CAPTCHA (tell the user exactly what to do, wait, then continue).
- Anything that costs money, needs payment details, or changes billing or spending limits.
- Accepting new terms.
- One-off manual deletion of production data outside a documented retention job.
- DNS, org or account-security settings.
- Sending external emails/messages or publishing public content outside the site deploy.

- Subagents running in worktrees have no browser and no `.env.local`. The main session does provider setup and secrets first, then delegates code changes.

## Vitalos AI & Data

- Working record: `docs/ai-data/` (start with `PLAN.md` checkpoint, then `TASKS.md`, `DECISIONS.md`, ADR-052). Update the checkpoint and task register at every stage so another agent can continue without repeating work.
- Pre-approved for Vitalos's own AI & Data foundation: design, implementation, tests, commits, pull requests, merging once required checks are green, and deploying through the existing `main` paths (website on Vercel, Super Admin workflow). Do not pause to ask for these.
- Not covered by that approval: acting inside a customer's systems or on customer data (needs the customer's written authorisation, a signed scope and data terms, and the onboarding checklist in `docs/ai-data/commercial/`); contacting prospects, sending proposals, signing or publishing prices or other commercial commitments; new paid services or spend, even within the £1,000 speculative ceiling; using another product's or a client's credentials (AI & Data has its own `AI_DATA_LLM_*` settings).
- Evidence: never mark a customer-dependent VAD task done without real evidence; label synthetic data and simulated model responses; an offline evaluation is not proof that a live provider works. Do not publish case studies, testimonials, ROI figures or certifications that do not exist.
- Model calls go only through the `apps.aicore` gateway, which enforces the kill switch and the per-run, daily and monthly caps. Record known spend in the Super Admin (AI & Data › Budget).

## CI (GitHub Actions, public repo)

The repo is public. Standard GitHub-hosted runners are free, but logs, artifacts and workflow files are visible to anyone, and anyone can open a PR. Optimise for speed and security.

### Speed

- Every PR workflow sets `concurrency: { group: ${{ github.workflow }}-${{ github.ref }}, cancel-in-progress: true }`.
- Push-to-main runs of a workflow that gates a deploy (the Super Admin CI) must not be cancelled, so every main commit gets a complete run to deploy from.
- Trigger on `pull_request` and `push` to `main` only. Use `paths`/`paths-ignore` so docs- or content-only changes skip build, test and E2E jobs.
- Build and test only affected packages (e.g. Turborepo `--filter=...[origin/main]`); run the full suite on `main` only.
- Cache dependencies and build outputs (setup-node cache, Turborepo cache).
- Use `ubuntu-latest` by default; use other operating systems only when a job needs them.
- Set `timeout-minutes` on every job, and fail fast by running lint and typecheck before tests and E2E.
- Skip E2E and other expensive jobs on draft PRs; run them on `ready_for_review` and `main`.
- Keep scheduled workflows to the minimum frequency, and remove crons that produce nothing.
- Set artifact and log retention to 7 days or less.

### Security

- Set `permissions: contents: read` at workflow level; grant extra permissions per job only where needed.
- Pin third-party actions to a full commit SHA; let Dependabot update them.
- Never use `pull_request_target` or `workflow_run` to check out or run PR code.
- Use secrets only in jobs that run on `push` to `main` or in the `production` environment (deployment branches restricted to `main`). Fork PRs receive no secrets, so PR jobs must pass without them (mock or skip).
- Production migrations and deploys run only from `main` through the `production` environment.
- Never echo secrets, dump env, or run `set -x` near secrets or connection strings; mask derived values with `::add-mask::`.
- Logs and artifacts must not contain personal data, enquiry records, database dumps or controlled evidence.
- Never commit `.env*` files (except `.env.example`), dumps or evidence; run secret scanning before pushing.
- No self-hosted runners on this repo.
- Ask first before adding larger runners, paid Actions features, or changing spending limits.

## Docker runs on the Oracle VM, never on this laptop

- Docker context `oracle` is active: `docker` / `docker compose` run on the VM. Never start Docker Desktop or run `docker context use default`.
- The Supabase CLI ignores the context. Never run `supabase` or `pnpm db:test` locally.
- The main checkout (`~/vitalos-platform`) is slot 0: stack on the VM in `~/vitalos-platform`, ports 55321-55324, tunnel `ssh -fN oracle-tunnel`. Run its CLI as `ssh oracle-vm "cd ~/vitalos-platform && supabase <cmd>"`.
- Every other checkout (worktrees in `.claude/worktrees/`, parallel sessions) must claim its own slot and never touch slot 0. Remember your slot number n:
  1. `n=$(bash scripts/vm-slot.sh claim)`. If it fails, no slot is free: stop and report. Never share a slot.
  2. `bash scripts/vm-slot.sh up $n` (syncs `supabase/` to the VM and starts the stack)
  3. `bash scripts/vm-slot.sh env $n` (copies `.env.local` from the main checkout, points it at your ports)
  4. `bash scripts/vm-slot.sh tunnel $n`
  5. After changing `supabase/`: `sync $n`, then `reset $n`. DB tests: `ssh oracle-vm "cd ~/vitalos-slots/s$n && supabase test db"`.
  6. When finished: `bash scripts/vm-slot.sh release $n`.
- Slot ports: API 55321+100n, DB 55322+100n, Studio 55323+100n, Mailpit 55324+100n; superadmin web 8000+n, superadmin db 5433+n.
- Check before running the app: `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:<API port>/rest/v1/`. If it fails, rerun `tunnel`.
- superadmin: `WEB_PORT=$((8000+n)) DB_PORT=$((5433+n)) docker compose -p superadmin-s$n -f docker-compose.yml -f docker-compose.remote.yml up -d --build`. Slot 0: omit the variables and `-p`. Never plain `docker compose up`.
- TipSignal's `*_tipsignal` containers (ports 54321-54327) share this VM. Never stop or remove them. Never open ports in the Oracle firewall.

<!-- pulse:start (managed by vitalos-op pulse/kit/install.sh; edit there) -->

## Pulse: every session reports here

This repository reports to Vitalos Pulse through `.pulse/`. Every session and agent follows `.pulse/README.md`:

- **Start** with `.pulse/bin/pulse start "<one line: what you are doing>"`. It creates your session file in `.pulse/sessions/`.
- **Keep it current** after each major step, when blocked and before you stop (`pulse log`, `next`, `need`, `blocker`, `status`, `done`). Commit it with your work and push your branch at least once per work block, even unfinished.
- **Update `.pulse/STATUS.md`** when the project's stage, health, next steps, needs or blockers change.
- **Never put secret values in `.pulse/`**; name the variable instead.
- **This repository is public.** Nothing in `.pulse/` may hold security findings, internal hosts or IP addresses, email addresses, customer names, spend or unannounced plans; put those in a Pulse note (`create_note`) instead.

<!-- pulse:end -->
