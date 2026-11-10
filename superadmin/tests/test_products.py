"""Product Pipeline (ADR-044): navigation, permissions, the Askbridge status card, caching and the audited Open."""

import io
import json
import re
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.core.management import call_command
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.products import client, status
from apps.products.registry import get_product

TOKEN = "askbridge-status-token-DO-NOT-RENDER-0123456789"
STATUS_URL = "https://askbridge.example.test/api/platform/v1/status"
SUPERADMIN_URL = "https://askbridge.example.test/superadmin"


def payload(**overrides):
    now = timezone.now()
    body = {
        "product": "askbridge",
        "environment": "production",
        "status": "operational",
        "checkedAt": now.isoformat(),
        "tenants": {"total": 42, "active": 30, "trial": 9, "suspended": 3},
        "subscriptions": {"active": 28, "trialing": 9, "pastDue": 2},
        "alerts": [],
        "superadminUrl": SUPERADMIN_URL,
    }
    body.update(overrides)
    return body


def alert(severity="critical", title="Stripe webhooks failing", url=SUPERADMIN_URL + "/alerts/1", minutes=12):
    return {
        "severity": severity,
        "title": title,
        "since": (timezone.now() - timedelta(minutes=minutes)).isoformat(),
        "url": url,
    }


class Stub:
    """Replaces the HTTP adapter: returns ``answer`` (or raises it) and counts calls."""

    def __init__(self):
        self.calls = []
        self.answer = payload()

    def __call__(self, url, token, timeout=client.TIMEOUT_SECONDS):
        self.calls.append({"url": url, "token": token, "timeout": timeout})
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def askbridge(settings, monkeypatch):
    settings.ASKBRIDGE_STATUS_URL = STATUS_URL
    settings.ASKBRIDGE_STATUS_TOKEN = TOKEN
    settings.ASKBRIDGE_SUPERADMIN_URL = SUPERADMIN_URL
    stub = Stub()
    monkeypatch.setattr(client, "fetch_status_json", stub)
    cache.clear()
    yield stub
    cache.clear()


def grant(user, *codenames):
    for codename in codenames:
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label="products", codename=codename)
        )


@pytest.fixture
def pipeline_viewer(viewer):
    """A Viewer who may see the Product Pipeline but not open Askbridge."""
    grant(viewer, "view_product_pipeline")
    return viewer


@pytest.fixture
def askbridge_operator(make_user):
    """A Viewer with both permissions (not a SuperAdmin)."""
    from apps.accounts.roles import VIEWER

    user = make_user(VIEWER, email="operator@example.test")
    grant(user, "view_product_pipeline", "open_askbridge_superadmin")
    return user


def page(client_for, user, path="/products/"):
    response = client_for(user).get(path)
    assert response.status_code == 200
    return response.content.decode()


# --- Navigation and access ------------------------------------------------------------------------


def test_nav_entry_shows_for_superadmin_and_permitted_users_only(
    client_for, superadmin, viewer, lead, askbridge_operator, seeded
):
    assert 'data-nav="products"' in page(client_for, superadmin, "/")
    assert 'data-nav="products"' in page(client_for, askbridge_operator, "/")
    assert 'data-nav="products"' not in page(client_for, viewer, "/")
    assert 'data-nav="products"' not in page(client_for, lead, "/")
    grant(viewer, "view_product_pipeline")
    assert 'data-nav="products"' in page(client_for, viewer, "/")


def test_pipeline_pages_are_refused_without_the_permission(client, client_for, viewer, lead, norole, seeded):
    for path in ("/products/", "/products/askbridge/"):
        assert client.get(path).status_code == 302  # anonymous: to sign-in
        assert client_for(norole).get(path).status_code == 403
        assert client_for(viewer).get(path).status_code == 403
        assert client_for(lead).get(path).status_code == 403


def test_pipeline_page_renders_with_the_askbridge_card(client_for, superadmin, askbridge, seeded):
    body = page(client_for, superadmin)
    assert re.findall(r'aria-current="page" data-nav="([a-z_]+)"', body) == ["products"]
    assert "<h1" in body and "Product Pipeline" in body
    assert 'data-product="askbridge"' in body and "Askbridge" in body and "by Vitalos" in body
    assert "products/askbridge-app-icon" in body
    assert "/products/askbridge/" in body


def test_unknown_product_is_404(client_for, superadmin, askbridge, seeded):
    assert client_for(superadmin).get("/products/nothing/").status_code == 404


# --- Status card ---------------------------------------------------------------------------------------


