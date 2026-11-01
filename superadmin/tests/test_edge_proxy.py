"""The Cloudflare edge Worker in front of Cloud Run (EdgeProxyMiddleware): the forwarded host and client IP are
trusted only alongside the edge secret, and only for an allowed host."""

import secrets

import pytest
from django.core.exceptions import DisallowedHost
from django.test import Client, RequestFactory

from apps.core.http import client_ip
from apps.core.middleware import EdgeProxyMiddleware

RUN_APP = "vitalos-superadmin-123.europe-west2.run.app"
ADMIN = "admin.example.test"
PORTAL = "portal.example.test"
SECRET = secrets.token_urlsafe(32)


@pytest.fixture
def edge(settings):
    settings.EDGE_PROXY_SECRET = SECRET
    settings.ALLOWED_HOSTS = [ADMIN, PORTAL]
    settings.TRUSTED_PROXY_COUNT = 1
    return settings


def via_edge(secret=SECRET, host=ADMIN, **extra):
    headers = {"HTTP_HOST": RUN_APP, "HTTP_X_FORWARDED_HOST": host, **extra}
    if secret is not None:
        headers["HTTP_X_VITALOS_EDGE_SECRET"] = secret
    return headers


def through_middleware(request):
    seen = {}

    def view(req):
        try:
            seen["host"] = req.get_host()
        except DisallowedHost:
            seen["host"] = None
        seen["ip"] = client_ip(req)
        seen["meta"] = dict(req.META)
        return None

    EdgeProxyMiddleware(view)(request)
    return seen


@pytest.mark.django_db
def test_edge_request_is_served_as_the_public_host(edge):
    response = Client().get("/login/", **via_edge())
    assert response.status_code == 200


@pytest.mark.django_db
def test_run_app_host_without_the_edge_is_still_refused(edge):
    assert Client().get("/login/", HTTP_HOST=RUN_APP).status_code == 400
    assert Client().get("/login/", HTTP_HOST=RUN_APP, HTTP_X_FORWARDED_HOST=ADMIN).status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("secret", ["", "wrong", SECRET[:-1], SECRET + "x"])
def test_wrong_or_missing_secret_changes_nothing(edge, secret):
    assert Client().get("/login/", **via_edge(secret=secret)).status_code == 400


@pytest.mark.django_db
def test_no_configured_secret_never_trusts_the_header(edge):
    edge.EDGE_PROXY_SECRET = ""
    assert Client().get("/login/", **via_edge(secret="")).status_code == 400
    assert Client().get("/login/", **via_edge()).status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("host", ["evil.example.test", f"{ADMIN}:8443", "", f"{ADMIN}@evil.example.test"])
def test_forwarded_host_outside_allowed_hosts_is_ignored(edge, host):
    assert Client().get("/login/", **via_edge(host=host)).status_code == 400


def test_first_forwarded_host_is_used_and_lowercased(edge):
    seen = through_middleware(
        RequestFactory().get("/", **via_edge(host=f"{ADMIN.upper()}, evil.example.test"))
    )
    assert seen["host"] == ADMIN


@pytest.mark.django_db
def test_portal_routing_follows_the_forwarded_host(edge):
    edge.PORTAL_HOST = PORTAL
    portal = Client()
    assert portal.get("/sign-in/", **via_edge(host=PORTAL)).status_code == 200
    assert portal.get("/login/", **via_edge(host=PORTAL)).status_code == 404
    admin = Client()
    assert admin.get("/login/", **via_edge(host=ADMIN)).status_code == 200
    assert admin.get("/sign-in/", **via_edge(host=ADMIN)).status_code == 404


def test_secret_is_removed_from_the_request(edge):
    for headers in (via_edge(), via_edge(secret="wrong")):
        seen = through_middleware(RequestFactory().get("/", **headers))
        assert "HTTP_X_VITALOS_EDGE_SECRET" not in seen["meta"]


def test_client_ip_comes_from_cloudflare_only_through_the_edge(edge):
    # Cloud Run's front end appends Cloudflare's egress address; CF-Connecting-IP holds the visitor.
    forwarded = {"HTTP_X_FORWARDED_FOR": "198.51.100.7, 104.28.0.9", "HTTP_CF_CONNECTING_IP": "198.51.100.7"}
    assert through_middleware(RequestFactory().get("/", **via_edge(**forwarded)))["ip"] == "198.51.100.7"
    # Without the secret a forged CF-Connecting-IP is ignored and the last hop is used, as before.
    forged = {"HTTP_X_FORWARDED_FOR": "203.0.113.5", "HTTP_CF_CONNECTING_IP": "192.0.2.1"}
    assert (
        through_middleware(RequestFactory().get("/", **via_edge(secret=None, **forged)))["ip"]
        == "203.0.113.5"
    )
    # A malformed value falls back to the normal rule.
    bad = {"HTTP_X_FORWARDED_FOR": "104.28.0.9", "HTTP_CF_CONNECTING_IP": "not-an-ip"}
    assert through_middleware(RequestFactory().get("/", **via_edge(**bad)))["ip"] == "104.28.0.9"
