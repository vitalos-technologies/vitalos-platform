#!/usr/bin/env bash
# Deploy the Vitalos Super Admin to Google Cloud Run (project vitalos-workforce, europe-west2): the service
# vitalos-superadmin and its release job vitalos-superadmin-release. The image is pulled through the Artifact
# Registry remote repository "ghcr" (a mirror of ghcr.io), the database is free-tier PostgreSQL (Supabase by
# default, or Neon), files stay on Cloudflare R2, and admin.vitalos.co.uk and portal.vitalos.co.uk reach the
# service through the Cloudflare edge Worker (EdgeProxyMiddleware, ADR-026). This script never touches DNS
# or Cloudflare.
#
#   superadmin/deploy/gcp/deploy.sh --dry-run   # print the plan and expected cost; calls nothing
#   superadmin/deploy/gcp/deploy.sh             # deploy (normally run by the "Super Admin deploy" workflow)
#
# Idempotent and resumable: the service and job are updated in place, never deleted. Secrets live in Secret
# Manager as vitalos-superadmin--<name> (the Container Apps secret names, kept). The Django secret key, the
# bootstrap password, the client portal's push (VAPID) key and the edge proxy secret are generated once and then
# kept. Secret values are never printed (and are registered with the GitHub Actions log masker in Actions).
#
# Prerequisites (DEPLOY.md §2.1, done once by the project Owner): Workload Identity Federation for this
# repository, the deploying service account and its roles, the runtime service account apps-runtime, and the
# Artifact Registry remote repository "ghcr".
#
# Environment for a real run (the deploying identity comes from gcloud, e.g. google-github-actions/auth):
#   IMAGE                      image to deploy through the mirror, e.g.
#                              europe-west2-docker.pkg.dev/vitalos-workforce/ghcr/<owner>/vitalos-platform/superadmin:<git sha>
#   DATABASE_URL               Supabase session pooler (port 5432) or Neon pooled connection string,
#                              with sslmode=require
#   NEW_DJANGO_SECRET_KEY, NEW_BOOTSTRAP_ADMIN_PASSWORD, NEW_PORTAL_PUSH_VAPID_PRIVATE_KEY, NEW_EDGE_PROXY_SECRET
#                              used only when Secret Manager has no such secret yet
# Optional: SENTRY_DSN.
# Required: BOOTSTRAP_ADMIN_EMAIL (bootstrap admin sign-in; a secret so it stays out of public logs).
# Optional mail and enquiry settings (superadmin/docs/email-setup.md), each passed through only when set:
#   plain variables  PRIMARY_OWNER_EMAIL (also reaches the release job), EMAIL_TRANSPORT, INBOUND_PROVIDER,
#                    NOTIFY_OWNER_EMAIL, OBJECT_STORAGE_ENDPOINT, OBJECT_STORAGE_BUCKET,
#                    OBJECT_STORAGE_REGION, RETENTION_ENFORCE, RELAY_API_BASE_URL, RELAY_REALTIME_ENABLED,
#                    RELAY_EMAIL_FROM, OUTREACH_MAILBOX, OUTREACH_GRAPH_TENANT_ID, OUTREACH_GRAPH_CLIENT_ID,
#                    OUTREACH_SMTP_HOST, OUTREACH_SMTP_PORT, OUTREACH_SMTP_USER
#   secrets          RESEND_API_KEY, RESEND_WEBHOOK_SECRET, INBOUND_WEBHOOK_SECRET, TURNSTILE_SECRET_KEY,
#                    OBJECT_STORAGE_ACCESS_KEY_ID, OBJECT_STORAGE_SECRET_ACCESS_KEY, SLACK_WEBHOOK_URL,
#                    RELAY_ADMIN_API_SECRET, RELAY_WEBHOOK_SECRET, OUTREACH_GRAPH_CLIENT_SECRET,
#                    OUTREACH_SMTP_PASSWORD
#                    (Secret Manager secrets, referenced with --update-secrets; an empty value never overwrites
#                    a secret that is already stored). APP_BASE_URL is always https://<domain>.
# Optional Insights and Careers settings (docs/DEPLOY.md, "Content (Insights and Careers)"), same rules:
#   plain variables  CONTENT_WEB_TARGETS, CONTENT_MEDIA_BUCKET, CONTENT_MEDIA_PUBLIC_BASE_URL, CAREERS_CV_BUCKET,
#                    CAREERS_CV_MAX_MB, CAREERS_EMAIL_FROM, CAREERS_CANDIDATE_EMAILS_ENABLED,
#                    CONTENT_RELAY_SYNC_ENABLED, CONTENT_READ_RATE_LIMIT, CONTENT_OPPORTUNISTIC_TICK
#   secrets          CONTENT_READ_CLIENT_KEYS, CAREERS_SUBMIT_CLIENT_KEYS, CONTENT_REVALIDATE_SECRET,
#                    CONTENT_RENDER_SECRET, CONTENT_PREVIEW_SECRET, CONTENT_IP_SALT
# Optional Product Pipeline settings (docs/DEPLOY.md section 10, ADR-044), same rules:
#   plain variables  ASKBRIDGE_STATUS_URL, ASKBRIDGE_SUPERADMIN_URL, AUTOFIX_STATUS_URL, AUTOFIX_SUPERADMIN_URL,
#                    RELAY_PRODUCT_STATUS_URL, RELAY_PRODUCT_SUPERADMIN_URL
#   secrets          ASKBRIDGE_STATUS_TOKEN, AUTOFIX_STATUS_TOKEN, RELAY_PRODUCT_STATUS_TOKEN
#   (AUTOFIX_* configure Pitline, formerly Autofix; the names and the secret autofix-status-token are kept.
#   RELAY_PRODUCT_* configure Relay, the social media product, not the legacy site assistant's RELAY_*.)
# Optional Vitalos AI & Data model settings (ADR-052, docs/ai-data/operations/runbook.md), same rules:
#   plain variables  AI_DATA_LLM_PROVIDER, AI_DATA_LLM_BASE_URL, AI_DATA_LLM_MODEL, AI_DATA_LLM_EFFORT,
#                    AI_DATA_DISABLED
#   secrets          AI_DATA_LLM_API_KEY
# Optional Billing settings (superadmin/apps/billing/README.md), same rules:
#   plain variables  BILLING_PUBLIC_SITE_URL
#   secrets          BILLING_STRIPE_SECRET_KEY, BILLING_STRIPE_WEBHOOK_SECRET
set -euo pipefail