def test_healthy_status(client_for, superadmin, askbridge, seeded):
    body = page(client_for, superadmin)
    assert 'data-state="ok:operational"' in body and "Operational" in body
    assert re.search(r'data-testid="product-environment">.*Production', body)
    assert re.search(r'data-testid="tenants-total">42<', body)
    assert "30 active · 9 on trial · 3 suspended" in body
    assert re.search(r'data-testid="subscriptions-active">28<', body)
    assert "9 trialing · 2 past due" in body
    assert "No critical alerts." in body
    assert 'data-testid="open-superadmin"' in body
    assert askbridge.calls == [{"url": STATUS_URL, "token": TOKEN, "timeout": 3.0}]


def test_degraded_status_with_alerts(client_for, superadmin, askbridge, seeded):
    askbridge.answer = payload(
        status="degraded",
        environment="staging",
        alerts=[
            alert(title="Knowledge imports failing"),
            alert(severity="warning", title="Queue age above 5 minutes", url=None),
        ],
    )
    body = page(client_for, superadmin)
    assert 'data-state="ok:degraded"' in body and "Degraded" in body
    assert "Staging" in body
    assert "Critical alerts (1)" in body and "Knowledge imports failing" in body
    assert f'href="{SUPERADMIN_URL}/alerts/1"' in body
    assert "Queue age above 5 minutes" not in body  # the card lists critical alerts only
    detail = page(client_for, superadmin, "/products/askbridge/")
    assert "Knowledge imports failing" in detail and "Queue age above 5 minutes" in detail
    assert detail.count('data-testid="product-alert"') == 2


def test_down_status(client_for, superadmin, askbridge, seeded):
    askbridge.answer = payload(status="down")
    assert 'data-state="ok:down"' in page(client_for, superadmin)


@pytest.mark.parametrize("code", ["timeout", "unreachable", "http_500", "http_401", "http_302", "bad_json"])
def test_failure_shows_status_unavailable_and_no_numbers(client_for, superadmin, askbridge, seeded, code):
    askbridge.answer = client.StatusFetchError(code)
    body = page(client_for, superadmin)
    assert 'data-state="unavailable"' in body and "Status unavailable" in body
    assert "There has been no good check since this server started." in body
    assert 'data-testid="tenants-total"' not in body and 'data-testid="product-counts"' not in body
    assert f"({code})" in body


def test_failure_after_a_good_check_shows_its_time_but_not_its_numbers(
    client_for, superadmin, askbridge, seeded
):
    page(client_for, superadmin)
    last_good = cache.get("products:last-good:askbridge")
    assert last_good is not None
    cache.delete("products:status:askbridge")
    askbridge.answer = client.StatusFetchError("timeout")
    body = page(client_for, superadmin)
    when = timezone.localtime(last_good.received_at)
    assert f"The last good check was at {when:%H:%M} on {when.day} {when:%b %Y}." in body
    assert 'data-testid="product-counts"' not in body and ">42<" not in body


def test_unset_token_shows_status_not_configured_and_makes_no_request(
    client_for, superadmin, askbridge, settings, seeded
):
    settings.ASKBRIDGE_STATUS_TOKEN = ""
    body = page(client_for, superadmin)
    assert 'data-state="not_configured"' in body and "Status not configured" in body
    assert "ASKBRIDGE_STATUS_TOKEN" in body  # the variable name for permitted staff, never a value
    assert askbridge.calls == []
    assert 'data-testid="product-counts"' not in body


INVALID = {
    "not an object": ["askbridge"],
    "wrong product": payload(product="other"),
    "unknown status": payload(status="fine"),
    "bad environment": payload(environment="Prod <b>"),
    "count is a string": payload(tenants={"total": "42", "active": 1, "trial": 0, "suspended": 0}),
    "count is a boolean": payload(tenants={"total": 1, "active": True, "trial": 0, "suspended": 0}),
    "negative count": payload(subscriptions={"active": -1, "trialing": 0, "pastDue": 0}),
    "missing count": payload(subscriptions={"active": 1, "trialing": 0}),
    "breakdown above total": payload(tenants={"total": 1, "active": 2, "trial": 0, "suspended": 0}),
    "alerts not a list": payload(alerts={}),
    "alert without url key": payload(alerts=[{k: v for k, v in alert().items() if k != "url"}]),
    "alert to another host": payload(alerts=[alert(url="https://evil.example/x")]),
    "alert over http": payload(alerts=[alert(url="http://askbridge.example.test/x")]),
    "unknown severity": payload(alerts=[alert(severity="high")]),
    "empty title": payload(alerts=[alert(title="  ")]),
    "naive time": payload(checkedAt="2026-10-22T10:00:00"),
    "time in the future": payload(checkedAt=(timezone.now() + timedelta(hours=2)).isoformat()),
    "superadmin url not https": payload(superadminUrl="javascript:alert(1)"),
    "missing tenants": {k: v for k, v in payload().items() if k != "tenants"},
}


