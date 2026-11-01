"""Push notifications for the installable client portal (ADR-056, Phase 2).

Crypto is checked against the published RFC 8291 Appendix A example and by decrypting our own output with a
receiver key made here; VAPID tokens are verified with the derived public key. Delivery runs against a faked
transport or a fake push server on 127.0.0.1: nothing in this module (or any test, see conftest) reaches a real
push service. Every key below is generated inside the test that uses it, apart from the RFC's published example.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import re
import secrets
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.core.checks import run_checks
from django.test import Client
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.portal import notifications, push, pwa, services
from apps.portal.models import (
    Notification,
    NotificationPreference,
    PushDelivery,
    PushSubscription,
)
from tests.portal_helpers import build_world, client_for

BASE_DIR = Path(__file__).resolve().parent.parent
REPO = BASE_DIR.parent
ANDROID_CHROME = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 "
    "Mobile Safari/537.36"
)
IPHONE_SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.0 Mobile/15E148 Safari/604.1"
)
PORTAL_HOST = "portal.example.test"

# --- Helpers -----------------------------------------------------------------------------------------------------


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    text = re.sub(r"\s+", "", text)
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def raw_scalar(key) -> str:
    return b64(key.private_numbers().private_value.to_bytes(32, "big"))


def point(key) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def hkdf(salt, ikm, info, length):
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


class Receiver:
    """A browser's side of a subscription: its own key pair and authentication secret (made here, per test)."""

    def __init__(self, endpoint: str):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = secrets.token_bytes(16)
        self.endpoint = endpoint

    def subscription(self) -> dict:
        return {
            "endpoint": self.endpoint,
            "expirationTime": None,
            "keys": {"p256dh": b64(point(self.key)), "auth": b64(self.auth)},
        }

    def decrypt(self, body: bytes) -> bytes:
        return decrypt(body, self.key, self.auth)


def decrypt(body: bytes, receiver_key, auth: bytes) -> bytes:
    """RFC 8291 receiver side, written separately from the sender in push.py."""
    salt, record_size, id_length = body[:16], int.from_bytes(body[16:20], "big"), body[20]
    sender_public = body[21 : 21 + id_length]
    ciphertext = body[21 + id_length :]
    assert record_size == 4096 and id_length == 65 and len(ciphertext) <= record_size
    sender = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), sender_public)
    ecdh_secret = receiver_key.exchange(ec.ECDH(), sender)
    ikm = hkdf(auth, ecdh_secret, b"WebPush: info\x00" + point(receiver_key) + sender_public, 32)
    cek = hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    plain = AESGCM(cek).decrypt(nonce, ciphertext, None).rstrip(b"\x00")
    assert plain.endswith(b"\x02"), "last-record delimiter"
    return plain[:-1]


def parse_vapid(header: str) -> tuple[str, str]:
    match = re.fullmatch(r"vapid t=([A-Za-z0-9_\-\.]+), k=([A-Za-z0-9_\-]+)", header)
    assert match, header
    return match.group(1), match.group(2)


def verify_jwt(token: str, public_b64: str) -> tuple[dict, dict]:
    head, claims, signature = token.split(".")
    raw = unb64(signature)
    assert len(raw) == 64
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(public_b64))
    public.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))  # raises if invalid
    return json.loads(unb64(head)), json.loads(unb64(claims))


class FakeTransport:
    """Stands in for push._send_http: records each request and answers with queued statuses (default 201)."""

    def __init__(self):
        self.calls: list[dict] = []
        self.statuses: list = []

    def __call__(self, endpoint, body, headers, timeout):
        self.calls.append({"endpoint": endpoint, "body": body, "headers": dict(headers), "timeout": timeout})
        answer = self.statuses.pop(0) if self.statuses else 201
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, tuple):
            return push.HttpResult(*answer)
        return push.HttpResult(answer)


class FakePushServer:
    """A push service on 127.0.0.1 (allowed through PORTAL_PUSH_DEV_ORIGINS for the test only)."""

    def __init__(self):
        self.requests: list[dict] = []
        self.responses: list[tuple[int, dict]] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - http.server API
                length = int(self.headers.get("Content-Length") or 0)
                server.requests.append(
                    {"path": self.path, "headers": dict(self.headers), "body": self.rfile.read(length)}
                )
                status, extra = server.responses.pop(0) if server.responses else (201, {})
                self.send_response(status)
                for name, value in extra.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.origin = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


# --- Fixtures ----------------------------------------------------------------------------------------------------


@pytest.fixture
def world(db, mailoutbox):
    built = build_world()
    mailoutbox.clear()
    return built


@pytest.fixture
def vapid(settings):
    """Push switched on with a key generated for this test only."""
    key = ec.generate_private_key(ec.SECP256R1())
    settings.PORTAL_PUSH_VAPID_PRIVATE_KEY = raw_scalar(key)
    return key


@pytest.fixture
def transport(monkeypatch):
    fake = FakeTransport()
    monkeypatch.setattr(push, "_send_http", fake)
    return fake


@pytest.fixture
def push_server(settings):
    server = FakePushServer()
    settings.PORTAL_PUSH_DEV_ORIGINS = [server.origin]
    yield server
    server.close()


def fcm(name: str = "") -> str:
    return f"https://fcm.googleapis.com/fcm/send/{name or secrets.token_urlsafe(24)}"


def add_device(member, endpoint=None, user_agent=ANDROID_CHROME) -> tuple[PushSubscription, Receiver]:
    receiver = Receiver(endpoint or fcm())
    sub, _ = push.subscribe(member, push.parse_subscription(receiver.subscription()), user_agent=user_agent)
    return sub, receiver


def post_json(client, url, data, **extra):
    return client.post(url, data=json.dumps(data), content_type="application/json", **extra)


def seed_names(world) -> list[str]:
    names = [
        world.org_a.name,
        world.org_b.name,
        "Northwind",
        "Contoso",
        world.ch_a.title,
        world.project_a.name,
        world.deliv_a.title,
        world.q_a.question,
        world.upd_a.title,
        world.ms2.title,
    ]
    for member in (world.viewer, world.contrib, world.approver, world.signatory, world.b_approver):
        names += [member.user.email, member.user.full_name]
    return [n for n in names if n]


# --- Crypto: RFC 8291 Appendix A, round trip, VAPID ----------------------------------------------------------------

RFC = {
    "plaintext": b"When I grow up, I want to be a watermelon",
    "as_private": "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw",
    "as_public": "BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8",
    "ua_private": "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94",
    "ua_public": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
    "salt": "DGv6ra1nlYgDCS1FRnbzlw",
    "auth_secret": "BTBZMqHH6r4Tts7J_aSIgg",
    "message": (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
        "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT"
        "pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
    ),
}


