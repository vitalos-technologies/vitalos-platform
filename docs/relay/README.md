# Vitalos Relay: runbook

Relay is the chat assistant on vitalos.co.uk. It answers questions from published Vitalos knowledge, cites its sources, and hands a conversation to a named person in the Super Admin.

> **Superseded on the public site while the Askbridge key is set.** When `ASKBRIDGE_SITE_KEY` is set, vitalos.co.uk shows the Askbridge widget and does not render `RelayLauncher`, whatever `RELAY_ENABLED` says. Unset the key and redeploy to bring Relay back. The Relay packages and routes stay in the repo. See ADR-045.

> **Naming (10 Nov 2026).** "Relay" now means Vitalos's social media publishing product (relay.vitalos.co.uk), which is on the Products pages and in the Super Admin's Product Pipeline. This chat assistant is labelled **"Site assistant (legacy)"** in the Super Admin. Only those visible labels changed: the package names (`relay-core`, `relay-knowledge`, `relay-widget`), routes (`/api/relay/*`, `/relay/...`), settings (`RELAY_*`), permissions, tables and data keep "relay". The visitor-facing widget, its system prompt and the legal pages still say "Relay" until the owner decides otherwise. See the ADR-044 addendum.

Design documents:

- Decisions: `DECISIONS.md`.
- Architecture: ADR-035 to ADR-038.
- The server-to-server contract: `API.md`.
- Privacy draft: `PRIVACY.md`.
- Evals: `evals/REPORT.md`.

## Architecture in one page

```
visitor browser ──(SSE, bearer visitor token, Turnstile)──▶ apps/web /api/relay/*
   ▲  realtime pings (content-free, Supabase Broadcast)            │
   │                                                              ▼
   └──────────── Supabase (website project) ◀── @vitalos/relay-core ──▶ DeepSeek (redacted text)
                    relay schema, pgvector,                 │        ──▶ relay-embed Edge Function (gte-small)
                    pg_cron → /api/relay/cron/*             │
                                                            ├─ signed webhook ──▶ Super Admin /api/inbound/relay
Super Admin (Django, own DB) ──(HMAC-signed admin API)──────┘                     alerts: bell, toast, email
```

- **The website owns conversations** (the `relay` schema in the website Supabase project). RLS is on with no policies, and only `service_role` has grants.
- **The Super Admin never touches that database.** It calls `/api/relay/admin/*`, signed with `RELAY_ADMIN_API_SECRET`. It receives alerts on `/api/inbound/relay`, signed with `RELAY_WEBHOOK_SECRET`.
- Business rules live once, in `packages/relay-core`. The route handlers in `apps/web/src/features/relay/http` only parse, authorise and serialise.
- Knowledge is ingested by checksum, from three sources:
  - `repo`: `packages/relay-knowledge/content`;
  - `cms`: published website content;
  - `faq`: the Master FAQ, from the Notion sync or the committed snapshot.

  Team answers are written in the admin.

## Environments and configuration

Every name is in `.env.example` (website) and `superadmin/.env.example` (Super Admin). Values live only in `.env.local`, Vercel env, Supabase secrets or GitHub Actions secrets.

