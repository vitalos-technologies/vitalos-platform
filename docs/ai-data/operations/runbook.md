# Vitalos AI & Data — operations runbook

Owner: Operations Owner (founder at launch). Scope: the public section `vitalos.co.uk/ai-data`, the AI & Data enquiry path, and the Super Admin pages under `admin.vitalos.co.uk/ai-data/`. Client production systems are **not** run from here (ADR-052).

## 1. Where things run

| Piece                                  | Host                                         | Deploys                                                                                                                                 |
| -------------------------------------- | -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Public pages and the AI & Data form    | Vercel project `vitalos-platform` (`dub1`)   | Intended: on merge to `main`. On 28 Oct 2026 the Git integration created no deployment, so production was deployed with the CLI (below) |
| Enquiry records and outbox             | Website Supabase project (ADR-019)           | No schema change in this milestone                                                                                                      |
| Pipeline, offers, budget, demonstrator | Super Admin, Azure Container Apps (UK South) | `Super Admin deploy` workflow after CI on `main` (guarded, backed up, health-checked)                                                   |

### Deploying the website when the Git integration does not

Check first: `vercel ls vitalos-platform` (or the Vercel dashboard) should show a production deployment for the merge commit within a few minutes. If none appears:

1. `git worktree add --detach /tmp/deploy <merge sha>` (a clean checkout of `main`, no `node_modules`).
2. In it: `vercel link --yes --project vitalos-platform`, then `vercel deploy --prod --yes`. Vercel builds remotely with the project's own environment variables (Root Directory `apps/web`).
3. `vercel link` writes a `.env.local` with development variables into that checkout: delete it immediately, then remove the worktree.
4. Run the smoke checks in §4.

Owner follow-up: reconnect the Vercel GitHub integration (Vercel › Project › Settings › Git) so merges deploy again; `docs/operations/deployment.md` notes Git-triggered deployments were blocked by team access.

## 2. Configuration

Website: no new variables. The AI & Data form uses the existing enquiry settings (`VITALOS_ENQUIRY_BACKEND`, Supabase, Turnstile, `EMAIL_PROVIDER`, `ENQUIRY_NOTIFICATION_TO`).

Super Admin (GitHub environment `Production`; passed through by `superadmin/deploy/gcp/deploy.sh` only when set):

| Name                   | Kind     | Purpose                                                                                     | Default when unset                   |
| ---------------------- | -------- | ------------------------------------------------------------------------------------------- | ------------------------------------ |
| `AI_DATA_LLM_API_KEY`  | secret   | Key for the OpenAI-compatible provider used by the demonstrator's model path                | Model path unavailable (parser-only) |
| `AI_DATA_LLM_BASE_URL` | variable | Provider base URL, e.g. an OpenAI-compatible `/v1` endpoint                                 | Model path unavailable               |
| `AI_DATA_LLM_MODEL`    | variable | Model id; must have a row in the price table (`apps/aicore/core/pricing.py`)                | Model path unavailable               |
| `AI_DATA_DISABLED`     | variable | `true` stops every demonstrator run (environment kill switch, overrides the in-app setting) | Runs allowed                         |

In-app (Super Admin › AI & Data › Demonstrator › Settings, SuperAdmin only, audited): kill switch, model path on/off (off by default), per-run call cap, daily run cap, monthly model budget (GBP).

Never print, log or commit a key. Add or rotate it only in the GitHub environment (or the Container Apps secret), then redeploy.

## 3. Turning on the live model path (owner step)

