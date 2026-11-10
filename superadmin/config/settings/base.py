"""Settings shared by every environment. Secrets and hosts come only from the environment."""

from datetime import timedelta
from pathlib import Path

import environ
from csp.constants import NONCE, NONE, SELF

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
if (BASE_DIR / ".env").is_file():
    environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
APP_ENVIRONMENT = env("APP_ENVIRONMENT", default="development")

INSTALLED_APPS = [
    "apps.core.apps.SuperAdminSiteConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.postgres",
    "django_htmx",
    "simple_history",
    "axes",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "csp",
    "rest_framework",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "apps.core",
    "apps.audit",
    "apps.mailer",
    "apps.accounts",
    "apps.notifications",
    "apps.architecture",
    "apps.enquiries",
    "apps.email_templates",
    "apps.outreach",
    "apps.relay",
    "apps.products",
    "apps.api",
    "apps.content_sync",
    "apps.insights",
    "apps.careers",
    "apps.aidata",
    "apps.aicore",
    "apps.recon_demo",
    "apps.billing",
    "apps.portal",
]

MIDDLEWARE = [
    "apps.core.middleware.HealthCheckMiddleware",
    "apps.core.middleware.EdgeProxyMiddleware",
    "apps.core.middleware.RequestIDMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
    "apps.portal.middleware.PortalRoutingMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.synthetic.SyntheticVisibilityMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "apps.portal.middleware.CustomerBoundaryMiddleware",
    "apps.accounts.middleware.OTPEnforcementMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "csp.middleware.CSPMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "axes.middleware.AxesMiddleware",
    "apps.content_sync.middleware.OpportunisticTickMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.app_context",
            ],
        },
    },
]

DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "architecture:home"
LOGOUT_REDIRECT_URL = "accounts:login"

# Sessions: 8 hour absolute lifetime, HTTP-only cookies.
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_NAME = "vsa_session"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_NAME = "vsa_csrftoken"
# Host-only cookies: never set a Domain attribute, so the admin host and the client portal host can never
# share a session or CSRF cookie (ADR-056). A test fails if either is set.
SESSION_COOKIE_DOMAIN = None
CSRF_COOKIE_DOMAIN = None

# django-axes: lock an email+IP combination after repeated failures.
AXES_FAILURE_LIMIT = env.int("AXES_FAILURE_LIMIT", default=5)
AXES_COOLOFF_TIME = timedelta(minutes=env.int("AXES_COOLOFF_MINUTES", default=30))
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_USERNAME_FORM_FIELD = "email"
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "accounts/lockout.html"
AXES_CLIENT_IP_CALLABLE = "apps.core.http.client_ip"
AXES_SENSITIVE_PARAMETERS = ["password"]
# Number of trusted reverse proxies in front of the app (Cloud Run's front end = 1, as Azure Container Apps'
# ingress was). Requests through the Cloudflare edge Worker take the client IP from CF-Connecting-IP instead.
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=0)
# Shared secret of the Cloudflare edge Worker in front of Cloud Run (apps.core.middleware.EdgeProxyMiddleware).
# Empty: X-Forwarded-Host is never trusted.
EDGE_PROXY_SECRET = env("EDGE_PROXY_SECRET", default="")

# django-otp: TOTP is mandatory for SuperAdmin and for anyone who enrolled a device.
# REQUIRE_MFA_FOR_SUPER_ADMIN is accepted as an alias for OTP_REQUIRED_FOR_SUPERADMIN.
OTP_TOTP_ISSUER = "Vitalos Super Admin"
OTP_REQUIRED_FOR_SUPERADMIN = env.bool(
    "OTP_REQUIRED_FOR_SUPERADMIN", default=env.bool("REQUIRE_MFA_FOR_SUPER_ADMIN", default=True)
)