| Area             | Website variables                                                                                                      | Notes                                                                                                        |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Flag             | `RELAY_ENABLED`                                                                                                        | Off: no launcher, and every Relay route answers 404. **Off in production until the owner approves.**         |
| Store            | `RELAY_STORE=supabase`                                                                                                 | `memory` is for tests only. Production rejects it.                                                           |
| Model            | `RELAY_LLM_PROVIDER`, `DEEPSEEK_API_KEY`, `RELAY_MODEL=deepseek-flash`                                                 | Production rejects `mock`. `deepseek-chat` and `deepseek-reasoner` are retired and rejected.                 |
| Kill switches    | `RELAY_AI_ENABLED`, `RELAY_DAILY_TOKEN_CAP`                                                                            | Settings also has "AI on/off" and a token cap. The lower cap applies.                                        |
| Retrieval        | `RELAY_SIM_FLOOR`, `RELAY_EMBED_FUNCTION_URL`, `RELAY_EMBED_SECRET`                                                    | Without the embed function, retrieval is full-text only. The answer threshold is in Settings (default 0.40). |
| Secrets          | `RELAY_TOKEN_PEPPER`, `RELAY_IP_SALT`, `RELAY_ADMIN_API_SECRET` (+ `_PREVIOUS`), `RELAY_WEBHOOK_SECRET`, `CRON_SECRET` | Generate with `openssl rand -base64 48`.                                                                     |
| Super Admin link | `RELAY_SUPERADMIN_WEBHOOK_URL` (https in production), `RELAY_ADMIN_BASE_URL`                                           |                                                                                                              |
| Bot check        | `NEXT_PUBLIC_TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`                                                               | Shared with the enquiry form. Action `relay`.                                                                |
| Realtime         | `RELAY_REALTIME_PUBLIC_KEY`                                                                                            | Without it, the widget and admin poll.                                                                       |
| Master FAQ       | `NOTION_FAQ_TOKEN`, `RELAY_FAQ_SYNC_ENABLED`, `RELAY_FAQ_REQUIRE_HUB_ACTIVE`                                           | Without a token, the committed snapshot is used.                                                             |
| Email            | `RELAY_VISITOR_EMAILS_ENABLED=false`, `RELAY_EMAIL_FROM`                                                               | Visitor reply emails need owner approval.                                                                    |
| Tests only       | `RELAY_RATE_LIMIT_MULTIPLIER`                                                                                          | Production rejects any value other than 1.                                                                   |

**Super Admin variables:**

- `RELAY_API_BASE_URL`: the website origin. The Relay tab is hidden until it is set.
- `RELAY_ADMIN_API_SECRET` and `RELAY_WEBHOOK_SECRET`: the same values as on the website.
- `RELAY_REALTIME_ENABLED`.
- `RELAY_EMAIL_FROM`.
- `RELAY_CLIENT=http`: `fake` is for local design work and is refused in production.

## Turning Relay on (production checklist)

Each step is owner-gated where marked.

1. **Database migration.** Apply `supabase/migrations/20261015090000_relay.sql` and `20261015090100_relay_cron.sql`. First take a dump and store it outside the repo. Rehearsed on slot 1 on 15 Oct: enquiries preserved.
2. **Expose the schema.** Add the `relay` schema to the PostgREST exposed schemas (Dashboard → API settings, or `alter role authenticator set pgrst.db_schemas = 'public, graphql_public, relay'; notify pgrst, 'reload config';`).
3. **Deploy the Edge Function.** `supabase functions deploy relay-embed --no-verify-jwt`, then `supabase secrets set RELAY_EMBED_SECRET=…`.
4. **Load knowledge.** Run `pnpm relay:ingest` against production. Or set the repository variable `RELAY_INGEST_ENABLED=true` and the `RELAY_*` production-environment secrets so `.github/workflows/relay-knowledge.yml` re-indexes after content changes.
5. **Set Vercel production env.** Everything under "Environments" above, with `RELAY_ENABLED` still `false`.
6. **Set Super Admin env.** Set the Super Admin variables (Azure). Confirm the Relay tab loads.
7. **Schedule jobs.** Store the Vault secrets `relay_cron_base_url` (`https://vitalos.co.uk`, the apex: `www` redirects with a 308, which `pg_net` does not follow) and `relay_cron_secret` (= `CRON_SECRET`). Until they exist, the `pg_cron` jobs are no-ops. The Super Admin's `RELAY_API_BASE_URL` is also the apex.
8. **Owner approvals** (`PRIVACY.md`):
   - the privacy notice version that covers Relay, then set `RELAY_PRIVACY_NOTICE_VERSION`;
   - retention periods;
   - the DeepSeek key and credit.
9. **Go live.** Set `RELAY_ENABLED=true` and redeploy. Check:
   - `/api/relay/suggestions?page=/` returns 200;
   - a question streams a cited answer;
   - a hand-off appears in the Super Admin bell within 10 seconds.

## Operations

- **Kill switch, fastest first:**
  1. Super Admin → Relay → Settings → AI off. Visitors are offered a person; no redeploy.
  2. `RELAY_AI_ENABLED=false` and redeploy.
  3. `RELAY_ENABLED=false` and redeploy. The launcher disappears and the routes answer 404. Stored conversations are kept.