@pytest.mark.parametrize("answer", INVALID.values(), ids=INVALID.keys())
def test_invalid_payload_is_status_unavailable(client_for, superadmin, askbridge, seeded, answer):
    askbridge.answer = answer
    body = page(client_for, superadmin)
    assert 'data-state="unavailable"' in body and "Status unavailable" in body
    assert "(invalid:" in body
    assert 'data-testid="product-counts"' not in body
    assert "evil.example" not in body and "javascript:" not in body


def test_unknown_keys_are_ignored():
    snapshot = status.parse_status(payload(extra={"x": 1}), get_product("askbridge"))
    assert snapshot.tenants["total"] == 42 and snapshot.alerts == ()


def test_status_is_cached(client_for, superadmin, askbridge, seeded):
    page(client_for, superadmin)
    page(client_for, superadmin)
    page(client_for, superadmin, "/products/askbridge/")
    assert len(askbridge.calls) == 1
    cache.delete("products:status:askbridge")
    page(client_for, superadmin)
    assert len(askbridge.calls) == 2


def test_failures_are_cached_briefly(client_for, superadmin, askbridge, seeded, monkeypatch):
    askbridge.answer = client.StatusFetchError("timeout")
    timeouts = []
    real_set = cache.set
    monkeypatch.setattr(
        cache,
        "set",
        lambda key, value, timeout=None: timeouts.append((key, timeout)) or real_set(key, value, timeout),
    )
    page(client_for, superadmin)
    page(client_for, superadmin)
    assert len(askbridge.calls) == 1
    assert ("products:status:askbridge", status.FAILURE_CACHE_SECONDS) in timeouts


def test_an_unexpected_error_never_breaks_the_page(client_for, superadmin, askbridge, seeded):
    askbridge.answer = RuntimeError("boom")
    body = page(client_for, superadmin)
    assert "Status unavailable" in body and "(error)" in body


@pytest.mark.parametrize(
    "answer",
    [payload(alerts=[alert()]), client.StatusFetchError("timeout"), ["bad"]],
    ids=["ok", "down", "bad"],
)
def test_no_token_or_status_url_in_rendered_html(client_for, superadmin, askbridge, seeded, answer):
    askbridge.answer = answer
    for path in ("/products/", "/products/askbridge/", "/"):
        body = page(client_for, superadmin, path)
        assert TOKEN not in body and "Bearer" not in body
        assert STATUS_URL not in body


# --- Permission-gated details and the audited Open --------------------------------------------------------


def test_view_only_users_see_status_but_no_details_or_open_button(
    client_for, pipeline_viewer, askbridge, seeded
):
    askbridge.answer = payload(alerts=[alert(title="Knowledge imports failing")])
    for path in ("/products/", "/products/askbridge/"):
        body = page(client_for, pipeline_viewer, path)
        assert "Operational" in body
        assert 'data-testid="open-superadmin"' not in body and "/products/askbridge/open/" not in body
        assert 'data-testid="product-counts"' not in body and ">42<" not in body
        assert "Knowledge imports failing" not in body
        assert SUPERADMIN_URL not in body
    assert 'data-testid="no-open-permission"' in page(client_for, pipeline_viewer, "/products/askbridge/")


def test_permitted_users_see_details_and_the_open_button(client_for, askbridge_operator, askbridge, seeded):
    detail = page(client_for, askbridge_operator, "/products/askbridge/")
    assert 'data-testid="open-superadmin"' in detail and 'action="/products/askbridge/open/"' in detail
    assert 'data-testid="product-counts"' in detail and SUPERADMIN_URL in detail


def test_csp_lets_the_open_form_reach_the_superadmin_only_where_it_is_shown(
    client_for, askbridge_operator, pipeline_viewer, askbridge, seeded
):
    def form_action(user, path):
        policy = client_for(user).get(path)["Content-Security-Policy"]
        return re.search(r"form-action ([^;]*)", policy).group(1).split()

    for path in ("/products/", "/products/askbridge/"):
        assert form_action(askbridge_operator, path) == ["'self'", "https://askbridge.example.test"]
        assert form_action(pipeline_viewer, path) == ["'self'"]
    assert form_action(askbridge_operator, "/") == ["'self'"]


def test_open_redirects_and_writes_an_audit_event(client_for, askbridge_operator, askbridge, seeded):
    response = client_for(askbridge_operator).post("/products/askbridge/open/")
    assert response.status_code == 302 and response["Location"] == SUPERADMIN_URL
    event = AuditEvent.objects.get(action="products.superadmin_opened")
    assert event.actor == askbridge_operator and event.actor_email == "operator@example.test"
    assert event.entity_type == "product" and event.entity_id == "askbridge"
    assert event.summary == "Opened the Askbridge Superadmin"
    assert event.metadata == {"product": "askbridge", "destination": SUPERADMIN_URL}
    assert TOKEN not in json.dumps(event.metadata)