# Primary owner and sign-in. The owner is created by `manage.py create_owner` with no password.
APP_BASE_URL = env("APP_BASE_URL", default="http://localhost:8000").rstrip("/")
PRIMARY_OWNER_EMAIL = env("PRIMARY_OWNER_EMAIL", default="").strip().lower()
# Pre-fills the sign-in email when set. Empty by default: pre-filling a public page reveals the login.
DEFAULT_SIGNIN_EMAIL = env("DEFAULT_SIGNIN_EMAIL", default="").strip().lower()

# Outbound email. EMAIL_TRANSPORT=log (default) never sends; resend is switched on by a human only.
EMAIL_TRANSPORT = env("EMAIL_TRANSPORT", default="log")
EMAIL_BACKEND = {
    "log": "apps.mailer.backends.LogEmailBackend",
    "resend": "apps.mailer.backends.ResendEmailBackend",
}.get(EMAIL_TRANSPORT, "apps.mailer.backends.LogEmailBackend")
RESEND_API_KEY = env("RESEND_API_KEY", default="")
RESEND_API_URL = "https://api.resend.com/emails"
NOTIFY_FROM = env("NOTIFY_FROM", default="notifications@vitalos.co.uk")
NOTIFY_FROM_HEADER = f"Vitalos Admin <{NOTIFY_FROM}>"
DEFAULT_FROM_EMAIL = NOTIFY_FROM_HEADER
SERVER_EMAIL = NOTIFY_FROM_HEADER
# Outreach (cold) email never goes through Resend: its acceptable use policy forbids cold outreach,
# and a suspension would stop every other Vitalos email. It goes through a real mailbox instead:
# Microsoft 365 over Microsoft Graph (OUTREACH_GRAPH_*, preferred) or any mailbox over SMTP
# (OUTREACH_SMTP_*). With neither set, outreach sends are refused while EMAIL_TRANSPORT=resend
# (DECISIONS 120, 127). OUTREACH_MAILBOX is the From and Reply-To address.
OUTREACH_MAILBOX = env("OUTREACH_MAILBOX", default="").strip().lower()
OUTREACH_GRAPH_TENANT_ID = env("OUTREACH_GRAPH_TENANT_ID", default="").strip()
OUTREACH_GRAPH_CLIENT_ID = env("OUTREACH_GRAPH_CLIENT_ID", default="").strip()
OUTREACH_GRAPH_CLIENT_SECRET = env("OUTREACH_GRAPH_CLIENT_SECRET", default="")
OUTREACH_SMTP_HOST = env("OUTREACH_SMTP_HOST", default="")
OUTREACH_SMTP_PORT = env.int("OUTREACH_SMTP_PORT", default=465)
OUTREACH_SMTP_USER = env("OUTREACH_SMTP_USER", default="").strip()
OUTREACH_SMTP_PASSWORD = env("OUTREACH_SMTP_PASSWORD", default="")
SUPPORT_MAILBOX = env("SUPPORT_MAILBOX", default="support@vitalos.co.uk")
SUPPORT_FROM_HEADER = f"Vitalos Support <{SUPPORT_MAILBOX}>"
NOTIFY_OWNER_EMAIL = env("NOTIFY_OWNER_EMAIL", default=PRIMARY_OWNER_EMAIL or "admin@vitalos.co.uk")
# Enquiries inbox. Inbound mail arrives from a Cloudflare Email Worker (or Resend Inbound) as signed
# webhooks; an empty secret makes the endpoint refuse everything (fail closed).
INBOUND_PROVIDER = env("INBOUND_PROVIDER", default="cloudflare")
INBOUND_WEBHOOK_SECRET = env("INBOUND_WEBHOOK_SECRET", default="")
RESEND_WEBHOOK_SECRET = env("RESEND_WEBHOOK_SECRET", default="")
TURNSTILE_SECRET_KEY = env("TURNSTILE_SECRET_KEY", default="")
SLACK_WEBHOOK_URL = env("SLACK_WEBHOOK_URL", default="")
# Retention runs as a dry run (proposal only) until a human sets RETENTION_ENFORCE=true.
RETENTION_ENFORCE = env.bool("RETENTION_ENFORCE", default=False)
# Resend free tier: 100 emails a day. Notification emails roll into the digest before the limit.
RESEND_DAILY_LIMIT = env.int("RESEND_DAILY_LIMIT", default=100)
# Vitalos Relay (website chat with hand-off to staff, ADR-035). The website owns conversations and knowledge;
# this app presents them through the website's signed admin API and receives alerts on a signed webhook.
# An empty RELAY_API_BASE_URL hides the Relay tab and makes /api/inbound/relay answer 404.
RELAY_API_BASE_URL = env("RELAY_API_BASE_URL", default="").strip().rstrip("/")
RELAY_ADMIN_API_SECRET = env("RELAY_ADMIN_API_SECRET", default="")
RELAY_WEBHOOK_SECRET = env("RELAY_WEBHOOK_SECRET", default="")
RELAY_REALTIME_ENABLED = env.bool("RELAY_REALTIME_ENABLED", default=True)
# "http" (default) talks to the website; "fake" is in-memory sample data for local UI work and tests only.
RELAY_CLIENT = env("RELAY_CLIENT", default="http").strip().lower()
RELAY_EMAIL_FROM = env("RELAY_EMAIL_FROM", default="Vitalos Relay <relay@notify.vitalos.co.uk>")
# Product Pipeline (ADR-044): each product's status is read server-side with a Bearer token and cached.
# An empty token shows "Status not configured" and makes no request. The token is a secret.
ASKBRIDGE_STATUS_URL = env(
    "ASKBRIDGE_STATUS_URL", default="https://askbridge.vitalos.co.uk/api/platform/v1/status"
).strip()
ASKBRIDGE_STATUS_TOKEN = env("ASKBRIDGE_STATUS_TOKEN", default="")
# Where "Open Askbridge Superadmin" goes after the permission check and audit. Nothing is appended to it.
ASKBRIDGE_SUPERADMIN_URL = env(
    "ASKBRIDGE_SUPERADMIN_URL", default="https://askbridge.vitalos.co.uk/superadmin"
).strip()
# Answerd, Vitalos Workforce and TipSignal have no ADR-044 status endpoint yet: their status URLs and tokens
# default to empty ("Status not configured", no request). Set them once each product serves the contract.
ANSWERD_STATUS_URL = env("ANSWERD_STATUS_URL", default="").strip()
ANSWERD_STATUS_TOKEN = env("ANSWERD_STATUS_TOKEN", default="")
# The Answerd admin console is the clickable prototype's for now (answerd-demo, demo data only).
ANSWERD_SUPERADMIN_URL = env(
    "ANSWERD_SUPERADMIN_URL", default="https://answerd-demo.vitalos.co.uk/admin"
).strip()
WORKFORCE_STATUS_URL = env("WORKFORCE_STATUS_URL", default="").strip()
WORKFORCE_STATUS_TOKEN = env("WORKFORCE_STATUS_TOKEN", default="")
# Empty until Workforce has a deployed superadmin; no Open button is shown without an address.
WORKFORCE_SUPERADMIN_URL = env("WORKFORCE_SUPERADMIN_URL", default="").strip()
TIPSIGNAL_STATUS_URL = env("TIPSIGNAL_STATUS_URL", default="").strip()
TIPSIGNAL_STATUS_TOKEN = env("TIPSIGNAL_STATUS_TOKEN", default="")
# The TipSignal admin is reachable only over Tailscale; set an https address here if one is published.
TIPSIGNAL_SUPERADMIN_URL = env("TIPSIGNAL_SUPERADMIN_URL", default="").strip()
# Pitline (formerly Autofix; the setting names keep AUTOFIX_) serves the ADR-044 contract from its own
# superadmin (DECISIONS A403 in the pitline repo).
AUTOFIX_STATUS_URL = env(
    "AUTOFIX_STATUS_URL", default="https://pitline.co.uk/superadmin/api/platform/v1/status"
).strip()
AUTOFIX_STATUS_TOKEN = env("AUTOFIX_STATUS_TOKEN", default="")
AUTOFIX_SUPERADMIN_URL = env("AUTOFIX_SUPERADMIN_URL", default="https://pitline.co.uk/superadmin/").strip()
# Relay, the social media publishing product (relay.vitalos.co.uk), serves the ADR-044 contract
# (ADR-044 addendum). RELAY_PRODUCT_ keeps these apart from the legacy site assistant's RELAY_* settings.
# The token stays empty ("Status not configured", no request) until the owner sets the secret.
RELAY_PRODUCT_STATUS_URL = env(
    "RELAY_PRODUCT_STATUS_URL", default="https://relay.vitalos.co.uk/api/platform/v1/status"
).strip()
RELAY_PRODUCT_STATUS_TOKEN = env("RELAY_PRODUCT_STATUS_TOKEN", default="")
RELAY_PRODUCT_SUPERADMIN_URL = env(
    "RELAY_PRODUCT_SUPERADMIN_URL", default="https://relay.vitalos.co.uk/admin/platform"
).strip()
# Forgot-password emails only make sense when mail can actually be delivered (or locally).
PASSWORD_RESET_ENABLED = env.bool(
    "PASSWORD_RESET_ENABLED", default=EMAIL_TRANSPORT != "log" or APP_ENVIRONMENT == "development"
)

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/London"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
# Enquiry attachments: S3-compatible object storage (Cloudflare R2) when a bucket is configured,
# local disk otherwise. Without a bucket, bytes are kept only in development (attachments.py).
OBJECT_STORAGE_ENDPOINT = env("OBJECT_STORAGE_ENDPOINT", default="")
OBJECT_STORAGE_BUCKET = env("OBJECT_STORAGE_BUCKET", default="")
OBJECT_STORAGE_ACCESS_KEY_ID = env("OBJECT_STORAGE_ACCESS_KEY_ID", default="")
OBJECT_STORAGE_SECRET_ACCESS_KEY = env("OBJECT_STORAGE_SECRET_ACCESS_KEY", default="")
OBJECT_STORAGE_REGION = env("OBJECT_STORAGE_REGION", default="auto")
if OBJECT_STORAGE_BUCKET:
    ATTACHMENTS_STORAGE = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": OBJECT_STORAGE_BUCKET,
            "endpoint_url": OBJECT_STORAGE_ENDPOINT or None,
            "access_key": OBJECT_STORAGE_ACCESS_KEY_ID,
            "secret_key": OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "region_name": OBJECT_STORAGE_REGION,
            "signature_version": "s3v4",
            "querystring_auth": True,
            "querystring_expire": 300,
            "default_acl": None,
            "file_overwrite": False,
        },
    }