DRY_RUN=0
case "${1:-}" in
  --dry-run) DRY_RUN=1 ;;
  "") ;;
  *) echo "usage: $0 [--dry-run]" >&2; exit 2 ;;
esac

PROJECT="${GCP_PROJECT:-vitalos-workforce}"
REGION="${GCP_REGION:-europe-west2}"
SERVICE="${CLOUD_RUN_SERVICE:-vitalos-superadmin}"
RELEASE_JOB="${SERVICE}-release"
# Secret Manager names are <prefix>--<secret name>, shared by the service and the job.
PREFIX="$SERVICE"
RUNTIME_SA="${RUNTIME_SERVICE_ACCOUNT:-apps-runtime@${PROJECT}.iam.gserviceaccount.com}"
DOMAIN="${CUSTOM_DOMAIN:-admin.vitalos.co.uk}"
# Client portal host (ADR-056). The app serves only the portal URLs on it.
PORTAL_HOST_NAME="${PORTAL_HOST:-portal.vitalos.co.uk}"
CPU="1"   # Cloud Run needs a whole vCPU for concurrency above 1; billed only while serving
MEMORY="512Mi"
CONCURRENCY="50"

log() { printf '\n==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
# In GitHub Actions, register values with the log masker so they can never appear in job output.
mask() { if [ "${GITHUB_ACTIONS:-}" = "true" ] && [ -n "$1" ]; then printf '::add-mask::%s\n' "$1"; fi; }
output() { if [ -n "${GITHUB_OUTPUT:-}" ]; then printf '%s=%s\n' "$1" "$2" >> "$GITHUB_OUTPUT"; fi; }
gc() { gcloud --project "$PROJECT" --quiet "$@"; }

plan() {
  cat <<EOF
Vitalos Super Admin: deployment plan (dry run, nothing is created or changed)

Project             $PROJECT
Region              $REGION
Runtime identity    $RUNTIME_SA   (exists: DEPLOY.md §2.1)
Image mirror        ${REGION}-docker.pkg.dev/$PROJECT/ghcr   (exists: Artifact Registry remote repository of ghcr.io)

Will create or update:
  1. Cloud Run job      $RELEASE_JOB
       runs /app/bin/release.sh (migrate, seed_architecture, create_superadmin, each retried 3x with
       backoff for database cold starts) once per deploy, before the service takes the new image;
       $CPU vCPU / $MEMORY, task timeout 900 s, no retries
  2. Cloud Run service  $SERVICE
       image ${IMAGE:-${REGION}-docker.pkg.dev/$PROJECT/ghcr/<owner>/vitalos-platform/superadmin:<git sha>}
       port 8000; min instances 0, max instances 1 (scale to zero); $CPU vCPU / $MEMORY; concurrency $CONCURRENCY;
       startup CPU boost; public (the Cloudflare edge Worker and Cloud Run's own address)
  3. Secret Manager secrets $PREFIX--<name> (europe-west2 only; values never printed), readable by $RUNTIME_SA:
       django-secret-key, bootstrap-admin-password, portal-push-vapid-private-key, edge-proxy-secret
       (generated once, then kept), database-url (from the GitHub production environment)
       Optional, written only when the workflow provides a non-empty value (an existing secret is never
       overwritten with an empty one; a new version is added only when the value changed): sentry-dsn,
       resend-api-key, resend-webhook-secret, inbound-webhook-secret, turnstile-secret-key,
       object-storage-access-key-id, object-storage-secret-access-key, slack-webhook-url, and the rest
       Environment variables: ALLOWED_HOSTS=$DOMAIN,$PORTAL_HOST_NAME, APP_BASE_URL=https://${DOMAIN} always;
       PRIMARY_OWNER_EMAIL (release job too), EMAIL_TRANSPORT, INBOUND_PROVIDER, NOTIFY_OWNER_EMAIL,
       OBJECT_STORAGE_ENDPOINT/BUCKET/REGION and RETENTION_ENFORCE only when provided

Not touched: DNS and Cloudflare (the edge Worker in front of $DOMAIN and $PORTAL_HOST_NAME is managed
separately); no load balancer, no Cloud SQL (Supabase or Neon free), no VPC connector.

Expected monthly cost: about £1 to £2
  - Cloud Run (request-based billing): 180,000 vCPU-s, 360,000 GiB-s and 2 million requests free per month.
    One $CPU vCPU instance uses the vCPU grant in 50 h of serving time; scaled to zero when idle, an internal
    tool stays well below that, and release-job runs take seconds.
  - Secret Manager: 6 active secret versions free, then about US\$0.06 per version a month (the Super Admin
    holds about 25); new versions are added only when a value changes.
  - Artifact Registry: 0.5 GB free, then about US\$0.10 per GB a month for cached images.
  - Supabase free plan (500 MB database) or Neon free plan; Cloudflare free DNS and Workers free plan.
EOF
}

if [ "$DRY_RUN" = 1 ]; then
  plan
  exit 0
fi

ADMIN_EMAIL="${BOOTSTRAP_ADMIN_EMAIL:?BOOTSTRAP_ADMIN_EMAIL is required (the bootstrap admin sign-in email)}"
: "${IMAGE:?Set IMAGE to the Artifact Registry mirror image to deploy}"
case "$IMAGE" in
  "${REGION}-docker.pkg.dev/$PROJECT/"*:*) ;;
  *) die "IMAGE must be a tagged image in ${REGION}-docker.pkg.dev/$PROJECT/ (got $IMAGE)" ;;