def test_superadmin_may_open(client_for, superadmin, askbridge, seeded):
    response = client_for(superadmin).post("/products/askbridge/open/")
    assert response.status_code == 302 and response["Location"] == SUPERADMIN_URL


def test_open_is_refused_without_the_product_permission(
    client, client_for, pipeline_viewer, lead, norole, askbridge, seeded
):
    assert client_for(pipeline_viewer).post("/products/askbridge/open/").status_code == 403
    assert client_for(lead).post("/products/askbridge/open/").status_code == 403
    assert client_for(norole).post("/products/askbridge/open/").status_code == 403
    assert client.post("/products/askbridge/open/").status_code == 302  # anonymous: to sign-in
    assert not AuditEvent.objects.filter(action="products.superadmin_opened").exists()


def test_open_needs_post_and_a_known_product(client_for, askbridge_operator, askbridge, seeded):
    client = client_for(askbridge_operator)
    assert client.get("/products/askbridge/open/").status_code == 405
    assert client.post("/products/nothing/open/").status_code == 404
    assert not AuditEvent.objects.filter(action="products.superadmin_opened").exists()


def test_open_requires_csrf(askbridge_operator, askbridge, seeded):
    from django.test import Client

    from .conftest import login

    csrf_client = login(Client(enforce_csrf_checks=True), askbridge_operator)
    assert csrf_client.post("/products/askbridge/open/").status_code == 403
    assert not AuditEvent.objects.filter(action="products.superadmin_opened").exists()


def test_audit_trail_reads_the_open_event(client_for, superadmin, askbridge, seeded):
    client = client_for(superadmin)
    client.post("/products/askbridge/open/")
    body = client.get("/audit/?action=products.superadmin_opened").content.decode()
    assert (
        "Opened a product superadmin from Product Pipeline" in body
        and "Opened the Askbridge Superadmin" in body
    )


# --- Answerd, Vitalos Workforce and TipSignal ------------------------------------------------------

OTHER_PRODUCTS = ("answerd", "workforce", "tipsignal")


@pytest.fixture
def no_other_superadmins(settings):
    """The three newer products with no superadmin address (as Workforce and TipSignal ship)."""
    settings.ANSWERD_SUPERADMIN_URL = ""
    settings.WORKFORCE_SUPERADMIN_URL = ""
    settings.TIPSIGNAL_SUPERADMIN_URL = ""


def test_pipeline_lists_every_product(client_for, superadmin, askbridge, seeded):
    body = page(client_for, superadmin)
    for key in ("askbridge", *OTHER_PRODUCTS, "autofix", "relay"):
        assert f'data-product="{key}"' in body and f"products/{key}-app-icon" in body
        assert f"/products/{key}/" in body
    assert "Answerd" in body and "Vitalos Workforce" in body and "TipSignal" in body and "Pitline" in body
    assert "Autofix" not in body
    assert "Online booking, reminders and AI front desk tools for independent garages." in body


def test_products_without_a_status_endpoint_make_no_request(client_for, superadmin, askbridge, seeded):
    page(client_for, superadmin)
    for key in OTHER_PRODUCTS:
        detail = page(client_for, superadmin, f"/products/{key}/")
        assert "Status not configured" in detail and 'data-testid="product-counts"' not in detail
    # Only Askbridge has a status endpoint and token, so it is the only product ever asked.
    assert askbridge.calls and {call["url"] for call in askbridge.calls} == {STATUS_URL}


def test_no_open_button_without_a_superadmin_address(
    client_for, superadmin, askbridge, no_other_superadmins, seeded
):
    for key in OTHER_PRODUCTS:
        detail = page(client_for, superadmin, f"/products/{key}/")
        assert 'data-testid="open-superadmin"' not in detail and f"/products/{key}/open/" not in detail
        assert 'data-testid="no-superadmin-url"' in detail
        assert client_for(superadmin).post(f"/products/{key}/open/").status_code == 404
    index = page(client_for, superadmin)
    for key in OTHER_PRODUCTS:
        assert f"/products/{key}/open/" not in index
    assert not AuditEvent.objects.filter(action="products.superadmin_opened").exists()


