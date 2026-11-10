"""Test settings: fast hashing, isolated database (SQLite unless DATABASE_URL is set)."""

from django.core.management.utils import get_random_secret_key

from .base import *  # noqa: F403
from .base import BASE_DIR, LOGGING, MIDDLEWARE, env

SECRET_KEY = get_random_secret_key()
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]
DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'test.sqlite3'}")}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    "attachments": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "content_media": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "careers_cvs": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "portal_files": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
}
PORTAL_FILES_STORAGE_ENABLED = True
PORTAL_HOST = ""  # tests that need a portal host override the setting
PORTAL_ENABLED = True
# Push is off unless a test generates a key; no fake push server unless a test starts one.
PORTAL_PUSH_VAPID_PRIVATE_KEY = ""
PORTAL_PUSH_SUBJECT = "mailto:support@vitalos.co.uk"
PORTAL_PUSH_DEV_ORIGINS = []
ATTACHMENTS_STORAGE_ENABLED = True
CONTENT_MEDIA_STORAGE_ENABLED = True
CAREERS_CV_STORAGE_ENABLED = True
CONTENT_MEDIA_PUBLIC_BASE_URL = "https://media.example.test"
# No content keys or website targets unless a test sets them (a developer's .env must not leak in).
CONTENT_WEB_TARGETS = []
_UNSET = ""
CONTENT_READ_CLIENT_KEYS = _UNSET
CAREERS_SUBMIT_CLIENT_KEYS = _UNSET
CONTENT_REVALIDATE_SECRET = _UNSET
CONTENT_RENDER_SECRET = _UNSET
CONTENT_PREVIEW_SECRET = _UNSET
ASKBRIDGE_STATUS_TOKEN = _UNSET
ASKBRIDGE_STATUS_URL = "https://askbridge.example.test/api/platform/v1/status"
ASKBRIDGE_SUPERADMIN_URL = "https://askbridge.example.test/superadmin"
AUTOFIX_STATUS_TOKEN = _UNSET
AUTOFIX_STATUS_URL = "https://pitline.example.test/superadmin/api/platform/v1/status"
AUTOFIX_SUPERADMIN_URL = "https://pitline.example.test/superadmin/"
RELAY_PRODUCT_STATUS_TOKEN = _UNSET
RELAY_PRODUCT_STATUS_URL = "https://relay.example.test/api/platform/v1/status"
RELAY_PRODUCT_SUPERADMIN_URL = "https://relay.example.test/admin/platform"
CONTENT_OPPORTUNISTIC_TICK = False
AI_DATA_LLM_API_KEY = _UNSET
AI_DATA_LLM_BASE_URL = _UNSET
AI_DATA_LLM_MODEL = _UNSET
AI_DATA_DISABLED = False
TURNSTILE_SECRET_KEY = _UNSET  # tests that need Turnstile set it (and stub the verification)
BILLING_STRIPE_SECRET_KEY = _UNSET
BILLING_STRIPE_WEBHOOK_SECRET = _UNSET
BILLING_PUBLIC_SITE_URL = "https://vitalos.example"
LOGGING["handlers"]["console"]["formatter"] = "text"
LOGGING["root"]["level"] = "WARNING"
LOGGING["loggers"]["django"]["level"] = "ERROR"
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_CLASSES": []}  # noqa: F405
# Static files are served by Django's test client finders; WhiteNoise needs a collected STATIC_ROOT.
MIDDLEWARE = [entry for entry in MIDDLEWARE if "whitenoise" not in entry]
