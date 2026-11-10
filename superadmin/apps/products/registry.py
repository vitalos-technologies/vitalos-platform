"""The products shown in the Product Pipeline (ADR-044). Configuration, not data: no table, no migration.

Adding a product:

1. Add a ``Product`` below.
2. Add its settings (status URL, status token, superadmin URL) to ``config/settings/base.py``,
   ``config/settings/prod.py`` and ``config/settings/test.py`` (https check), ``.env.example`` and
   ``deploy/gcp/deploy.sh``; document them in ``docs/DEPLOY.md`` section 10.
3. Add its open permission to ``models.ProductAccess.Meta.permissions`` and run
   ``python manage.py makemigrations products``.
4. Add ``static/products/<key>-mark.svg`` and ``<key>-app-icon.svg``, and extend ``tests/test_products.py``.

The status endpoint must follow the contract in ADR-044 (``status.py`` validates it).
"""

from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings


@dataclass(frozen=True)
class Product:
    key: str
    name: str
    endorsement: str
    summary: str
    # Static paths (``static/products/...``).
    mark: str
    app_icon: str
    # Names of the settings that hold the server-side status endpoint, its Bearer token and the
    # product's own superadmin. Read on every access so tests and deploys can change them.
    status_url_setting: str
    status_token_setting: str
    superadmin_url_setting: str
    # Full Django permission name ("app_label.codename") that gates details and the Open button.
    open_permission: str

    @property
    def status_url(self) -> str:
        return (getattr(settings, self.status_url_setting, "") or "").strip()

    @property
    def status_token(self) -> str:
        return getattr(settings, self.status_token_setting, "") or ""

    @property
    def superadmin_url(self) -> str:
        return (getattr(settings, self.superadmin_url_setting, "") or "").strip()

    @property
    def superadmin_origin(self) -> str:
        """``scheme://host[:port]`` of the superadmin, for the page's CSP ``form-action``."""
        parts = urlsplit(self.superadmin_url)
        return (
            f"{parts.scheme}://{parts.netloc}" if parts.scheme in ("https", "http") and parts.netloc else ""
        )

    @property
    def status_configured(self) -> bool:
        return bool(self.status_token and self.status_url)

    @property
    def trusted_hosts(self) -> frozenset[str]:
        """Hosts the product's alert links may point to: its status endpoint and its superadmin."""
        hosts = {urlsplit(url).hostname for url in (self.status_url, self.superadmin_url)}
        return frozenset(host for host in hosts if host)


PRODUCTS: tuple[Product, ...] = (
    Product(
        key="askbridge",
        name="Askbridge",
        endorsement="by Vitalos",
        summary="AI customer assistant and live chat that businesses add to their website.",
        mark="products/askbridge-mark.svg",
        app_icon="products/askbridge-app-icon.svg",
        status_url_setting="ASKBRIDGE_STATUS_URL",
        # The name of the setting, not a secret.
        status_token_setting="ASKBRIDGE_STATUS_TOKEN",  # noqa: S106  # nosec B106
        superadmin_url_setting="ASKBRIDGE_SUPERADMIN_URL",
        open_permission="products.open_askbridge_superadmin",
    ),
    Product(
        key="answerd",
        name="Answerd",
        endorsement="by Vitalos",
        summary=(
            "UK local-services app where every business picks up. Clickable prototype live; "
            "the backend is being built on Vitalos Workforce."
        ),
        mark="products/answerd-mark.svg",
        app_icon="products/answerd-app-icon.svg",
        status_url_setting="ANSWERD_STATUS_URL",
        status_token_setting="ANSWERD_STATUS_TOKEN",  # noqa: S106  # nosec B106
        superadmin_url_setting="ANSWERD_SUPERADMIN_URL",
        open_permission="products.open_answerd_superadmin",
    ),
    Product(
        key="workforce",
        name="Vitalos Workforce",
        endorsement="",
        summary=(
            "AI role agents for UK SMEs that work a business's own inboxes and ask a person before "
            "anything important. In build."
        ),
        mark="products/workforce-mark.svg",
        app_icon="products/workforce-app-icon.svg",
        status_url_setting="WORKFORCE_STATUS_URL",
        status_token_setting="WORKFORCE_STATUS_TOKEN",  # noqa: S106  # nosec B106
        superadmin_url_setting="WORKFORCE_SUPERADMIN_URL",
        open_permission="products.open_workforce_superadmin",
    ),
    Product(
        key="tipsignal",
        name="TipSignal",
        endorsement="",
        summary="Football tips from a probability and decision engine, with a public, immutable track record.",
        mark="products/tipsignal-mark.svg",
        app_icon="products/tipsignal-app-icon.svg",
        status_url_setting="TIPSIGNAL_STATUS_URL",
        status_token_setting="TIPSIGNAL_STATUS_TOKEN",  # noqa: S106  # nosec B106
        superadmin_url_setting="TIPSIGNAL_SUPERADMIN_URL",
        open_permission="products.open_tipsignal_superadmin",
    ),
    Product(
        key="autofix",
        name="Pitline",
        endorsement="by Vitalos",
        summary="Online booking, reminders and AI front desk tools for independent garages.",
        mark="products/autofix-mark.svg",
        app_icon="products/autofix-app-icon.svg",
        status_url_setting="AUTOFIX_STATUS_URL",
        status_token_setting="AUTOFIX_STATUS_TOKEN",  # noqa: S106  # nosec B106
        superadmin_url_setting="AUTOFIX_SUPERADMIN_URL",
        open_permission="products.open_autofix_superadmin",
    ),
    # Relay, the social media publishing product (relay.vitalos.co.uk; ADR-044 addendum). Not the legacy
    # site assistant (``apps.relay``, labelled "Site assistant (legacy)"): its settings are RELAY_PRODUCT_*.
    Product(
        key="relay",
        name="Relay",
        endorsement="by Vitalos",
        summary="Social media publishing, inbox and AI assistant for teams.",
        mark="products/relay-mark.svg",
        app_icon="products/relay-app-icon.svg",
        status_url_setting="RELAY_PRODUCT_STATUS_URL",
        status_token_setting="RELAY_PRODUCT_STATUS_TOKEN",  # noqa: S106  # nosec B106
        superadmin_url_setting="RELAY_PRODUCT_SUPERADMIN_URL",
        open_permission="products.open_relay_superadmin",
    ),
)


def all_products() -> tuple[Product, ...]:
    return PRODUCTS


def get_product(key: str) -> Product | None:
    return next((product for product in PRODUCTS if product.key == key), None)