esac
: "${DATABASE_URL:?Set DATABASE_URL to the Supabase session pooler (or Neon pooled) connection string}"
mask "$DATABASE_URL"
case "$DATABASE_URL" in *sslmode=require*) ;; *) die "DATABASE_URL must include sslmode=require" ;; esac
# Supabase's direct host (db.<ref>.supabase.co) is IPv6-only, and Cloud Run has no IPv6 egress by default.
case "$DATABASE_URL" in
  *@db.*.supabase.co*) die "DATABASE_URL uses the Supabase direct host, which is IPv6-only and unreachable from Cloud Run. Use Connect -> Session pooler (port 5432) instead (DEPLOY.md)." ;;
esac
# An unescaped /, ?, # or @ in the password moves part of it into the path or host, so Django sees a wrong
# database name and the release job fails inside Cloud Run (and logs that fragment). Never print the URL here.
_db_rest=${DATABASE_URL#*://}
_db_authority=${_db_rest%%[/?#]*}
case "${_db_rest#"$_db_authority"}" in
  *@*) die "DATABASE_URL password contains an unescaped /, ? or #: URL-encode it, or use an openssl rand -hex 24 password (DEPLOY.md §2.3)." ;;
esac
case "$_db_authority" in
  *@*@*) die "DATABASE_URL has more than one @ before the host: URL-encode the password, or use an openssl rand -hex 24 password (DEPLOY.md §2.3)." ;;
  *@?*) ;;
  *) die "DATABASE_URL has no user@host part: use the full connection string from the provider (DEPLOY.md §2.3)." ;;