else:
    ATTACHMENTS_STORAGE = {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": BASE_DIR / "media" / "attachments"},
    }
STORAGES["attachments"] = ATTACHMENTS_STORAGE
ATTACHMENTS_STORAGE_ENABLED = bool(OBJECT_STORAGE_BUCKET) or APP_ENVIRONMENT == "development"

# Insights and Careers (ADR-039 to ADR-042). Signing keys are "keyId:secret[,keyId:secret...]" lists:
# the signer uses the first entry, the verifier accepts any entry (rotation with no downtime). A scope
# with no keys fails closed (503). Values are secrets; set them only in the platform's secret store.
CONTENT_WEB_TARGETS = [url.rstrip("/") for url in env.list("CONTENT_WEB_TARGETS", default=[]) if url.strip()]
CONTENT_READ_CLIENT_KEYS = env("CONTENT_READ_CLIENT_KEYS", default="")
CAREERS_SUBMIT_CLIENT_KEYS = env("CAREERS_SUBMIT_CLIENT_KEYS", default="")
CONTENT_REVALIDATE_SECRET = env("CONTENT_REVALIDATE_SECRET", default="")
CONTENT_RENDER_SECRET = env("CONTENT_RENDER_SECRET", default="")
CONTENT_PREVIEW_SECRET = env("CONTENT_PREVIEW_SECRET", default="")
CONTENT_MEDIA_BUCKET = env("CONTENT_MEDIA_BUCKET", default="")
CONTENT_MEDIA_PUBLIC_BASE_URL = env("CONTENT_MEDIA_PUBLIC_BASE_URL", default="").rstrip("/")
CAREERS_CV_BUCKET = env("CAREERS_CV_BUCKET", default="")
CAREERS_CV_MAX_MB = env.int("CAREERS_CV_MAX_MB", default=10)
CAREERS_EMAIL_FROM = env("CAREERS_EMAIL_FROM", default="")
CAREERS_CANDIDATE_EMAILS_ENABLED = env.bool("CAREERS_CANDIDATE_EMAILS_ENABLED", default=False)
CONTENT_RELAY_SYNC_ENABLED = env.bool("CONTENT_RELAY_SYNC_ENABLED", default=False)
CONTENT_IP_SALT = env("CONTENT_IP_SALT", default="")
# Requests per minute per read key id (simple per-process counter).
CONTENT_READ_RATE_LIMIT = env.int("CONTENT_READ_RATE_LIMIT", default=600)
# The admin runs the content tick itself at most once a minute when it serves content requests (ADR-042).
CONTENT_OPPORTUNISTIC_TICK = env.bool("CONTENT_OPPORTUNISTIC_TICK", default=True)