def test_rfc8291_appendix_a_vector_matches_byte_for_byte():
    sender = ec.derive_private_key(int.from_bytes(unb64(RFC["as_private"]), "big"), ec.SECP256R1())
    assert point(sender) == unb64(RFC["as_public"])
    body = push._encrypt(
        RFC["plaintext"], unb64(RFC["ua_public"]), unb64(RFC["auth_secret"]), sender, unb64(RFC["salt"])
    )
    assert body == unb64(RFC["message"])
    assert len(body) == 144  # 86-octet header + 41 + delimiter + 16-octet tag
    # The receiver side used by the other tests reads the RFC's message back with the RFC's receiver key.
    receiver = ec.derive_private_key(int.from_bytes(unb64(RFC["ua_private"]), "big"), ec.SECP256R1())
    assert decrypt(body, receiver, unb64(RFC["auth_secret"])) == RFC["plaintext"]


def test_encryption_round_trip_and_fresh_key_and_salt_per_message():
    receiver = Receiver(fcm())
    payload = json.dumps(push.message_for("question", "/portal/notifications/1/open/")).encode()
    first = push.encrypt(payload, point(receiver.key), receiver.auth)
    second = push.encrypt(payload, point(receiver.key), receiver.auth)
    assert receiver.decrypt(first) == receiver.decrypt(second) == payload
    assert first[:16] != second[:16] and first[21:86] != second[21:86]  # new salt and sender key every time
    with pytest.raises(ValueError):
        push.encrypt(b"x" * (push.MAX_PAYLOAD_BYTES + 1), point(receiver.key), receiver.auth)


def test_vapid_jwt_verifies_with_the_derived_public_key(vapid):
    now = 1_800_000_000
    header = push.vapid_authorization(fcm("abc"), now=now)
    token, k = parse_vapid(header)
    assert k == push.public_key() == b64(point(vapid))
    assert len(unb64(k)) == 65 and unb64(k)[0] == 4
    head, claims = verify_jwt(token, k)
    assert head == {"typ": "JWT", "alg": "ES256"}
    assert claims["aud"] == "https://fcm.googleapis.com"
    assert now < claims["exp"] <= now + 24 * 3600
    assert claims["sub"] == "mailto:support@vitalos.co.uk"
    # The audience is the endpoint's origin, whatever the path.
    _, apple = verify_jwt(
        parse_vapid(push.vapid_authorization("https://web.push.apple.com/QGx", now=now))[0], k
    )
    assert apple["aud"] == "https://web.push.apple.com"


def test_key_setting_format_and_system_check(settings):
    settings.PORTAL_PUSH_VAPID_PRIVATE_KEY = ""
    assert not push.enabled() and push.public_key() == "" and push.key_id() == ""
    assert not [m for m in run_checks() if m.id == "portal.W001"]
    for bad in (
        "not-a-key",
        "A" * 43,  # the zero scalar is not a private key
        "_" * 43,  # larger than the curve order
        "a" * 44,
        "-----BEGIN EC PARAMETERS-----",  # PEM is not the accepted format
    ):
        settings.PORTAL_PUSH_VAPID_PRIVATE_KEY = bad
        assert not push.enabled(), bad
        warnings = [m for m in run_checks() if m.id == "portal.W001"]
        assert warnings and bad not in warnings[0].msg
    key = ec.generate_private_key(ec.SECP256R1())
    settings.PORTAL_PUSH_VAPID_PRIVATE_KEY = raw_scalar(key)
    assert push.enabled() and push.public_key() == b64(point(key))
    assert re.fullmatch(r"[0-9a-f]{16}", push.key_id())


def test_every_kind_has_a_generic_message():
    kinds = {value for value, _ in Notification.Kind.choices} | {push.TEST_KIND}
    assert kinds <= set(push.MESSAGES)
    for title, body in push.MESSAGES.values():
        assert title == "Vitalos" and body.endswith(".") and len(body) < 80


# --- SSRF: the endpoint allowlist ----------------------------------------------------------------------------------

ALLOWED = (
    "https://fcm.googleapis.com/fcm/send/dGVzdA:APA91b",
    "https://fcm.googleapis.com:443/wp/abc",
    "https://updates.push.services.mozilla.com/wpush/v2/gAAAAAB",
    "https://push.services.mozilla.com/wpush/v1/abc",
    "https://web.push.apple.com/QGx3",
    "https://api.push.apple.com/3/device/abc",
    "https://wns2-par02p.notify.windows.com/w/?token=BQYAAAB",
)
REFUSED = (
    "http://fcm.googleapis.com/fcm/send/abc",  # not https
    "https://127.0.0.1/push",  # IP literal
    "https://[::1]/push",
    "https://10.0.0.5/push",
    "https://169.254.169.254/latest/meta-data/",
    "https://localhost/push",
    "https://example.com/push",  # not a push service
    "https://storage.googleapis.com/bucket/x",  # *.googleapis.com is not needed, so not allowed
    "https://fcm.googleapis.com.evil.example/x",
    "https://notify.windows.com/x",  # the suffix needs a subdomain
    "https://evilpush.apple.com/x",
    "https://user:secret@fcm.googleapis.com/fcm/send/abc",  # credentials
    "https://fcm.googleapis.com@evil.example/x",
    "https://fcm.googleapis.com:8443/fcm/send/abc",  # non-default port
    "https://fcm.googleapis.com/fcm/send/abc#frag",
    "https://fcm.googleapis.com/fcm/send/a b",
    "https://fcm.googleapis.com/" + "a" * 2048,
    "",
    "javascript:alert(1)",
)


@pytest.mark.parametrize("endpoint", ALLOWED)
def test_real_push_services_are_allowed(endpoint, settings):
    settings.PORTAL_PUSH_DEV_ORIGINS = []
    assert push.endpoint_problem(endpoint) == ""


@pytest.mark.parametrize("endpoint", REFUSED)
def test_endpoints_outside_the_allowlist_are_refused(endpoint, settings):
    settings.PORTAL_PUSH_DEV_ORIGINS = []
    assert push.endpoint_problem(endpoint) != ""


def test_dev_origins_allow_exactly_one_local_origin(settings):
    settings.PORTAL_PUSH_DEV_ORIGINS = ["http://127.0.0.1:8765"]
    assert push.endpoint_problem("http://127.0.0.1:8765/push/abc") == ""
    assert push.endpoint_problem("http://127.0.0.1:8766/push/abc") != ""
    assert push.endpoint_problem("http://localhost:8765/push/abc") != ""
    assert push.endpoint_problem("http://user:pw@127.0.0.1:8765/push/abc") != ""