esac
unset _db_rest _db_authority

secret_exists() { gc secrets describe "$PREFIX--$1" >/dev/null 2>&1; }

# put_secret NAME VALUE: create the secret (London only, readable by the runtime identity) or add a version when
# the value changed. The value goes through stdin, never the command line.
put_secret() {
  local name="$PREFIX--$1" value="$2"
  mask "$value"
  if ! secret_exists "$1"; then
    printf '%s' "$value" | gc secrets create "$name" --replication-policy=user-managed --locations="$REGION" \
      --labels="app=$SERVICE" --data-file=- >/dev/null
    gc secrets add-iam-policy-binding "$name" --member "serviceAccount:$RUNTIME_SA" \
      --role roles/secretmanager.secretAccessor >/dev/null
    echo "  secret $name: created"
  elif [ "$(gc secrets versions access latest --secret "$name" 2>/dev/null)" != "$value" ]; then
    printf '%s' "$value" | gc secrets versions add "$name" --data-file=- >/dev/null
    echo "  secret $name: new version"
  fi
}

# generated_once NAME FALLBACK: keep a stored secret; create it from the newly generated fallback otherwise.
generated_once() {
  if secret_exists "$1"; then return 0; fi
  [ -n "$2" ] || die "no value for $1: the workflow must provide it on the first deploy"
  put_secret "$1" "$2"
}

log "Checking prerequisites in $PROJECT ($REGION)"
gc iam service-accounts describe "$RUNTIME_SA" >/dev/null 2>&1 || die "runtime service account $RUNTIME_SA not found: run DEPLOY.md §2.1 first"

log "Resolving secrets (generated once, then kept)"
_new="${NEW_DJANGO_SECRET_KEY:-}"
if ! secret_exists django-secret-key && [ "${#_new}" -lt 50 ]; then
  die "django-secret-key must be at least 50 characters"
fi
generated_once django-secret-key "${NEW_DJANGO_SECRET_KEY:-}"
generated_once bootstrap-admin-password "${NEW_BOOTSTRAP_ADMIN_PASSWORD:-}"
# Client portal push (ADR-056 Phase 2): the VAPID private key (raw P-256 scalar, base64url). Generated once by the
# workflow and kept; deleting the secret (README "Rotate the push key") makes the next deploy generate a new one.
if ! secret_exists portal-push-vapid-private-key && ! [[ "${NEW_PORTAL_PUSH_VAPID_PRIVATE_KEY:-}" =~ ^[A-Za-z0-9_-]{43}$ ]]; then
  die "portal-push-vapid-private-key must be a base64url P-256 private key (43 characters)"
fi
generated_once portal-push-vapid-private-key "${NEW_PORTAL_PUSH_VAPID_PRIVATE_KEY:-}"
# The Cloudflare edge Worker sends this with every request (EdgeProxyMiddleware); the Worker reads the same secret.
_new="${NEW_EDGE_PROXY_SECRET:-}"
if ! secret_exists edge-proxy-secret && [ "${#_new}" -lt 32 ]; then
  die "edge-proxy-secret must be at least 32 characters"
fi
generated_once edge-proxy-secret "${NEW_EDGE_PROXY_SECRET:-}"
unset _new
put_secret database-url "$DATABASE_URL"

SECRET_REFS=(
  DJANGO_SECRET_KEY=django-secret-key
  DATABASE_URL=database-url
  PORTAL_PUSH_VAPID_PRIVATE_KEY=portal-push-vapid-private-key
)
ENV_VARS=(
  DJANGO_SETTINGS_MODULE=config.settings.prod
  "ALLOWED_HOSTS=$DOMAIN,$PORTAL_HOST_NAME"
  "CSRF_TRUSTED_ORIGINS=https://$DOMAIN,https://$PORTAL_HOST_NAME"
  "PORTAL_HOST=$PORTAL_HOST_NAME"
  SECURE_SSL_REDIRECT=True
  # Cloud Run's front end is the one proxy hop; edge Worker requests use CF-Connecting-IP (EdgeProxyMiddleware).
  TRUSTED_PROXY_COUNT=1
  APP_ENVIRONMENT=production
  LOG_FORMAT=json
  WEB_CONCURRENCY=2
  "APP_BASE_URL=https://$DOMAIN"
)