- **Cost:**
  - Settings → daily token cap. Insights shows tokens and estimated cost per day.
  - The `usage_daily` table holds per-day totals.
  - DeepSeek's off-peak pricing applies outside 01:00–04:00 and 06:00–10:00 UTC on weekdays.
- **Re-indexing:**
  - Seed and website content: `pnpm relay:ingest` (`--dry-run` to preview; `--force` to re-embed everything).
  - Master FAQ: `pnpm relay:faq-sync` (`--full` to reconcile) or the Sync now button.
  - Each document also has a Reindex button in Knowledge.
  - The `relay-faq-sync` cron runs every 15 minutes, plus a nightly full run.
- **Master FAQ gate:**
  - In production, FAQ entries stay draft while the Notion hub page's Status is Draft (`RELAY_FAQ_REQUIRE_HUB_ACTIVE`).
  - Needs confirmation and Held views list what is waiting.
  - To rebuild the snapshot after Notion changes: `pnpm --filter @vitalos/relay-knowledge faq-snapshot`, then commit.
- **Evals:** `pnpm relay:eval --retrieval` after any knowledge or retrieval change. `pnpm relay:eval --answers --base <url>` after prompt or model changes. Targets are in `evals/REPORT.md`.
- **Retention:**
  - Dry run: `select * from relay.purge_expired(true);`. It reports the counts it would delete.
  - Schedule it only after the owner confirms the periods (decision 20).

## Key rotation

- **Admin API secret.** Set the new value as `RELAY_ADMIN_API_SECRET` on the website, and move the old one to `RELAY_ADMIN_API_SECRET_PREVIOUS`. Redeploy, update the Super Admin's `RELAY_ADMIN_API_SECRET`, then remove `_PREVIOUS`.
- **Webhook secret.** There is no overlap window. Update both apps together. Each webhook is retried twice (after 1 s and 4 s). A hand-off alert lost in between is followed by the 10- and 30-minute reminder alerts while the hand-off stays unanswered.
- **CRON_SECRET.** Update Vercel and the Vault `relay_cron_secret` together.
- **DeepSeek key.** Create the new key, update Vercel, redeploy, then revoke the old key.
- **Token pepper or IP salt.** Rotating the pepper signs out every visitor conversation, because the stored token hashes stop matching. Rotate it only after a suspected leak. Rotating the salt only resets rate-limit buckets.
- **Embed secret.** Update the Supabase function secret and Vercel together.

## Incidents

| Symptom                                        | Check                                                                        | Fix                                                                                                            |
| ---------------------------------------------- | ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Answers stop and visitors are offered a person | Insights errors; Settings AI flag; DeepSeek status and balance               | Top up or rotate the key. The kill switch keeps hand-off working.                                              |
| The model says something wrong or unapproved   | Find it with inbox search; check the citations                               | Fix the source (FAQ in Notion, then sync; or repo content). Archive a bad team answer. Add a golden eval case. |
| No alerts in the Super Admin                   | Website function logs (webhook errors); Super Admin `RelayInboundEvent` rows | Check `RELAY_SUPERADMIN_WEBHOOK_URL` and both secrets match.                                                   |
| Reminders or digest missing                    | `select * from cron.job_run_details order by start_time desc limit 20;`      | Check the Vault secrets and `CRON_SECRET`.                                                                     |
| Retrieval poor or empty                        | `kb_chunks` rows with null `embedding`; `relay-embed` logs (`WORKER_LIMIT`)  | Re-run ingest. It repairs missing embeddings in batches.                                                       |
| Abuse or spam                                  | `rate_limits`; Turnstile dashboard                                           | Lower the rate limits in code, or turn AI off temporarily.                                                     |
| Personal data exposure                         | Stop: `RELAY_ENABLED=false`                                                  | Follow the breach process in the Trust Centre. Delete the affected conversations (audited).                    |

## Local development

- Use a VM Supabase slot (AGENTS.md). Never run Supabase locally.
- Run the website with `RELAY_ENABLED=true`, `RELAY_STORE=supabase` and `RELAY_LLM_PROVIDER=mock`. Run the Super Admin with `RELAY_API_BASE_URL=http://localhost:<web port>` and the same two secrets.
- Browser tests run Relay on the memory store with the mock provider (`playwright.config.ts`).