def test_subscribe_refuses_endpoints_outside_the_allowlist(world, vapid, settings):
    client = client_for(world.approver.user)
    for endpoint in REFUSED:
        receiver = Receiver(endpoint)
        response = post_json(client, "/portal/push/subscribe/", receiver.subscription())
        assert response.status_code == 400, endpoint
        assert response.json()["message"] == "This browser's push service isn't supported."
    assert not PushSubscription.objects.exists()


def test_subscribe_refuses_malformed_keys(world, vapid):
    client = client_for(world.approver.user)
    good = Receiver(fcm()).subscription()
    for keys in (
        {},
        {"p256dh": good["keys"]["p256dh"]},
        {"p256dh": good["keys"]["p256dh"], "auth": b64(b"short")},
        {"p256dh": b64(b"\x04" + b"\x00" * 64), "auth": good["keys"]["auth"]},  # not on the curve
        {"p256dh": good["keys"]["p256dh"][:-4], "auth": good["keys"]["auth"]},
        {"p256dh": "not base64!", "auth": good["keys"]["auth"]},
    ):
        response = post_json(client, "/portal/push/subscribe/", {**good, "keys": keys})
        assert response.status_code == 400, keys
    assert post_json(client, "/portal/push/subscribe/", ["not", "an", "object"]).status_code == 400
    response = client.post("/portal/push/subscribe/", data=b"{", content_type="application/json")
    assert response.status_code == 400
    assert not PushSubscription.objects.exists()


def test_the_allowlist_is_checked_again_at_send_time(world, vapid, settings, push_server):
    sub, _ = add_device(world.approver, endpoint=f"{push_server.origin}/push/abc")
    settings.PORTAL_PUSH_DEV_ORIGINS = []  # the endpoint is no longer allowed
    ok, _message = push.send_test(sub)
    assert not ok and push_server.requests == []
    delivery = PushDelivery.objects.get(subscription=sub)
    assert delivery.status == "failed" and delivery.last_error == "blocked_endpoint"
    sub.refresh_from_db()
    assert sub.disabled_at and sub.disabled_reason == "blocked"


def test_redirects_are_never_followed(world, vapid, push_server):
    sub, _ = add_device(world.approver, endpoint=f"{push_server.origin}/push/abc")
    push_server.responses = [(307, {"Location": f"{push_server.origin}/elsewhere"})]
    ok, _ = push.send_test(sub)
    assert not ok
    assert [r["path"] for r in push_server.requests] == [
        "/push/abc"
    ]  # one request; the redirect was not followed
    assert PushDelivery.objects.get(subscription=sub).last_error == "redirect"


# --- Access: auth, CSRF, POST only, own devices only, never in preview -------------------------------------------

PUSH_PATHS = ("push/subscribe/", "push/unsubscribe/", "push/test/")


def test_push_routes_need_a_signed_in_member(world, vapid):
    anonymous = Client()
    for path in PUSH_PATHS:
        response = post_json(anonymous, f"/portal/{path}", Receiver(fcm()).subscription())
        assert response.status_code == 302 and "/portal/sign-in/" in response["Location"], path
    staff = client_for(world.staff)
    assert post_json(staff, "/portal/push/subscribe/", Receiver(fcm()).subscription()).status_code == 403
    assert not PushSubscription.objects.exists()


def test_push_routes_need_csrf(world, vapid):
    client = Client(enforce_csrf_checks=True)
    client.force_login(world.approver.user)
    data = Receiver(fcm()).subscription()
    for path in PUSH_PATHS:
        assert post_json(client, f"/portal/{path}", data).status_code == 403, path
    assert not PushSubscription.objects.exists()
    page = client.get("/portal/account/").content.decode()
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)
    response = post_json(client, "/portal/push/subscribe/", data, HTTP_X_CSRFTOKEN=token)
    assert response.status_code == 201 and response.json()["ok"] is True


def test_push_routes_are_post_only(world, vapid):
    client = client_for(world.approver.user)
    for path in (*PUSH_PATHS, "push/renew/"):
        assert client.get(f"/portal/{path}").status_code == 405, path
        assert Client().get(f"/portal/{path}").status_code in (302, 405), path


def test_subscribe_stores_a_label_never_the_raw_user_agent(world, vapid):
    client = client_for(world.approver.user)
    receiver = Receiver(fcm())
    response = post_json(
        client, "/portal/push/subscribe/", receiver.subscription(), HTTP_USER_AGENT=ANDROID_CHROME
    )
    assert response.status_code == 201 and response.json()["label"] == "Chrome on Android"
    sub = PushSubscription.objects.get()
    assert sub.member == world.approver and sub.endpoint == receiver.endpoint
    assert sub.label == "Chrome on Android" and sub.vapid_key_id == push.key_id()
    assert sub.p256dh == b64(point(receiver.key)) and sub.auth == b64(receiver.auth)
    stored = json.dumps([getattr(sub, f.attname) for f in PushSubscription._meta.fields], default=str)
    assert "Pixel 8" not in stored and "Mozilla/5.0" not in stored
    # Subscribing again from the same browser refreshes the row.
    response = post_json(
        client, "/portal/push/subscribe/", receiver.subscription(), HTTP_USER_AGENT=IPHONE_SAFARI
    )
    assert response.status_code == 200 and PushSubscription.objects.count() == 1
    assert PushSubscription.objects.get().label == "Safari on iPhone"
    assert AuditEvent.objects.filter(action="portal.push_subscribed", actor=world.approver.user).count() == 2


@pytest.mark.parametrize(
    "agent,label",
    [
        (ANDROID_CHROME, "Chrome on Android"),
        (IPHONE_SAFARI, "Safari on iPhone"),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36 Edg/130.0",
            "Edge on Windows",
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:131.0) Gecko/20100101 Firefox/131.0",
            "Firefox on Mac",
        ),
        (
            "Mozilla/5.0 (Linux; Android 14; SM-S921B) AppleWebKit/537.36 SamsungBrowser/26.0 Chrome/122.0 Mobile Safari/537.36",
            "Samsung Internet on Android",
        ),
        ("", "Browser"),
    ],
)
def test_device_labels(agent, label):
    assert push.device_label(agent) == label