def test_answerd_open_redirects_to_its_superadmin_with_audit(
    client_for, superadmin, askbridge, settings, seeded
):
    settings.ANSWERD_SUPERADMIN_URL = "https://answerd.example.test/admin"
    detail = page(client_for, superadmin, "/products/answerd/")
    assert 'action="/products/answerd/open/"' in detail
    response = client_for(superadmin).post("/products/answerd/open/")
    assert response.status_code == 302 and response["Location"] == "https://answerd.example.test/admin"
    event = AuditEvent.objects.get(action="products.superadmin_opened")
    assert event.entity_id == "answerd" and event.summary == "Opened the Answerd Superadmin"


def test_each_product_has_its_own_open_permission(
    client_for, askbridge_operator, askbridge, settings, seeded
):
    settings.ANSWERD_SUPERADMIN_URL = "https://answerd.example.test/admin"
    assert client_for(askbridge_operator).post("/products/answerd/open/").status_code == 403
    detail = page(client_for, askbridge_operator, "/products/answerd/")
    assert 'data-testid="no-open-permission"' in detail
    grant(askbridge_operator, "open_answerd_superadmin")
    operator = type(askbridge_operator).objects.get(pk=askbridge_operator.pk)
    assert client_for(operator).post("/products/answerd/open/").status_code == 302


def test_product_access_command_knows_the_new_products(viewer, seeded):
    out = io.StringIO()
    for codename in ("open_answerd_superadmin", "open_workforce_superadmin", "open_tipsignal_superadmin"):
        call_command("product_access", "--email", viewer.email, "--grant", codename, stdout=out)
    viewer = type(viewer).objects.get(pk=viewer.pk)
    assert viewer.has_perm("products.open_tipsignal_superadmin") and viewer.has_perm(
        "products.open_workforce_superadmin"
    )


# --- Pitline (formerly Autofix; the key, codename and settings keep autofix) --------------------------------

AUTOFIX_TOKEN = "autofix-status-token-DO-NOT-RENDER-9876543210"
AUTOFIX_STATUS_URL = "https://pitline.example.test/superadmin/api/platform/v1/status"
AUTOFIX_SUPERADMIN_URL = "https://pitline.example.test/superadmin/"


def autofix_payload(**overrides):
    """What Pitline serves (``apps/autofix/status.py`` in the pitline repo, DECISIONS A403)."""
    body = {
        "product": "autofix",
        "environment": "production",
        "status": "operational",
        "checkedAt": timezone.now().isoformat().replace("+00:00", "Z"),
        # Pitline adds onboarding and cancelled; the contract ignores unknown keys.
        "tenants": {"total": 12, "active": 7, "trial": 3, "suspended": 1, "onboarding": 3, "cancelled": 1},
        "subscriptions": {"active": 6, "trialing": 3, "pastDue": 1},
        "alerts": [],
        "superadminUrl": AUTOFIX_SUPERADMIN_URL,
    }
    body.update(overrides)
    return body


@pytest.fixture
def autofix(askbridge, settings, monkeypatch):
    """Pitline configured; its answers come from ``autofix.answer``, Askbridge's from the Askbridge stub."""
    settings.AUTOFIX_STATUS_URL = AUTOFIX_STATUS_URL
    settings.AUTOFIX_STATUS_TOKEN = AUTOFIX_TOKEN
    settings.AUTOFIX_SUPERADMIN_URL = AUTOFIX_SUPERADMIN_URL
    stub = Stub()
    stub.answer = autofix_payload()

    def route(url, token, timeout=client.TIMEOUT_SECONDS):
        return (stub if url == AUTOFIX_STATUS_URL else askbridge)(url, token, timeout)

    monkeypatch.setattr(client, "fetch_status_json", route)
    return stub


@pytest.fixture
def autofix_operator(make_user):
    from apps.accounts.roles import VIEWER

    user = make_user(VIEWER, email="autofix-operator@example.test")
    grant(user, "view_product_pipeline", "open_autofix_superadmin")
    return user


def test_autofix_payload_parses_with_its_extra_tenant_keys():
    snapshot = status.parse_status(autofix_payload(), get_product("autofix"))
    assert snapshot.product == "autofix" and snapshot.status == "operational"
    assert snapshot.tenants == {"total": 12, "active": 7, "trial": 3, "suspended": 1}
    assert snapshot.subscriptions == {"active": 6, "trialing": 3, "pastDue": 1}
    assert snapshot.superadmin_url == AUTOFIX_SUPERADMIN_URL


def test_autofix_degraded_with_an_alert_on_its_own_superadmin():
    answer = autofix_payload(
        status="degraded",
        alerts=[alert(title="2 Pitline jobs failed", url=AUTOFIX_SUPERADMIN_URL + "jobs/")],
    )
    snapshot = status.parse_status(answer, get_product("autofix"))
    assert (
        snapshot.status == "degraded" and snapshot.critical_alerts[0].url == AUTOFIX_SUPERADMIN_URL + "jobs/"
    )
    # A link to another product's host is refused.
    with pytest.raises(status.InvalidStatus):
        status.parse_status(autofix_payload(alerts=[alert()]), get_product("autofix"))