def _s3_options(bucket: str, *, private: bool) -> dict:
    return {
        "bucket_name": bucket,
        "endpoint_url": OBJECT_STORAGE_ENDPOINT or None,
        "access_key": OBJECT_STORAGE_ACCESS_KEY_ID,
        "secret_key": OBJECT_STORAGE_SECRET_ACCESS_KEY,
        "region_name": OBJECT_STORAGE_REGION,
        "signature_version": "s3v4",
        "querystring_auth": private,
        "querystring_expire": 60,
        "default_acl": None,
        "file_overwrite": False,
    }


# Post and author images: public-read object storage when CONTENT_MEDIA_BUCKET is set (served from
# CONTENT_MEDIA_PUBLIC_BASE_URL), local disk under media/public otherwise (served by a dev-only URL).
if CONTENT_MEDIA_BUCKET:
    CONTENT_MEDIA_STORAGE = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": _s3_options(CONTENT_MEDIA_BUCKET, private=False),
    }
else:
    CONTENT_MEDIA_STORAGE = {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": BASE_DIR / "media" / "public", "base_url": "/media/"},
    }
# CVs: a private bucket with 60-second signed URLs (ADR-041), local disk otherwise.
if CAREERS_CV_BUCKET:
    CAREERS_CV_STORAGE = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": _s3_options(CAREERS_CV_BUCKET, private=True),
    }