def test_a_member_can_only_touch_their_own_devices(world, vapid, transport):
    theirs, _ = add_device(world.contrib)
    other_org, _ = add_device(world.b_approver)
    mine, _ = add_device(world.approver)
    client = client_for(world.approver.user)
    for sub in (theirs, other_org):
        assert client.post("/portal/push/unsubscribe/", {"subscription": sub.pk}).status_code == 404
        assert client.post("/portal/push/test/", {"subscription": sub.pk}).status_code == 404
        assert post_json(client, "/portal/push/unsubscribe/", {"endpoint": sub.endpoint}).status_code == 404
        assert post_json(client, "/portal/push/test/", {"endpoint": sub.endpoint}).status_code == 404
    for value in ("", "x", "999999"):
        assert client.post("/portal/push/unsubscribe/", {"subscription": value}).status_code == 404
    assert PushSubscription.objects.count() == 3 and transport.calls == []
    # The other organisation's member cannot reach this organisation's devices either.
    other = client_for(world.b_approver.user)
    assert other.post("/portal/push/unsubscribe/", {"subscription": mine.pk}).status_code == 404
    assert other.post("/portal/push/test/", {"subscription": mine.pk}).status_code == 404
    # Their own device: removed, and the device list no longer shows it.
    response = client.post("/portal/push/unsubscribe/", {"subscription": mine.pk})
    assert response.status_code == 302 and response["Location"] == "/portal/account/"
    assert not PushSubscription.objects.filter(pk=mine.pk).exists()
    assert set(PushSubscription.objects.values_list("pk", flat=True)) == {theirs.pk, other_org.pk}


def test_staff_preview_and_admin_host_have_no_push_routes(world, vapid, settings):
    add_device(world.approver)
    staff = client_for(world.staff)
    base = f"/client-portal/preview/{world.approver.pk}/as/"
    for path in (*PUSH_PATHS, "push/renew/"):
        assert staff.post(base + path).status_code == 404, path
        assert staff.get(base + path).status_code == 404, path
        with pytest.raises(NoReverseMatch):
            reverse(f"portal_preview:push_{path.split('/')[1]}", kwargs={"preview_member": world.approver.pk})
    page = staff.get(base + "account/").content.decode()
    assert 'data-testid="push-card"' not in page and "data-push" not in page
    # With a portal host the routes exist only there.
    settings.PORTAL_HOST = PORTAL_HOST
    settings.ALLOWED_HOSTS = ["testserver", PORTAL_HOST]
    for path in (*PUSH_PATHS, "push/renew/"):
        assert client_for(world.approver.user).post(f"/portal/{path}").status_code == 404, path
        assert staff.post(f"/{path}").status_code == 404, path
    on_host = client_for(world.approver.user)
    on_host.defaults["HTTP_HOST"] = PORTAL_HOST
    response = post_json(on_host, "/push/subscribe/", Receiver(fcm()).subscription())
    assert response.status_code == 201


def test_a_shared_browser_moves_to_the_person_signed_in(world, vapid):
    sub, receiver = add_device(world.contrib)
    client = client_for(world.approver.user)
    assert post_json(client, "/portal/push/subscribe/", receiver.subscription()).status_code == 201
    moved = PushSubscription.objects.get(endpoint=receiver.endpoint)
    assert moved.member == world.approver and not PushSubscription.objects.filter(pk=sub.pk).exists()


def test_another_persons_endpoint_with_different_keys_cannot_take_the_device(world, vapid):
    # A shared browser presents the same endpoint with the same keys. Someone who has only learnt the endpoint
    # (their own keys) must not be able to move the device to their account.
    sub, receiver = add_device(world.contrib)
    impostor = Receiver(receiver.endpoint).subscription()
    response = post_json(client_for(world.approver.user), "/portal/push/subscribe/", impostor)
    assert response.status_code == 400 and "someone else" in response.json()["message"]
    kept = PushSubscription.objects.get(endpoint=receiver.endpoint)
    assert kept.pk == sub.pk and kept.member == world.contrib and kept.p256dh == sub.p256dh


def test_a_simultaneous_registration_is_a_polite_refusal_not_an_error(world, vapid, monkeypatch):
    from django.db import IntegrityError

    def clash(*args, **kwargs):
        raise IntegrityError("duplicate key value violates unique constraint")

    monkeypatch.setattr(PushSubscription, "save", clash)
    response = post_json(
        client_for(world.approver.user), "/portal/push/subscribe/", Receiver(fcm()).subscription()
    )
    assert response.status_code == 400 and "Reload the page" in response.json()["message"]
    sub_data = push.parse_subscription(Receiver(fcm()).subscription())
    assert push.renew(fcm(), b64(secrets.token_bytes(16)), sub_data) is False


def test_at_most_ten_active_devices(world, vapid):
    subs = []
    for index in range(push.MAX_DEVICES_PER_MEMBER + 2):
        sub, _ = add_device(world.approver)
        # Distinct, increasing times in the past, so each new device is the newest when the cap is applied.
        earlier = timezone.now() - dt.timedelta(minutes=100 - index)
        PushSubscription.objects.filter(pk=sub.pk).update(created_at=earlier)
        subs.append(sub)
    add_device(world.approver)  # the thirteenth device
    active = PushSubscription.objects.filter(member=world.approver, disabled_at__isnull=True)
    assert active.count() == push.MAX_DEVICES_PER_MEMBER
    oldest = PushSubscription.objects.filter(pk__in=[subs[0].pk, subs[1].pk, subs[2].pk])
    assert set(oldest.values_list("disabled_reason", flat=True)) == {"limit"}


def test_test_notifications_are_rate_limited(world, vapid, transport):
    sub, _ = add_device(world.approver)
    client = client_for(world.approver.user)
    for _ in range(push.RATE_LIMITS_PER_HOUR["portal.push_test"]):
        response = post_json(client, "/portal/push/test/", {"endpoint": sub.endpoint})
        assert response.status_code == 200 and response.json()["ok"] is True
    response = post_json(client, "/portal/push/test/", {"endpoint": sub.endpoint})
    assert response.status_code == 429 and "an hour" in response.json()["message"]
    assert len(transport.calls) == push.RATE_LIMITS_PER_HOUR["portal.push_test"]


def test_subscribe_is_rate_limited(world, vapid):
    client = client_for(world.approver.user)
    for _ in range(push.RATE_LIMITS_PER_HOUR["portal.push_subscribed"]):
        assert post_json(client, "/portal/push/subscribe/", Receiver(fcm()).subscription()).status_code == 201
    assert post_json(client, "/portal/push/subscribe/", Receiver(fcm()).subscription()).status_code == 429


def test_test_notification_goes_to_the_members_own_device(world, vapid, transport):
    sub, receiver = add_device(world.approver)
    client = client_for(world.approver.user)
    response = post_json(client, "/portal/push/test/", {"endpoint": sub.endpoint})
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "message": "Sent. It should appear on this device in a few seconds.",
    }
    [call] = transport.calls
    assert call["endpoint"] == sub.endpoint
    message = json.loads(receiver.decrypt(call["body"]))
    assert message == {
        "title": "Vitalos",
        "body": "Test notification: notifications work on this device.",
        "url": "/portal/account/",
        "tag": "vitalos-test",
    }
    assert call["headers"]["Topic"] == "portal-test"
    delivery = PushDelivery.objects.get(subscription=sub)
    assert delivery.kind == "test" and delivery.status == "sent" and delivery.notification is None