# Optional settings. Added only when the workflow provides a non-empty value, so a deploy without them leaves
# whatever the service already holds untouched (--update-env-vars and --update-secrets keep the rest).
for _name in PRIMARY_OWNER_EMAIL EMAIL_TRANSPORT INBOUND_PROVIDER NOTIFY_OWNER_EMAIL \
  OBJECT_STORAGE_ENDPOINT OBJECT_STORAGE_BUCKET OBJECT_STORAGE_REGION RETENTION_ENFORCE \
  CONTENT_WEB_TARGETS CONTENT_MEDIA_BUCKET CONTENT_MEDIA_PUBLIC_BASE_URL CAREERS_CV_BUCKET CAREERS_CV_MAX_MB \
  CAREERS_EMAIL_FROM CAREERS_CANDIDATE_EMAILS_ENABLED CONTENT_RELAY_SYNC_ENABLED CONTENT_READ_RATE_LIMIT \
  CONTENT_OPPORTUNISTIC_TICK \
  RELAY_API_BASE_URL RELAY_REALTIME_ENABLED RELAY_EMAIL_FROM \
  OUTREACH_MAILBOX OUTREACH_GRAPH_TENANT_ID OUTREACH_GRAPH_CLIENT_ID \
  OUTREACH_SMTP_HOST OUTREACH_SMTP_PORT OUTREACH_SMTP_USER \
  ASKBRIDGE_STATUS_URL ASKBRIDGE_SUPERADMIN_URL AUTOFIX_STATUS_URL AUTOFIX_SUPERADMIN_URL \
  RELAY_PRODUCT_STATUS_URL RELAY_PRODUCT_SUPERADMIN_URL \
  AI_DATA_LLM_PROVIDER AI_DATA_LLM_BASE_URL AI_DATA_LLM_MODEL AI_DATA_LLM_EFFORT AI_DATA_DISABLED \
  BILLING_PUBLIC_SITE_URL PORTAL_ENABLED PORTAL_FILES_BUCKET; do
  if [ -n "${!_name:-}" ]; then ENV_VARS+=("$_name=${!_name}"); fi
done
add_optional_secret() {  # env var name, secret name
  local value="${!1:-}"
  if [ -n "$value" ]; then
    put_secret "$2" "$value"
    SECRET_REFS+=("$1=$2")
  fi
}
add_optional_secret SENTRY_DSN sentry-dsn
add_optional_secret RESEND_API_KEY resend-api-key
add_optional_secret RESEND_WEBHOOK_SECRET resend-webhook-secret
add_optional_secret INBOUND_WEBHOOK_SECRET inbound-webhook-secret
add_optional_secret TURNSTILE_SECRET_KEY turnstile-secret-key
add_optional_secret OBJECT_STORAGE_ACCESS_KEY_ID object-storage-access-key-id
add_optional_secret OBJECT_STORAGE_SECRET_ACCESS_KEY object-storage-secret-access-key
add_optional_secret SLACK_WEBHOOK_URL slack-webhook-url
add_optional_secret OUTREACH_GRAPH_CLIENT_SECRET outreach-graph-client-secret
add_optional_secret OUTREACH_SMTP_PASSWORD outreach-smtp-password
add_optional_secret CONTENT_READ_CLIENT_KEYS content-read-client-keys
add_optional_secret CAREERS_SUBMIT_CLIENT_KEYS careers-submit-client-keys
add_optional_secret CONTENT_REVALIDATE_SECRET content-revalidate-secret
add_optional_secret CONTENT_RENDER_SECRET content-render-secret
add_optional_secret CONTENT_PREVIEW_SECRET content-preview-secret
add_optional_secret CONTENT_IP_SALT content-ip-salt
add_optional_secret RELAY_ADMIN_API_SECRET relay-admin-api-secret
add_optional_secret RELAY_WEBHOOK_SECRET relay-webhook-secret
add_optional_secret ASKBRIDGE_STATUS_TOKEN askbridge-status-token
add_optional_secret AUTOFIX_STATUS_TOKEN autofix-status-token
add_optional_secret RELAY_PRODUCT_STATUS_TOKEN relay-product-status-token
add_optional_secret AI_DATA_LLM_API_KEY ai-data-llm-api-key
add_optional_secret BILLING_STRIPE_SECRET_KEY billing-stripe-secret-key
add_optional_secret BILLING_STRIPE_WEBHOOK_SECRET billing-stripe-webhook-secret
unset _name
# JOB_* is built from the service's lists, so PRIMARY_OWNER_EMAIL reaches the release job (create_owner).
JOB_ENV=("${ENV_VARS[@]}" "BOOTSTRAP_ADMIN_EMAIL=$ADMIN_EMAIL")
JOB_SECRETS=("${SECRET_REFS[@]}" BOOTSTRAP_ADMIN_PASSWORD=bootstrap-admin-password)
SERVICE_SECRETS=("${SECRET_REFS[@]}" EDGE_PROXY_SECRET=edge-proxy-secret)

