"""Security review fixes on the content side: strict signature headers, read-rate isolation and the
production settings checks."""

import sys
import time
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from apps.content_sync import api, signing
from config import content_validation

from .content_helpers import configure, open_site, signed_get
from .test_security import _check_prod

pytestmark = pytest.mark.django_db
PATH = "/api/content/v1/health"
GOOD_SECRET = "s" * 32


@pytest.fixture(autouse=True)
def _keys(settings):
    configure(settings, targets=())
    cache.clear()
    yield
    cache.clear()


def _headers(**overrides):
    headers = signing.sign_headers("read", "GET", PATH)
    headers.update(overrides)
    return {f"HTTP_{name.upper().replace('-', '_')}": value for name, value in headers.items()}


@pytest.mark.parametrize(
    "overrides",
    [
        {"X-Vitalos-Timestamp": "²³⁴"},
        {"X-Vitalos-Timestamp": "١٧٦٠٠٠٠٠٠٠"},  # Arabic-Indic digits pass str.isdigit()
        {"X-Vitalos-Timestamp": "1" * 13},
        {"X-Vitalos-Key-Id": "ré-1"},
        {"X-Vitalos-Key-Id": "READ-1"},
        {"X-Vitalos-Signature": "v1=" + "é" * 64},
        {"X-Vitalos-Signature": "v1=" + "A" * 64},
        {"X-Vitalos-Signature": "v2=" + "0" * 64},
        {"X-Vitalos-Signature": "v1=" + "0" * 63},
    ],
)
def test_malformed_signature_headers_are_401_not_500(client: Client, overrides):
    response = client.get(PATH, **_headers(**overrides))
    assert response.status_code == 401


def test_malformed_values_are_refused_without_raising_type_errors():
    for kwargs in (
        {"key_id": "read-1", "timestamp": "²", "signature_header": "v1=" + "0" * 64},
        {"key_id": "rëad", "timestamp": str(int(time.time())), "signature_header": "v1=" + "0" * 64},
        {"key_id": "read-1", "timestamp": str(int(time.time())), "signature_header": "v1=" + "ö" * 64},
    ):
        with pytest.raises(signing.InvalidSignature):
            signing.verify("read", method="GET", path=PATH, body=b"", **kwargs)


def test_non_ascii_preview_tokens_are_refused():
    with pytest.raises(signing.InvalidSignature):
        signing.verify_preview_token("ÿÿÿ.ÿÿÿ", "post", "00000000-0000-4000-8000-000000000101")


def test_slug_misses_do_not_use_up_the_read_limit(client: Client, settings, monkeypatch):
    # The read limits count per wall-clock minute; hold the clock still so the 37 calls below can't
    # straddle a minute boundary and reset the buckets halfway through.
    frozen = timezone.now()
    monkeypatch.setattr(api, "timezone", SimpleNamespace(now=lambda: frozen))
    open_site()
    settings.CONTENT_READ_RATE_LIMIT = 3
    for index in range(15):
        assert (
            signed_get(client, f"/api/content/v1/insights/posts/example-missing-{index}").status_code == 404
        )
        assert signed_get(client, f"/api/content/v1/careers/roles/example-missing-{index}").status_code == 404
    assert signed_get(client, PATH).status_code == 200  # real reads still answer
    # Misses have their own, ten times larger bucket.
    statuses = [signed_get(client, f"/api/content/v1/insights/posts/x-{i}").status_code for i in range(5)]
    assert statuses == [429] * 5  # 30 misses already counted: the miss bucket (10 x 3) is full
    assert signed_get(client, PATH).status_code == 200
    assert signed_get(client, PATH).status_code == 200
    assert signed_get(client, PATH).status_code == 429  # ordinary reads keep the ordinary limit


# --- Production settings -------------------------------------------------------------------------


def test_content_settings_validation():
    assert content_validation.problems({}) == []
    ok = {
        "CONTENT_READ_CLIENT_KEYS": f"read-1:{GOOD_SECRET},read-0:{GOOD_SECRET}",
        "CAREERS_SUBMIT_CLIENT_KEYS": f"submit-1:{GOOD_SECRET}",
        "CONTENT_IP_SALT": GOOD_SECRET,
        "CONTENT_WEB_TARGETS": ["https://www.vitalos.co.uk"],
    }
    assert content_validation.problems(ok) == []
    found = content_validation.problems({"CONTENT_RENDER_SECRET": "render-1:short"})
    assert found and "render-1" in found[0] and "short" not in found[0]
    assert content_validation.problems({"CONTENT_PREVIEW_SECRET": f"Bad_Id:{GOOD_SECRET}"})
    assert content_validation.problems({"CONTENT_REVALIDATE_SECRET": GOOD_SECRET})  # no key id
    assert content_validation.problems({"CONTENT_WEB_TARGETS": ["http://web.example.test"]})
    assert content_validation.problems({"CAREERS_SUBMIT_CLIENT_KEYS": f"submit-1:{GOOD_SECRET}"})  # no salt
    assert content_validation.problems({**ok, "CONTENT_IP_SALT": "short"})


WINDOWS = pytest.mark.skipif(
    sys.platform == "win32", reason="the prod-settings subprocess needs a POSIX PATH (runs in CI on Linux)"
)


@WINDOWS
def test_production_refuses_weak_content_keys():
    result = _check_prod("import django;django.setup()", CONTENT_READ_CLIENT_KEYS="read-1:short")
    assert result.returncode != 0 and "CONTENT_READ_CLIENT_KEYS" in result.stderr


@WINDOWS
def test_production_refuses_plain_http_website_targets():
    result = _check_prod("import django;django.setup()", CONTENT_WEB_TARGETS="http://web.example.test")
    assert result.returncode != 0 and "CONTENT_WEB_TARGETS" in result.stderr