def test_sign_out_turns_notifications_off_for_that_browser(world, vapid):
    sub, _ = add_device(world.approver)
    other, _ = add_device(world.approver)
    client = client_for(world.approver.user)
    client.post("/portal/sign-out/", {"push_endpoint": sub.endpoint})
    assert not PushSubscription.objects.filter(pk=sub.pk).exists()
    assert PushSubscription.objects.filter(pk=other.pk).exists()
    # Someone else's endpoint in the form does nothing.
    theirs, _ = add_device(world.contrib)
    client = client_for(world.approver.user)
    response = client.post("/portal/sign-out/", {"push_endpoint": theirs.endpoint})
    assert response.status_code == 302 and PushSubscription.objects.filter(pk=theirs.pk).exists()


def test_renew_needs_the_old_subscriptions_secret(world, vapid):
    sub, old = add_device(world.approver)
    fresh = Receiver(fcm())
    anonymous = Client(enforce_csrf_checks=True)  # the worker has no session or CSRF token
    wrong = {
        "old_endpoint": sub.endpoint,
        "old_auth": b64(secrets.token_bytes(16)),
        "subscription": fresh.subscription(),
    }
    assert post_json(anonymous, "/portal/push/renew/", wrong).status_code == 204
    assert PushSubscription.objects.get(pk=sub.pk).endpoint == old.endpoint
    unknown = {**wrong, "old_endpoint": fcm(), "old_auth": b64(old.auth)}
    assert post_json(anonymous, "/portal/push/renew/", unknown).status_code == 204
    bad_new = {
        "old_endpoint": sub.endpoint,
        "old_auth": b64(old.auth),
        "subscription": Receiver("https://example.com/x").subscription(),
    }
    assert post_json(anonymous, "/portal/push/renew/", bad_new).status_code == 204
    assert PushSubscription.objects.get(pk=sub.pk).endpoint == old.endpoint
    right = {"old_endpoint": sub.endpoint, "old_auth": b64(old.auth), "subscription": fresh.subscription()}
    assert post_json(anonymous, "/portal/push/renew/", right).status_code == 204
    sub.refresh_from_db()
    assert sub.endpoint == fresh.endpoint and sub.auth == b64(fresh.auth) and sub.member == world.approver
    assert AuditEvent.objects.filter(action="portal.push_renewed", actor=world.approver.user).exists()


# --- Delivery ------------------------------------------------------------------------------------------------------


def test_notify_queues_a_push_per_device_when_the_preference_allows(world, vapid, transport, mailoutbox):
    phone, _ = add_device(world.approver)
    laptop, _ = add_device(world.approver)
    add_device(world.contrib)
    pref = notifications.preferences(world.contrib.user)
    pref.push_updates = False
    pref.save()
    update = services.save_update(world.ch_a, title="Push me", body="b", actor=world.staff)
    services.publish_update(update, actor=world.staff)
    queued = PushDelivery.objects.filter(notification__dedupe_key=f"update:{update.pk}")
    assert set(queued.values_list("subscription_id", flat=True)) == {phone.pk, laptop.pk}
    assert set(queued.values_list("status", flat=True)) == {"queued"} and transport.calls == []
    # Email is unaffected by the push preference.
    assert "contrib@northwind.example.test" in {m.to[0] for m in mailoutbox}
    # Another kind uses its own preference: questions still reach the contributor's device.
    question = services.ask_question(world.ch_a, question="Push question?", actor=world.staff)
    assert PushDelivery.objects.filter(
        notification__dedupe_key=f"question:{question.pk}", subscription__member=world.contrib
    ).exists()
    # Nothing is queued twice for the same event.
    again = notifications.notify(
        world.org_a,
        kind="update",
        title="Push me",
        url_name="update",
        url_kwargs={"pk": update.pk},
        key=f"update:{update.pk}",
    )
    assert again == 0 and queued.count() == 2


def test_pushes_go_out_once_the_action_commits(world, vapid, transport, django_capture_on_commit_callbacks):
    sub, receiver = add_device(world.approver)
    with django_capture_on_commit_callbacks(execute=True):
        update = services.save_update(world.ch_a, title="After commit", body="b", actor=world.staff)
        services.publish_update(update, actor=world.staff)
    [call] = transport.calls
    assert call["endpoint"] == sub.endpoint and call["timeout"] == push.TIMEOUT_SECONDS
    note = Notification.objects.get(user=world.approver.user, dedupe_key=f"update:{update.pk}")
    message = json.loads(receiver.decrypt(call["body"]))
    assert message["url"] == f"/portal/notifications/{note.pk}/open/" and message["tag"] == "vitalos-update"
    headers = call["headers"]
    assert (
        headers["TTL"] == "86400" and headers["Urgency"] == "normal" and headers["Topic"] == "portal-update"
    )
    assert headers["Content-Encoding"] == "aes128gcm"
    token, k = parse_vapid(headers["Authorization"])
    _, claims = verify_jwt(token, k)
    assert claims["aud"] == "https://fcm.googleapis.com"
    delivery = PushDelivery.objects.get(notification=note)
    assert delivery.status == "sent" and delivery.attempts == 1 and delivery.sent_at
    sub.refresh_from_db()
    assert sub.last_success_at and sub.failure_count == 0


def test_the_payload_names_nothing(world, vapid, transport, django_capture_on_commit_callbacks):
    _, receiver = add_device(world.approver)
    with django_capture_on_commit_callbacks(execute=True):
        services.post_staff_message(world.ch_a, body="Contoso Northwind secret plan", actor=world.staff)
        version = services.create_version(world.deliv_a, actor=world.staff, summary="v2", body="Body v2")
        services.share_version(version, actor=world.staff)
        services.ask_question(world.ch_a, question="Which Northwind ledger?", actor=world.staff)
    assert len(transport.calls) >= 3
    names = [*seed_names(world), "secret plan", "Prototype report", "Which Northwind ledger"]
    for call in transport.calls:
        plain = receiver.decrypt(call["body"]).decode()
        message = json.loads(plain)
        assert set(message) == {"title", "body", "url", "tag"}
        assert message["title"] == "Vitalos" and message["body"] in {
            body for _, body in push.MESSAGES.values()
        }
        assert re.fullmatch(r"/portal/notifications/\d+/open/", message["url"])
        for name in names:
            assert name.lower() not in plain.lower(), name
            assert name.lower() not in json.dumps(call["headers"]).lower(), name