else:
    CAREERS_CV_STORAGE = {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": BASE_DIR / "media" / "careers-cvs"},
    }
STORAGES["content_media"] = CONTENT_MEDIA_STORAGE
STORAGES["careers_cvs"] = CAREERS_CV_STORAGE
# Without a bucket, bytes are kept only in development (the production container disk is not durable).
CONTENT_MEDIA_STORAGE_ENABLED = bool(CONTENT_MEDIA_BUCKET) or APP_ENVIRONMENT == "development"
CAREERS_CV_STORAGE_ENABLED = bool(CAREERS_CV_BUCKET) or APP_ENVIRONMENT == "development"

DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
CSV_IMPORT_MAX_BYTES = 2 * 1024 * 1024

# Security headers that are safe in every environment.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Strict CSP: no inline script or style without the per-request nonce.
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": [NONE],
        "script-src": [SELF, NONCE],
        "style-src": [SELF, NONCE],
        "img-src": [SELF, "data:"],
        "font-src": [SELF],
        "connect-src": [SELF],
        "manifest-src": [SELF],
        # Enquiry message bodies render in a sandboxed same-origin iframe with their own CSP.
        "frame-src": [SELF],
        "form-action": [SELF],
        "frame-ancestors": [NONE],
        "base-uri": [NONE],
        "object-src": [NONE],
    },
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.api.authentication.ApiTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["apps.api.permissions.HasAnyRole"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"user": "600/hour"},
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Vitalos Super Admin API",
    "DESCRIPTION": "Read-only API over the Vitalos company architecture. "
    "Authenticate with `Authorization: Bearer <token>` using a token from Settings â†’ API tokens.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVE_PERMISSIONS": ["apps.api.permissions.HasAnyRole"],
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "OfferingStatusEnum": "apps.architecture.models.OfferingStatus",
        "ProjectStatusEnum": "apps.architecture.models.Project.Status",
    },
}