def test_autofix_defaults_point_at_pitline():
    from config.settings import base

    assert base.AUTOFIX_STATUS_URL == "https://pitline.co.uk/superadmin/api/platform/v1/status"
    assert base.AUTOFIX_SUPERADMIN_URL == "https://pitline.co.uk/superadmin/"


@pytest.mark.django_db
def test_migration_0004_renames_the_existing_autofix_permission():
    from importlib import import_module

    from django.apps import apps

    migration = import_module("apps.products.migrations.0004_product_pipeline_pitline_name")
    permission = Permission.objects.get(
        content_type__app_label="products", codename="open_autofix_superadmin"
    )
    permission.name = migration.OLD_NAME
    permission.save()
    migration.rename(migration.NEW_NAME)(apps, None)
    permission.refresh_from_db()
    assert permission.name == "Can see Pitline details and open the Pitline Superadmin"


def test_autofix_not_configured_makes_no_request(client_for, superadmin, askbridge, seeded):
    detail = page(client_for, superadmin, "/products/autofix/")
    assert "Status not configured" in detail and 'data-testid="product-counts"' not in detail
    assert all(call["url"] == STATUS_URL for call in askbridge.calls)


def test_autofix_card_shows_live_status(client_for, autofix_operator, autofix, seeded):
    detail = page(client_for, autofix_operator, "/products/autofix/")
    assert 'data-state="ok:operational"' in detail
    assert re.search(r'data-testid="tenants-total">12<', detail)
    assert "7 active · 3 on trial · 1 suspended" in detail
    assert re.search(r'data-testid="subscriptions-active">6<', detail) and "3 trialing · 1 past due" in detail
    assert 'action="/products/autofix/open/"' in detail
    assert autofix.calls == [{"url": AUTOFIX_STATUS_URL, "token": AUTOFIX_TOKEN, "timeout": 3.0}]


def test_autofix_open_redirects_to_its_superadmin_with_audit(client_for, autofix_operator, autofix, seeded):
    response = client_for(autofix_operator).post("/products/autofix/open/")
    assert response.status_code == 302 and response["Location"] == AUTOFIX_SUPERADMIN_URL
    event = AuditEvent.objects.get(action="products.superadmin_opened")
    assert event.entity_id == "autofix" and event.summary == "Opened the Pitline Superadmin"
    assert AUTOFIX_TOKEN not in json.dumps(event.metadata)


def test_autofix_open_needs_its_own_permission(client_for, askbridge_operator, autofix, seeded):
    assert client_for(askbridge_operator).post("/products/autofix/open/").status_code == 403
    detail = page(client_for, askbridge_operator, "/products/autofix/")
    assert 'data-testid="no-open-permission"' in detail and 'data-testid="product-counts"' not in detail
    grant(askbridge_operator, "open_autofix_superadmin")
    operator = type(askbridge_operator).objects.get(pk=askbridge_operator.pk)
    assert client_for(operator).post("/products/autofix/open/").status_code == 302
    out = io.StringIO()
    call_command("product_access", "--email", operator.email, stdout=out)
    assert "open_autofix_superadmin" in out.getvalue()


@pytest.mark.parametrize(
    "answer",
    [autofix_payload(), client.StatusFetchError("http_503"), ["bad"]],
    ids=["ok", "unavailable", "bad"],
)
def test_autofix_token_is_never_rendered(client_for, superadmin, autofix, seeded, answer):
    autofix.answer = answer
    for path in ("/products/", "/products/autofix/", "/"):
        body = page(client_for, superadmin, path)
        assert AUTOFIX_TOKEN not in body and "Bearer" not in body and AUTOFIX_STATUS_URL not in body


# --- Relay, the social media publishing product (ADR-044 addendum) ------------------------------------------

RELAY_TOKEN = "relay-product-status-token-DO-NOT-RENDER-1357924680"
RELAY_STATUS_URL = "https://relay.example.test/api/platform/v1/status"
RELAY_SUPERADMIN_URL = "https://relay.example.test/admin/platform"


def relay_payload(**overrides):
    """What Relay will serve: tenants are workspaces, subscriptions are Relay subscriptions."""
    body = payload(
        product="relay",
        tenants={"total": 20, "active": 14, "trial": 5, "suspended": 1},
        subscriptions={"active": 11, "trialing": 5, "pastDue": 0},
        superadminUrl=RELAY_SUPERADMIN_URL,
    )
    body.update(overrides)
    return body