1. Choose a provider whose data terms suit the data (synthetic only for the demonstrator; client data needs that client's approval and terms).
2. Create a key dedicated to Vitalos AI & Data with the provider's own spending limit set as low as practical.
3. Add `AI_DATA_LLM_API_KEY` (secret) and `AI_DATA_LLM_BASE_URL`, `AI_DATA_LLM_MODEL` (variables) to the GitHub `Production` environment.
4. Run **Actions › AI & Data live evaluation** (`workflow_dispatch`). It makes at most 40 calls on synthetic data and uploads a report (7-day retention). Review it against AC-14 in `../engineering/demonstrator-acceptance.md`, then commit the report under `../evaluation/`.
5. Redeploy the Super Admin (any `superadmin/` merge, or the deploy workflow with `confirm=DEPLOY`) so the app receives the settings, then switch "Model path" on in the demonstrator settings.

## 4. Monitoring and checks

| Check                | How                                                                                                                                            | Cadence            |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ |
| Site pages up        | `curl -s -o /dev/null -w "%{http_code}" https://vitalos.co.uk/ai-data` → 200 (same for `/solutions`, `/approach`, `/demonstrator`, `/contact`) | After each deploy  |
| Enquiry path         | Outbox health per `docs/runbooks/enquiry-delivery-failure.md`; new AI & Data enquiries appear as opportunities (stage New)                     | Weekly             |
| Super Admin health   | `https://admin.vitalos.co.uk/healthz/` → 200                                                                                                   | Deploy job does it |
| Model usage and cost | Demonstrator › Settings shows today's runs and this month's estimated spend against the caps                                                   | Weekly review      |
| Evaluation gate      | Super Admin CI runs `manage.py recon_eval` on every change to `superadmin/`                                                                    | Every PR           |
| Budget               | AI & Data › Budget (actual, planned, committed against the £1,000 ceiling)                                                                     | Weekly review      |

Alerts: the existing Super Admin notifications and Sentry (when `SENTRY_DSN` is set) cover errors. Cost is capped in the application; a provider or cloud budget alert is a notification, not a cap.

## 5. Failure handling and recovery

| Situation                                       | Action                                                                                                                                                          |
| ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Model provider down, slow or returning bad data | Runs end `FAILED` (retryable) or route lines to review; nothing is accepted unvalidated. Retry later, or "Continue without model" to finish with manual review. |
| Unexpected model spend                          | Set the kill switch (in-app) or `AI_DATA_DISABLED=true` and redeploy; lower the monthly cap; rotate the key at the provider.                                    |
| AI & Data enquiries not reaching the pipeline   | They are stored in Supabase first. Check the outbox, then the Super Admin inbox; use "Create opportunity" on the enquiry. No enquiry is lost if email fails.    |
| Opportunity created twice                       | Cannot happen per enquiry (one-to-one link). Manual duplicates: move one to Lost with reason "duplicate".                                                       |
| Bad website release                             | Promote the previous Vercel deployment (`docs/runbooks/rollback.md`), then revert the PR.                                                                       |
| Bad Super Admin release                         | Run **Super Admin deploy** with `confirm=DEPLOY` from the previous good commit (`superadmin/docs/DEPLOY.md`); migrations in this milestone are additive only.   |
| Stop all AI & Data intake temporarily           | Website: `VITALOS_ENQUIRY_BACKEND=disabled` pauses every enquiry (shows the email alternative). There is no AI & Data-only switch; prefer keeping intake open.  |

## 6. Data and retention

- Website enquiries: 24 months after last contact (existing retention job).
- Opportunities: contact details anonymised 24 months after closing — `python manage.py aidata_retention` (dry run) / `--apply`. Not scheduled yet; schedule it as a documented retention job when the owner confirms the period.
- Client portal delivery records: sent ones 90 days after sending, failed or cancelled ones after 180 days, turned-off push devices after 90 days; never queued or retrying ones, notifications or audit. Daily in the content tick, a dry run until `RETENTION_ENFORCE=true`; `python manage.py portal_delivery_retention` prints the counts. Policy: [`portal-delivery-retention.md`](portal-delivery-retention.md).
- Demonstrator runs hold synthetic text only. The new-run form requires confirming the data is synthetic or explicitly authorised. Client data must not be pasted into the demonstrator.

## 7. Costs at launch

Known new spend in this milestone: **£0**. Existing services used within free tiers or existing plans (Vercel, Supabase, Azure Container Apps free grant, Resend free tier). Model calls: none until a key is configured; then capped by the monthly budget setting (default £10).