SIMPLE_HISTORY_REVERT_DISABLED = True
SIMPLE_HISTORY_HISTORY_CHANGE_REASON_USE_TEXT_FIELD = True

# Logging: JSON lines with request IDs by default; LOG_FORMAT=text for local readability.
LOG_LEVEL = env("LOG_LEVEL", default="INFO")
LOG_FORMAT = env("LOG_FORMAT", default="json")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "apps.core.logging.RequestIDFilter"}},
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.json.JsonFormatter",
            "fmt": "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
            "rename_fields": {"asctime": "timestamp", "levelname": "level", "name": "logger"},
        },
        "text": {"format": "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": LOG_FORMAT if LOG_FORMAT in ("json", "text") else "json",
            "filters": ["request_id"],
        }
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "django.server": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "axes": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}

SENTRY_DSN = env("SENTRY_DSN", default="")

# Vitalos AI & Data model provider (apps.aicore, AID-011/012/017). AI_DATA_LLM_PROVIDER is "anthropic"
# (default: Claude through the official SDK, model defaults to claude-sonnet-5-5) or "openai-compatible"
# (chat completions; needs AI_DATA_LLM_BASE_URL and AI_DATA_LLM_MODEL).
# An empty key leaves the live model path unavailable (the demonstrator runs parser-only). The key is a
# secret: set it only in the platform's secret store. AI_DATA_DISABLED=true is the environment kill switch
# and overrides the database setting.
AI_DATA_LLM_PROVIDER = env("AI_DATA_LLM_PROVIDER", default="anthropic").strip().lower()
AI_DATA_LLM_EFFORT = env("AI_DATA_LLM_EFFORT", default="low").strip().lower()
AI_DATA_LLM_BASE_URL = env("AI_DATA_LLM_BASE_URL", default="").strip().rstrip("/")
AI_DATA_LLM_MODEL = env("AI_DATA_LLM_MODEL", default="").strip()
AI_DATA_LLM_API_KEY = env("AI_DATA_LLM_API_KEY", default="")
AI_DATA_DISABLED = env.bool("AI_DATA_DISABLED", default=False)
# Development only (ADR-055): answer workspace AI actions with a labelled local test double instead of a live
# model. Ignored unless DEBUG is on, so it can never stand in for a live provider in production.
AI_DATA_SIMULATED_PROVIDER = env.bool("AI_DATA_SIMULATED_PROVIDER", default=False)
# Share of the daily run cap (AI settings, "Live model runs per day") that public and customer workflows may use,
# in percent, rounded down. Website brief assist (aidata.brief_*) and the portal assistant (portal.*) can be
# triggered by people outside the company, so each is held to its own share and staff workflows keep the rest.
AI_DATA_BRIEF_ASSIST_DAILY_SHARE_PERCENT = env.int("AI_DATA_BRIEF_ASSIST_DAILY_SHARE_PERCENT", default=30)
AI_DATA_PORTAL_DAILY_SHARE_PERCENT = env.int("AI_DATA_PORTAL_DAILY_SHARE_PERCENT", default=30)
# Assistant answers one portal member may request per hour before they get the compiled (non-AI) answer.
PORTAL_AI_PER_MEMBER_PER_HOUR = env.int("PORTAL_AI_PER_MEMBER_PER_HOUR", default=10)