@pytest.fixture
def relay(askbridge, settings, monkeypatch):
    """Relay configured; its answers come from ``relay.answer``, Askbridge's from the Askbridge stub."""
    settings.RELAY_PRODUCT_STATUS_URL = RELAY_STATUS_URL
    settings.RELAY_PRODUCT_STATUS_TOKEN = RELAY_TOKEN
    settings.RELAY_PRODUCT_SUPERADMIN_URL = RELAY_SUPERADMIN_URL
    stub = Stub()
    stub.answer = relay_payload()

    def route(url, token, timeout=client.TIMEOUT_SECONDS):
        return (stub if url == RELAY_STATUS_URL else askbridge)(url, token, timeout)

    monkeypatch.setattr(client, "fetch_status_json", route)
    return stub


@pytest.fixture
def relay_operator(make_user):
    from apps.accounts.roles import VIEWER

    user = make_user(VIEWER, email="relay-operator@example.test")
    grant(user, "view_product_pipeline", "open_relay_superadmin")
    return user


def test_relay_is_registered_with_its_own_settings():
    relay = get_product("relay")
    assert relay.name == "Relay" and relay.endorsement == "by Vitalos"
    assert relay.summary == "Social media publishing, inbox and AI assistant for teams."
    assert relay.mark == "products/relay-mark.svg" and relay.app_icon == "products/relay-app-icon.svg"
    assert relay.open_permission == "products.open_relay_superadmin"
    # RELAY_PRODUCT_*, never the legacy site assistant's RELAY_* settings.
    assert (relay.status_url_setting, relay.status_token_setting, relay.superadmin_url_setting) == (
        "RELAY_PRODUCT_STATUS_URL",
        "RELAY_PRODUCT_STATUS_TOKEN",
        "RELAY_PRODUCT_SUPERADMIN_URL",
    )


def test_relay_defaults_point_at_relay_with_no_token():
    from config.settings import base

    assert base.RELAY_PRODUCT_STATUS_URL == "https://relay.vitalos.co.uk/api/platform/v1/status"
    assert base.RELAY_PRODUCT_SUPERADMIN_URL == "https://relay.vitalos.co.uk/admin/platform"


def test_relay_payload_parses():
    snapshot = status.parse_status(relay_payload(), get_product("relay"))
    assert snapshot.product == "relay" and snapshot.status == "operational"
    assert snapshot.tenants == {"total": 20, "active": 14, "trial": 5, "suspended": 1}
    assert snapshot.subscriptions == {"active": 11, "trialing": 5, "pastDue": 0}
    with pytest.raises(status.InvalidStatus):
        status.parse_status(relay_payload(product="askbridge"), get_product("relay"))


def test_relay_card_lists_it_and_shows_status_not_configured_without_a_token(
    client_for, superadmin, askbridge, seeded
):
    index = page(client_for, superadmin)
    assert 'data-product="relay"' in index and "products/relay-app-icon" in index
    assert "Social media publishing, inbox and AI assistant for teams." in index
    detail = page(client_for, superadmin, "/products/relay/")
    assert "Status not configured" in detail and 'data-testid="product-counts"' not in detail
    assert "products/relay-mark" in detail
    assert all(call["url"] == STATUS_URL for call in askbridge.calls)


def test_relay_card_shows_live_status(client_for, relay_operator, relay, seeded):
    detail = page(client_for, relay_operator, "/products/relay/")
    assert 'data-state="ok:operational"' in detail
    assert re.search(r'data-testid="tenants-total">20<', detail)
    assert re.search(r'data-testid="subscriptions-active">11<', detail)
    assert 'action="/products/relay/open/"' in detail
    assert relay.calls == [{"url": RELAY_STATUS_URL, "token": RELAY_TOKEN, "timeout": 3.0}]


def test_relay_open_redirects_to_its_superadmin_with_audit(client_for, relay_operator, relay, seeded):
    response = client_for(relay_operator).post("/products/relay/open/")
    assert response.status_code == 302 and response["Location"] == RELAY_SUPERADMIN_URL
    event = AuditEvent.objects.get(action="products.superadmin_opened")
    assert event.entity_id == "relay" and event.summary == "Opened the Relay Superadmin"
    assert RELAY_TOKEN not in json.dumps(event.metadata)


def test_relay_open_needs_its_own_permission(client_for, askbridge_operator, relay, seeded):
    assert client_for(askbridge_operator).post("/products/relay/open/").status_code == 403
    grant(askbridge_operator, "open_relay_superadmin")
    operator = type(askbridge_operator).objects.get(pk=askbridge_operator.pk)
    assert client_for(operator).post("/products/relay/open/").status_code == 302


