"""Production: every secret and host comes from the environment; fail closed if missing."""

from django.core.exceptions import ImproperlyConfigured

from config import content_validation

from .base import *  # noqa: F403
from .base import (
    ANSWERD_STATUS_URL,
    ANSWERD_SUPERADMIN_URL,
    ASKBRIDGE_STATUS_URL,
    ASKBRIDGE_SUPERADMIN_URL,
    ATTACHMENTS_STORAGE,
    AUTOFIX_STATUS_URL,
    AUTOFIX_SUPERADMIN_URL,
    BILLING_PUBLIC_SITE_URL,
    CAREERS_CV_BUCKET,
    CAREERS_CV_STORAGE,
    CONTENT_MEDIA_BUCKET,
    CONTENT_MEDIA_STORAGE,
    EDGE_PROXY_SECRET,
    EMAIL_TRANSPORT,
    OBJECT_STORAGE_BUCKET,
    PORTAL_FILES_BUCKET,
    PORTAL_FILES_STORAGE,
    PORTAL_PUSH_DEV_ORIGINS,
    PORTAL_PUSH_SUBJECT,
    RELAY_ADMIN_API_SECRET,
    RELAY_API_BASE_URL,
    RELAY_CLIENT,
    RELAY_WEBHOOK_SECRET,
    RESEND_API_KEY,
    SENTRY_DSN,
    TIPSIGNAL_STATUS_URL,
    TIPSIGNAL_SUPERADMIN_URL,
    WORKFORCE_STATUS_URL,
    WORKFORCE_SUPERADMIN_URL,
    env,
)

DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY")
if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be at least 50 characters.")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS")
DATABASES = {"default": env.db("DATABASE_URL")}
# Free-tier PostgreSQL behind a pooler (Supabase's session pooler by default, or Neon's PgBouncer, which
# also autosuspends after 5 idle minutes): open a fresh connection per request, health-check reused ones,
# and avoid server-side cursors, which transaction pooling does not support.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=0)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = env.bool("DB_DISABLE_SERVER_SIDE_CURSORS", default=True)
# Client portal (ADR-056, owner decision): served on its own host, nothing else is served there. The portal
# answers 404 on that host until the custom domain resolves to this app. PORTAL_ENABLED defaults to on only
# when a portal host is set; it is env-overridable, and /portal/ path mounting is local preview only.
PORTAL_HOST = env("PORTAL_HOST", default="portal.vitalos.co.uk").strip().lower()
PORTAL_ENABLED = env.bool("PORTAL_ENABLED", default=bool(PORTAL_HOST))
# Simulated assistant answers are for local demonstrations only.
PORTAL_AI_REPLAY = False
# Push (ADR-056, Phase 2): only real push services, never a local fake server, and only an https or mailto contact.
if PORTAL_PUSH_DEV_ORIGINS:
    raise ImproperlyConfigured("PORTAL_PUSH_DEV_ORIGINS is for local development and tests only.")
if not PORTAL_PUSH_SUBJECT.startswith(("mailto:", "https://")):
    raise ImproperlyConfigured("PORTAL_PUSH_SUBJECT must be a mailto: or https:// address.")
if PORTAL_ENABLED and not PORTAL_HOST:
    raise ImproperlyConfigured(
        "PORTAL_ENABLED needs PORTAL_HOST in production: /portal/ path mounting is for local preview only."
    )
if PORTAL_HOST:
    if PORTAL_HOST not in ALLOWED_HOSTS:
        ALLOWED_HOSTS = [*ALLOWED_HOSTS, PORTAL_HOST]
    if f"https://{PORTAL_HOST}" not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS = [*CSRF_TRUSTED_ORIGINS, f"https://{PORTAL_HOST}"]
APP_ENVIRONMENT = env("APP_ENVIRONMENT", default="production")
APP_BASE_URL = env("APP_BASE_URL", default="https://admin.vitalos.co.uk").rstrip("/")
if EMAIL_TRANSPORT == "resend" and not RESEND_API_KEY:
    raise ImproperlyConfigured("EMAIL_TRANSPORT=resend needs RESEND_API_KEY.")
if RELAY_CLIENT != "http":
    raise ImproperlyConfigured(
        "RELAY_CLIENT must be http in production (fake is sample data for local work)."
    )