# gcloud dict flags split on commas, and ALLOWED_HOSTS has some: use gcloud's ^DELIM^ escaping (gcloud topic escaping).
DELIM='@@'
env_flag() {
  local item out=""
  for item in "$@"; do
    case "$item" in *"$DELIM"*) die "a setting contains '$DELIM', which the deploy uses as a separator" ;; esac
    out+="$DELIM$item"
  done
  printf '^%s^%s' "$DELIM" "${out#"$DELIM"}"
}
secrets_flag() {
  local item out=""
  for item in "$@"; do out+=",${item%%=*}=$PREFIX--${item#*=}:latest"; done
  printf '%s' "${out#,}"
}

# Built before use: a failure inside $(...) in an argument would not stop the script.
JOB_ENV_FLAG="$(env_flag "${JOB_ENV[@]}")"
SERVICE_ENV_FLAG="$(env_flag "${ENV_VARS[@]}")"

log "Release job $RELEASE_JOB (migrations run before the service takes the new image)"
gc run jobs deploy "$RELEASE_JOB" --region "$REGION" --image "$IMAGE" --service-account "$RUNTIME_SA" \
  --cpu "$CPU" --memory "$MEMORY" --task-timeout 900s --max-retries 0 --command /app/bin/release.sh \
  --update-env-vars "$JOB_ENV_FLAG" --update-secrets "$(secrets_flag "${JOB_SECRETS[@]}")" >/dev/null
gc run jobs execute "$RELEASE_JOB" --region "$REGION" --wait >/dev/null ||
  die "$RELEASE_JOB failed (Cloud Run > Jobs > $RELEASE_JOB > Logs); the service still runs the previous image"
log "$RELEASE_JOB succeeded"

log "Service $SERVICE (scale to zero, $CPU vCPU / $MEMORY, max 1 instance)"
gc run deploy "$SERVICE" --region "$REGION" --image "$IMAGE" --service-account "$RUNTIME_SA" --port 8000 \
  --cpu "$CPU" --memory "$MEMORY" --min-instances 0 --max-instances 1 --concurrency "$CONCURRENCY" \
  --timeout 300 --cpu-boost \
  --update-env-vars "$SERVICE_ENV_FLAG" --update-secrets "$(secrets_flag "${SERVICE_SECRETS[@]}")" \
  --update-labels "app=$SERVICE" >/dev/null
URL="$(gc run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
output url "$URL"

# The service answers its own run.app address only through the edge path: /healthz/ ignores the host, and a
# page with the edge secret and a forwarded host shows the forwarded-host trust works for both hosts.
log "Waiting for $URL (the first request also wakes the service and the database)"
EDGE_SECRET="$(gc secrets versions access latest --secret "$PREFIX--edge-proxy-secret")"
mask "$EDGE_SECRET"
edge_code() {  # public host, path
  curl -s -o /dev/null -w '%{http_code}' --max-time 30 -H "x-forwarded-host: $1" \
    -H "x-vitalos-edge-secret: $EDGE_SECRET" "$URL$2" || true
}
healthy=0
for attempt in $(seq 1 30); do
  if curl -fsS --max-time 30 "$URL/healthz/" > /dev/null 2>&1; then healthy=1; break; fi
  sleep 10
done
[ "$healthy" = 1 ] || die "$URL/healthz/ did not answer within 5 minutes (attempt $attempt)"
admin_code="$(edge_code "$DOMAIN" /login/)"
[ "$admin_code" = 200 ] || die "$URL/login/ as $DOMAIN through the edge path returned $admin_code, expected 200"
portal_code="$(edge_code "$PORTAL_HOST_NAME" /sign-in/)"
[ "$portal_code" = 200 ] || printf '::warning::%s/sign-in/ as %s through the edge path returned %s\n' "$URL" "$PORTAL_HOST_NAME" "$portal_code"
log "Live on Cloud Run: $URL ($IMAGE); $DOMAIN /login/ $admin_code, $PORTAL_HOST_NAME /sign-in/ $portal_code"