def test_internal_notes_and_drafts_never_push(world, vapid, transport, django_capture_on_commit_callbacks):
    add_device(world.approver)
    with django_capture_on_commit_callbacks(execute=True):
        services.post_staff_message(world.ch_a, body="internal only", actor=world.staff, internal=True)
        services.save_update(world.ch_a, title="Draft", body="not ready", actor=world.staff)
        services.save_brief(
            world.ch_a,
            segments=[{"id": "s1", "text": "draft", "provenance": "ai_suggestion"}],
            summary="D",
            actor=world.staff,
        )
    assert transport.calls == [] and not PushDelivery.objects.exists()


def test_201_sent_410_disables_and_stops(world, vapid, transport):
    sub, _ = add_device(world.approver)
    ok, _ = push.send_test(sub)
    assert ok
    transport.statuses = [410]
    ok, message = push.send_test(sub)
    assert not ok and "ended" in message
    sub.refresh_from_db()
    assert sub.disabled_at and sub.disabled_reason == "gone"
    assert AuditEvent.objects.filter(action="portal.push_disabled").exists()
    # A disabled device gets nothing more: no queueing, and a queued delivery is refused without a request.
    update = services.save_update(world.ch_a, title="After 410", body="b", actor=world.staff)
    services.publish_update(update, actor=world.staff)
    assert not PushDelivery.objects.filter(notification__dedupe_key=f"update:{update.pk}").exists()
    stale = PushDelivery.objects.create(
        subscription=sub,
        kind="update",
        notification=Notification.objects.filter(user=world.approver.user).first(),
    )
    push.deliver(stale.pk)
    stale.refresh_from_db()
    assert stale.last_error == "device_off" and len(transport.calls) == 2


@pytest.mark.parametrize("status,category", [(413, "too_large"), (400, "rejected"), (403, "unauthorised")])
def test_permanent_failures_are_not_retried(world, vapid, transport, status, category):
    add_device(world.approver)
    transport.statuses = [status]
    update = services.save_update(world.ch_a, title="Permanent", body="b", actor=world.staff)
    services.publish_update(update, actor=world.staff)
    assert notifications.send_pending()["push"] == {"attempted": 1, "sent": 0, "failed": 1}
    delivery = PushDelivery.objects.get(notification__dedupe_key=f"update:{update.pk}")
    assert delivery.status == "failed" and delivery.last_error == category
    assert delivery.attempts == PushDelivery.MAX_ATTEMPTS  # final: never picked up again
    assert notifications.send_pending()["push"]["attempted"] == 0 and len(transport.calls) == 1


def test_429_and_5xx_retry_with_backoff_and_stop_at_the_cap(world, vapid, transport):
    sub, _ = add_device(world.approver)
    update = services.save_update(world.ch_a, title="Busy", body="b", actor=world.staff)
    services.publish_update(update, actor=world.staff)
    delivery = PushDelivery.objects.get(notification__dedupe_key=f"update:{update.pk}")
    transport.statuses = [(429, 120), 503, 429, 201]
    before = timezone.now()
    push.deliver(delivery.pk)
    delivery.refresh_from_db()
    assert delivery.status == "failed" and delivery.last_error == "rate_limited" and delivery.attempts == 1
    assert delivery.next_attempt_at >= before + dt.timedelta(seconds=120)  # Retry-After honoured
    assert push.send_pending()["attempted"] == 0  # not due yet
    for expected in (2, 3):
        PushDelivery.objects.filter(pk=delivery.pk).update(
            next_attempt_at=timezone.now() - dt.timedelta(seconds=1)
        )
        push.send_pending()
        delivery.refresh_from_db()
        assert delivery.attempts == expected
    assert delivery.status == "failed" and delivery.last_error == "rate_limited"
    # Bounded: no fourth attempt, however often the retry runs.
    PushDelivery.objects.filter(pk=delivery.pk).update(
        next_attempt_at=timezone.now() - dt.timedelta(seconds=1)
    )
    for _ in range(3):
        push.send_pending()
    assert len(transport.calls) == PushDelivery.MAX_ATTEMPTS
    sub.refresh_from_db()
    assert sub.disabled_at is None and sub.failure_count == 1


def test_network_errors_never_break_notify_or_email(
    world, vapid, transport, mailoutbox, django_capture_on_commit_callbacks
):
    add_device(world.approver)
    add_device(world.contrib)
    transport.statuses = [OSError("connection refused"), TimeoutError()]
    with django_capture_on_commit_callbacks(execute=True):
        update = services.save_update(world.ch_a, title="Network down", body="b", actor=world.staff)
        services.publish_update(update, actor=world.staff)  # must not raise
    update.refresh_from_db()
    assert update.status == "published"
    assert Notification.objects.filter(dedupe_key=f"update:{update.pk}").count() == 4
    assert len(mailoutbox) == 4  # every email still went
    errors = set(PushDelivery.objects.values_list("last_error", flat=True))
    assert errors == {"network", "timeout"}
    assert set(PushDelivery.objects.values_list("status", flat=True)) == {"failed"}


def test_a_crashing_push_layer_never_breaks_notify(world, vapid, monkeypatch, mailoutbox):
    add_device(world.approver)

    def boom(*args, **kwargs):
        raise RuntimeError("push layer exploded")

    monkeypatch.setattr(push, "queue", boom)
    update = services.save_update(world.ch_a, title="Crash", body="b", actor=world.staff)
    services.publish_update(update, actor=world.staff)
    assert Notification.objects.filter(dedupe_key=f"update:{update.pk}").count() == 4 and len(mailoutbox) == 4


def test_revoked_members_and_rotated_keys_get_nothing(world, vapid, transport, settings):
    sub, _ = add_device(world.viewer)
    update = services.save_update(world.ch_a, title="Revoked", body="b", actor=world.staff)
    services.publish_update(update, actor=world.staff)
    delivery = PushDelivery.objects.get(subscription=sub)
    services.revoke_member(world.viewer, actor=world.staff)
    push.deliver(delivery.pk)
    delivery.refresh_from_db()
    assert delivery.last_error == "not_member" and transport.calls == []
    # Rotating the server key retires every subscription made with the old one.
    mine, _ = add_device(world.approver)
    settings.PORTAL_PUSH_VAPID_PRIVATE_KEY = raw_scalar(ec.generate_private_key(ec.SECP256R1()))
    later = services.save_update(world.ch_a, title="New key", body="b", actor=world.staff)
    services.publish_update(later, actor=world.staff)
    mine.refresh_from_db()
    assert mine.disabled_reason == "key" and not PushDelivery.objects.filter(subscription=mine).exists()
    assert transport.calls == []