# Relay carries transcripts and contact details: https only, and both shared secrets present.
if RELAY_API_BASE_URL:
    if not RELAY_API_BASE_URL.startswith("https://"):
        raise ImproperlyConfigured("RELAY_API_BASE_URL must be https in production.")
    if len(RELAY_ADMIN_API_SECRET or "") < 32 or len(RELAY_WEBHOOK_SECRET or "") < 32:
        raise ImproperlyConfigured(
            "RELAY_ADMIN_API_SECRET and RELAY_WEBHOOK_SECRET (32+ characters) are required with RELAY_API_BASE_URL."
        )
# Product Pipeline: the status token travels only over https, and the Open button leaves only for https.
for _name, _url in (
    ("ASKBRIDGE_STATUS_URL", ASKBRIDGE_STATUS_URL),
    ("ASKBRIDGE_SUPERADMIN_URL", ASKBRIDGE_SUPERADMIN_URL),
    ("ANSWERD_STATUS_URL", ANSWERD_STATUS_URL),
    ("ANSWERD_SUPERADMIN_URL", ANSWERD_SUPERADMIN_URL),
    ("WORKFORCE_STATUS_URL", WORKFORCE_STATUS_URL),
    ("WORKFORCE_SUPERADMIN_URL", WORKFORCE_SUPERADMIN_URL),
    ("TIPSIGNAL_STATUS_URL", TIPSIGNAL_STATUS_URL),
    ("TIPSIGNAL_SUPERADMIN_URL", TIPSIGNAL_SUPERADMIN_URL),
    ("AUTOFIX_STATUS_URL", AUTOFIX_STATUS_URL),
    ("AUTOFIX_SUPERADMIN_URL", AUTOFIX_SUPERADMIN_URL),
):
    if _url and not _url.startswith("https://"):
        raise ImproperlyConfigured(f"{_name} must be https in production.")
# Billing: customers are sent back to the public payment pages, which must be https.
if not BILLING_PUBLIC_SITE_URL.startswith("https://"):
    raise ImproperlyConfigured("BILLING_PUBLIC_SITE_URL must be https in production.")
# In production the reset email is offered only when it can actually be delivered.
PASSWORD_RESET_ENABLED = env.bool("PASSWORD_RESET_ENABLED", default=EMAIL_TRANSPORT != "log")

# TLS terminates at the platform ingress, which sets X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
# Preload-list submission is a decision for the whole vitalos.co.uk apex, not this subdomain
# (see docs/DECISIONS.md), so its deploy-check warning is acknowledged here.
SILENCED_SYSTEM_CHECKS = ["security.W021"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=1)
# The Cloudflare edge Worker's secret (EdgeProxyMiddleware) is optional, but never a short, guessable one.
if 0 < len(EDGE_PROXY_SECRET) < 32:
    raise ImproperlyConfigured("EDGE_PROXY_SECRET must be at least 32 characters.")

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    "attachments": ATTACHMENTS_STORAGE,
    "content_media": CONTENT_MEDIA_STORAGE,
    "careers_cvs": CAREERS_CV_STORAGE,
    "portal_files": PORTAL_FILES_STORAGE,
}
# Production keeps attachment bytes only in object storage; the container disk is not durable.
ATTACHMENTS_STORAGE_ENABLED = bool(OBJECT_STORAGE_BUCKET)
# Same rule for post images and CVs: no bucket, no uploads (ADR-041: no CV upload tickets).
CONTENT_MEDIA_STORAGE_ENABLED = bool(CONTENT_MEDIA_BUCKET)
CAREERS_CV_STORAGE_ENABLED = bool(CAREERS_CV_BUCKET)
PORTAL_FILES_STORAGE_ENABLED = bool(PORTAL_FILES_BUCKET)

# Insights and Careers keys, targets and the applicant IP salt (empty values leave the features off).
_content_problems = content_validation.problems(
    {
        name: globals().get(name)
        for name in (*content_validation.KEY_SETTINGS, "CONTENT_WEB_TARGETS", "CONTENT_IP_SALT")
    }
)
if _content_problems:
    raise ImproperlyConfigured(" ".join(_content_problems))

if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        environment=APP_ENVIRONMENT,
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.0),
        send_default_pii=False,
    )