@pytest.mark.parametrize(
    "answer",
    [relay_payload(), client.StatusFetchError("http_503"), ["bad"]],
    ids=["ok", "unavailable", "bad"],
)
def test_relay_token_is_never_rendered(client_for, superadmin, relay, seeded, answer):
    relay.answer = answer
    for path in ("/products/", "/products/relay/", "/"):
        body = page(client_for, superadmin, path)
        assert RELAY_TOKEN not in body and "Bearer" not in body and RELAY_STATUS_URL not in body


# --- product_access command ---------------------------------------------------------------------------


def test_product_access_command_grants_and_revokes_with_audit(viewer, askbridge, seeded):
    out = io.StringIO()
    call_command(
        "product_access", "--email", "VIEWER@example.test", "--grant", "open_askbridge_superadmin", stdout=out
    )
    assert "holds: open_askbridge_superadmin, view_product_pipeline" in out.getvalue()
    viewer.refresh_from_db()
    viewer = type(viewer).objects.get(pk=viewer.pk)
    assert viewer.has_perm("products.open_askbridge_superadmin") and viewer.has_perm(
        "products.view_product_pipeline"
    )
    assert AuditEvent.objects.filter(action="products.access_granted").count() == 2
    call_command(
        "product_access", "--email", viewer.email, "--revoke", "open_askbridge_superadmin", stdout=out
    )
    viewer = type(viewer).objects.get(pk=viewer.pk)
    assert not viewer.has_perm("products.open_askbridge_superadmin")
    assert viewer.has_perm("products.view_product_pipeline")
    assert AuditEvent.objects.filter(action="products.access_revoked").count() == 1


def test_product_access_command_refuses_unknown_users_and_permissions(viewer, seeded):
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("product_access", "--email", "nobody@example.test")
    with pytest.raises(CommandError):
        call_command("product_access", "--email", viewer.email, "--grant", "delete_everything")


# --- HTTP adapter against a local server ------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    routes: dict = {}
    seen: list = []

    def do_GET(self):  # noqa: N802 - http.server API
        self.seen.append({"path": self.path, "authorization": self.headers.get("Authorization")})
        status_code, headers, body = self.routes[self.path]
        if callable(body):
            body = body()
        self.send_response(status_code)
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass  # the client hangs up early on purpose (oversize and timeout tests)


@pytest.fixture
def server(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    _Handler.routes, _Handler.seen = {}, []
    httpd = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", _Handler
    httpd.shutdown()
    httpd.server_close()


JSON = {"Content-Type": "application/json; charset=utf-8"}


def test_adapter_sends_the_bearer_token_and_decodes_json(server):
    base, handler = server
    handler.routes["/status"] = (200, JSON, b'{"product": "askbridge"}')
    assert client.fetch_status_json(base + "/status", TOKEN) == {"product": "askbridge"}
    assert handler.seen == [{"path": "/status", "authorization": f"Bearer {TOKEN}"}]


def test_adapter_never_follows_redirects(server):
    base, handler = server
    handler.routes["/status"] = (302, {"Location": base + "/elsewhere"}, b"")
    handler.routes["/elsewhere"] = (200, JSON, b"{}")
    with pytest.raises(client.StatusFetchError) as error:
        client.fetch_status_json(base + "/status", TOKEN)
    assert error.value.code == "http_302"
    assert [seen["path"] for seen in handler.seen] == ["/status"]


@pytest.mark.parametrize(
    ("route", "code"),
    [
        ((401, JSON, b'{"error": "unauthorised"}'), "http_401"),
        ((200, {"Content-Type": "text/html"}, b"<html>"), "not_json"),
        ((200, JSON, b"{not json"), "bad_json"),
        ((200, JSON, b'{"x": "' + b"a" * (client.MAX_RESPONSE_BYTES + 10) + b'"}'), "too_large"),
    ],
)
def test_adapter_failures(server, route, code):
    base, handler = server
    handler.routes["/status"] = route
    with pytest.raises(client.StatusFetchError) as error:
        client.fetch_status_json(base + "/status", TOKEN)
    assert error.value.code == code


def test_adapter_times_out(server):
    base, handler = server
    release = threading.Event()

    def slow():
        release.wait(5)
        return b"{}"

    handler.routes["/status"] = (200, JSON, slow)
    try:
        with pytest.raises(client.StatusFetchError) as error:
            client.fetch_status_json(base + "/status", TOKEN, timeout=0.3)
    finally:
        release.set()
    assert error.value.code == "timeout"


def test_adapter_refuses_other_schemes():
    with pytest.raises(client.StatusFetchError) as error:
        client.fetch_status_json("file:///etc/passwd", TOKEN)
    assert error.value.code == "bad_url"