def test_old_deliveries_expire_instead_of_sending(world, vapid, transport):
    add_device(world.approver)
    update = services.save_update(world.ch_a, title="Old", body="b", actor=world.staff)
    services.publish_update(update, actor=world.staff)
    PushDelivery.objects.update(created_at=timezone.now() - dt.timedelta(hours=25))
    push.send_pending()
    assert (
        set(PushDelivery.objects.values_list("last_error", flat=True)) == {"expired"}
        and transport.calls == []
    )


def test_real_http_to_a_fake_push_server(world, vapid, push_server, django_capture_on_commit_callbacks):
    """The real transport (urllib, no redirects, bounded reads) against a push service on 127.0.0.1."""
    sub, receiver = add_device(world.approver, endpoint=f"{push_server.origin}/push/device-1")
    with django_capture_on_commit_callbacks(execute=True):
        question = services.ask_question(world.ch_a, question="Over real HTTP?", actor=world.staff)
    [request] = push_server.requests
    assert request["path"] == "/push/device-1"
    headers = {k.lower(): v for k, v in request["headers"].items()}
    assert headers["content-encoding"] == "aes128gcm" and headers["ttl"] == "86400"
    assert headers["urgency"] == "normal" and headers["topic"] == "portal-question"
    token, k = parse_vapid(headers["authorization"])
    _, claims = verify_jwt(token, k)
    assert claims["aud"] == push_server.origin
    message = json.loads(receiver.decrypt(request["body"]))
    assert message["body"] == "A new question needs your answer." and question.question not in json.dumps(
        message
    )
    assert PushDelivery.objects.get(subscription=sub).status == "sent"
    # 410 from the service disables the device.
    push_server.responses = [(410, {})]
    ok, _ = push.send_test(sub)
    sub.refresh_from_db()
    assert not ok and sub.disabled_reason == "gone"


def test_management_command_reports_push(world, vapid, transport):
    from io import StringIO

    from django.core.management import call_command

    add_device(world.approver)
    update = services.save_update(world.ch_a, title="Command", body="b", actor=world.staff)
    services.publish_update(update, actor=world.staff)
    out = StringIO()
    call_command("portal_send_pending", stdout=out)
    assert "push attempted=1 sent=1 failed=0" in out.getvalue()


# --- Without a key -------------------------------------------------------------------------------------------------


def test_without_a_key_push_is_off_everywhere(world, settings, transport):
    settings.PORTAL_PUSH_VAPID_PRIVATE_KEY = ""
    client = client_for(world.approver.user)
    response = post_json(client, "/portal/push/subscribe/", Receiver(fcm()).subscription())
    assert (
        response.status_code == 503
        and response.json()["message"] == "Notifications on this device aren't available yet."
    )
    assert post_json(client, "/portal/push/test/", {"endpoint": fcm()}).status_code == 404
    assert post_json(client, "/portal/push/renew/", {}).status_code == 204
    page = client.get("/portal/account/")
    assert page.status_code == 200
    card = re.search(r'<section class="card push".*?</section>', page.content.decode(), re.S).group(0)
    assert "Notifications on this device aren't available yet." in card
    assert "data-push-key" not in card and "data-push-on" not in card
    assert "data-push-sync" not in client.get("/portal/").content.decode()
    update = services.save_update(world.ch_a, title="No key", body="b", actor=world.staff)
    services.publish_update(update, actor=world.staff)
    assert not PushDelivery.objects.exists() and transport.calls == []
    assert "push" not in notifications.send_pending()
    source = Client().get("/portal/sw.js").content.decode()
    assert 'const PUSH_KEY = "";' in source
    prefs = client.get("/portal/notifications/preferences/").content.decode()
    assert "aren't available yet" in prefs


def test_without_a_key_existing_devices_can_still_be_removed(world, vapid, settings):
    sub, _ = add_device(world.approver)
    settings.PORTAL_PUSH_VAPID_PRIVATE_KEY = ""
    client = client_for(world.approver.user)
    assert "Chrome on Android" in client.get("/portal/account/").content.decode()
    assert client.post("/portal/push/unsubscribe/", {"subscription": sub.pk}).status_code == 302
    assert not PushSubscription.objects.exists()
    assert client.post("/portal/push/test/", {"subscription": sub.pk}).status_code == 404


# --- Service worker ------------------------------------------------------------------------------------------------


def test_service_worker_handles_push_and_clicks_with_a_same_origin_guard(world, vapid):
    source = Client().get("/portal/sw.js").content.decode()
    assert pwa.SW_REVISION == "2"
    for handler in (
        'addEventListener("push"',
        'addEventListener("notificationclick"',
        'addEventListener("pushsubscriptionchange"',
    ):
        assert handler in source, handler
    guard = source.split("function safeTarget", 1)[1].split("\n}\n", 1)[0]
    assert 'value.startsWith("/") && !value.startsWith("//")' in guard
    assert "url.origin === scope.origin && url.pathname.startsWith(scope.pathname)" in guard
    assert "return scope.href;" in guard  # anything else opens the portal home
    click = source.split('addEventListener("notificationclick"', 1)[1].split("});", 1)[0]
    assert "openTarget(safeTarget(data.url))" in click
    assert "data: { url: safeTarget(data.url) }" in source
    assert f'const ICON = "{pwa.static(pwa.ICON_192)}";' in source
    assert f'const BADGE = "{pwa.static(pwa.BADGE)}";' in source
    assert f'const PUSH_KEY = "{push.public_key()}";' in source
    assert 'const PUSH_RENEW_URL = "/portal/push/renew/";' in source
    assert vapid.private_numbers().private_value.to_bytes(32, "big").hex() not in source
    assert raw_scalar(vapid) not in source


def test_service_worker_still_caches_no_workspace_paths(world, vapid):
    source = Client().get("/portal/sw.js").content.decode()
    pushing = source.split("// --- Push notifications", 1)[1]
    for forbidden in ("caches.open", "cache.put", "cache.add", "keep(", "indexedDB", "localStorage"):
        assert forbidden not in pushing, forbidden
    assert source.count("cache.put(") == 1 and source.count("cache.addAll(") == 1
    assert source.count("event.respondWith(") == 2
    # renew sends no cookies: the old subscription's secret is the only credential.
    assert 'credentials: "omit"' in pushing


def test_badge_icon_is_a_96px_png():
    data = (BASE_DIR / "static/portal/icons/badge-96.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")) == (96, 96)


# --- UI: Account card, device list, preferences ------------------------------------------------------------------


def push_card(html: str) -> str:
    match = re.search(r'<section class="card push".*?</section>', html, re.S)
    assert match, "push card missing"
    return match.group(0)