# Billing (apps.billing): invoices, payments and Stripe. Both Stripe values are secrets: set them only in the
# platform's secret store. With no key everything works except Stripe calls (the UI says "Stripe is not
# configured"); with no webhook secret /api/webhooks/stripe/ answers 503. Use a Vitalos restricted key only,
# never another product's. BILLING_PUBLIC_SITE_URL is where the payment pages live (vitalos.co.uk/pay).
BILLING_STRIPE_SECRET_KEY = env("BILLING_STRIPE_SECRET_KEY", default="")
BILLING_STRIPE_WEBHOOK_SECRET = env("BILLING_STRIPE_WEBHOOK_SECRET", default="")
BILLING_PUBLIC_SITE_URL = env("BILLING_PUBLIC_SITE_URL", default="https://vitalos.co.uk").strip().rstrip("/")

# Client portal (apps.portal, ADR-056). PORTAL_HOST: when set, the portal URLs are served only on that host and
# the Super Admin URLs are not served there; when empty the portal is mounted at /portal/ (local preview only).
# PORTAL_ENABLED is the master switch for customer access (staff tools and "Preview as customer" always work).
PORTAL_HOST = env("PORTAL_HOST", default="").strip().lower()
PORTAL_ENABLED = env.bool("PORTAL_ENABLED", default=True)
PORTAL_INVITE_TTL_HOURS = env.int("PORTAL_INVITE_TTL_HOURS", default=72)
# A manually reported managed-service status older than this many hours is labelled stale.
PORTAL_STATUS_STALE_HOURS = env.int("PORTAL_STATUS_STALE_HOURS", default=72)
PORTAL_FILES_BUCKET = env("PORTAL_FILES_BUCKET", default="")
if PORTAL_FILES_BUCKET:
    PORTAL_FILES_STORAGE = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": _s3_options(PORTAL_FILES_BUCKET, private=True),
    }
else:
    PORTAL_FILES_STORAGE = {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": BASE_DIR / "media" / "portal-files"},
    }
STORAGES["portal_files"] = PORTAL_FILES_STORAGE
# Without a bucket, bytes are kept only in development (the production container disk is not durable).
PORTAL_FILES_STORAGE_ENABLED = bool(PORTAL_FILES_BUCKET) or APP_ENVIRONMENT == "development"
# Demonstration only: replay hand-written, labelled AI answers through the gateway's simulated provider so the
# citation UI can be shown without a live model. Never on in production (prod.py forces it off).
PORTAL_AI_REPLAY = env.bool("PORTAL_AI_REPLAY", default=False)
# Push notifications for the installable portal (ADR-056, Phase 2; apps/portal/push.py). The VAPID private key is
# a SECRET: the raw 32-byte P-256 private scalar, base64url without padding (43 characters). The production deploy
# generates it once and keeps it (Container Apps secret portal-push-vapid-private-key); the public key is derived
# from it at runtime. Empty: push is off everywhere and the Account page says so.
PORTAL_PUSH_VAPID_PRIVATE_KEY = env("PORTAL_PUSH_VAPID_PRIVATE_KEY", default="").strip()
# The VAPID "sub" claim: how a push service can reach the sender (RFC 8292).
PORTAL_PUSH_SUBJECT = env("PORTAL_PUSH_SUBJECT", default="mailto:support@vitalos.co.uk").strip()
# Local development and tests only: exact origins (scheme://host:port) of a fake push server on this machine that
# are accepted besides the push-service allowlist. Production refuses any value (prod.py).
PORTAL_PUSH_DEV_ORIGINS = env.list("PORTAL_PUSH_DEV_ORIGINS", default=[])
# Retention of portal delivery records (ADR-056, "Delivery status and retention"; apps/portal/retention.py), run
# daily by the content tick and a dry run until RETENTION_ENFORCE=true. Days; anything below 7 counts as 7.
PORTAL_DELIVERY_SENT_RETENTION_DAYS = env.int("PORTAL_DELIVERY_SENT_RETENTION_DAYS", default=90)
PORTAL_DELIVERY_FAILED_RETENTION_DAYS = env.int("PORTAL_DELIVERY_FAILED_RETENTION_DAYS", default=180)
PORTAL_PUSH_DISABLED_RETENTION_DAYS = env.int("PORTAL_PUSH_DISABLED_RETENTION_DAYS", default=90)