def test_account_card_renders_every_state_and_the_device_list(world, vapid):
    sub, _ = add_device(world.approver)
    add_device(world.contrib)
    page = client_for(world.approver.user).get("/portal/account/").content.decode()
    card = push_card(page)
    assert f'data-push-key="{push.public_key()}"' in card
    assert (
        'data-push-subscribe="/portal/push/subscribe/"' in card
        and 'data-push-test="/portal/push/test/"' in card
    )
    assert f'data-push-devices="{push.endpoint_digest(sub.endpoint)}"' in card
    assert (
        '<p class="notice" data-push-state="unsupported">' in card
    )  # the server default, without JavaScript
    for state in ("ios", "off", "on", "blocked"):
        assert f'data-push-state="{state}" hidden' in card, state
    assert (
        "Install the app first:</strong> tap Share, then Add to Home Screen, then turn notifications on from the app."
        in card
    )
    assert "data-push-on>Turn on notifications</button>" in card
    assert "Send a test notification" in card and "data-push-off>Turn off</button>" in card
    assert "Notifications are blocked for this site." in card
    assert 'role="status" aria-live="polite"' in card
    devices = re.search(r'<ul class="list push__devices".*?</ul>', card, re.S).group(0)
    assert devices.count("<li") == 1 and "Chrome on Android" in devices
    assert f'name="subscription" value="{sub.pk}"' in devices and "csrfmiddlewaretoken" in devices
    assert sub.endpoint not in page  # endpoints never appear in the page, only their digests
    assert (
        "<script" not in card and "onclick" not in card and "style=" not in card
    )  # CSP: no inline code or styles
    assert "<dialog" not in card and "popover" not in card


def test_pages_carry_the_rotation_sync_and_the_sign_out_field(world, vapid):
    page = client_for(world.approver.user).get("/portal/").content.decode()
    assert 'data-sw="/portal/sw.js" data-sw-scope="/portal/" data-push-sync="/portal/push/subscribe/"' in page
    assert '<input type="hidden" name="push_endpoint" value="" data-push-endpoint>' in page


def test_preferences_page_has_push_toggles_beside_email(world, vapid):
    add_device(world.approver)
    client = client_for(world.approver.user)
    page = client.get("/portal/notifications/preferences/").content.decode()
    assert "<legend>Email</legend>" in page and "<legend>Notifications on your devices</legend>" in page
    for name in ("updates", "questions", "deliverables", "approvals"):
        assert f'name="email_{name}"' in page and f'name="push_{name}"' in page
    assert "These apply to 1 device where you turned notifications on." in page
    response = client.post(
        "/portal/notifications/preferences/", {"email_updates": "on", "push_questions": "on"}
    )
    assert response.status_code == 302
    pref = NotificationPreference.objects.get(user=world.approver.user)
    assert pref.email_updates and pref.push_questions
    assert not pref.push_updates and not pref.push_deliverables and not pref.push_approvals
    assert pref.wants_push("question") and not pref.wants_push("message") and not pref.wants_push("update")


def test_push_preferences_default_on():
    pref = NotificationPreference()
    assert all(pref.wants_push(kind) for kind, _ in Notification.Kind.choices)


# --- Deploy: the key is generated once by the workflow and kept by deploy.sh --------------------------------------

WORKFLOW = REPO / ".github/workflows/superadmin-deploy.yml"
DEPLOY = BASE_DIR / "deploy/gcp/deploy.sh"


def workflow_key_command() -> str:
    text = WORKFLOW.read_text()
    match = re.search(r'NEW_PORTAL_PUSH_VAPID_PRIVATE_KEY="\$\((openssl ecparam[^\n]*)\)"\n', text)
    assert match, "the deploy workflow must generate the VAPID key with openssl ecparam"
    return match.group(1)


def test_workflow_generates_masks_and_exports_the_key():
    text = WORKFLOW.read_text()
    command = workflow_key_command()
    assert command.startswith("openssl ecparam -name prime256v1 -genkey -noout")
    assert 'echo "::add-mask::$NEW_PORTAL_PUSH_VAPID_PRIVATE_KEY"' in text
    assert re.search(r"export [^\n]*NEW_PORTAL_PUSH_VAPID_PRIVATE_KEY", text)
    assert "NEW_PORTAL_PUSH_VAPID_PRIVATE_KEY}" in text  # a length guard before deploy.sh runs


def test_deploy_script_keeps_an_existing_key_and_references_the_secret():
    text = DEPLOY.read_text()
    assert 'generated_once portal-push-vapid-private-key "${NEW_PORTAL_PUSH_VAPID_PRIVATE_KEY:-}"' in text
    assert "  PORTAL_PUSH_VAPID_PRIVATE_KEY=portal-push-vapid-private-key\n" in text
    assert "^[A-Za-z0-9_-]{43}$" in text  # format guard before anything is written
    # generated_once() keeps a stored secret and only otherwise writes the new value.
    body = text.split("generated_once() {", 1)[1].split("\n}\n", 1)[0]
    assert body.index('if secret_exists "$1"; then return 0; fi') < body.index('put_secret "$1" "$2"')
    env_example = (BASE_DIR / ".env.example").read_text()
    assert re.search(r"^PORTAL_PUSH_VAPID_PRIVATE_KEY=$", env_example, re.M)


OPENSSL = shutil.which("openssl")
BASH = shutil.which("bash")


@pytest.mark.skipif(not OPENSSL or not BASH, reason="needs openssl and bash")
def test_workflow_key_pipeline_yields_the_key_openssl_generated(tmp_path, settings):
    """Run the workflow's own pipeline on a key generated here and compare the public key with openssl's."""
    pem = tmp_path / "test-only.pem"
    generate = [OPENSSL, "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(pem)]
    subprocess.run(generate, check=True)  # noqa: S603 - fixed arguments
    stages = workflow_key_command().split("|", 1)[1]  # everything after the generation step
    pipeline = [BASH, "-o", "pipefail", "-c", f'cat "$0" |{stages}', str(pem)]
    # The workflow's own command line, on a temporary key made for this test.
    raw = subprocess.run(pipeline, check=True, capture_output=True, text=True).stdout.strip()  # noqa: S603
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", raw)
    public = [OPENSSL, "ec", "-in", str(pem), "-pubout", "-outform", "DER"]
    spki = subprocess.run(public, check=True, capture_output=True).stdout  # noqa: S603
    settings.PORTAL_PUSH_VAPID_PRIVATE_KEY = raw
    assert push.enabled()
    assert unb64(push.public_key()) == spki[-65:]  # the uncompressed point closes the SubjectPublicKeyInfo
