"""Web Push for the installable client portal (ADR-056, Phase 2).

Standards, implemented with ``cryptography`` primitives only (no pywebpush or http_ece, and no hand-written curve
arithmetic):

* RFC 8030, HTTP push: the encrypted message is POSTed to the subscription's endpoint with ``TTL``, ``Urgency``
  and ``Topic``.
* RFC 8292, VAPID: an ES256 JWT (``aud`` = the endpoint's origin, ``exp`` within 24 hours, ``sub`` = a contact)
  and this server's public key, in ``Authorization: vapid t=..., k=...``.
* RFC 8291 with RFC 8188, ``aes128gcm``: ECDH on P-256 with the browser's key, HKDF-SHA256 with the browser's
  authentication secret, AES-128-GCM, one record.

Keys. ``PORTAL_PUSH_VAPID_PRIVATE_KEY`` is the raw 32-byte P-256 private scalar, base64url without padding. The
public key (65-byte uncompressed point) is derived from it at runtime. Without a valid key push is off everywhere:
nothing is queued, the routes refuse politely and the Account page says notifications aren't available yet. Each
subscription records the fingerprint of the key it was made with, so rotating the key retires every older one.

Privacy. Lock screens are visible and phones are shared, so a payload carries only a generic line per kind from
``MESSAGES`` plus the path of the notification's "open" route (which re-checks access when followed) and a tag.
Never a project, item or organisation name, and never message text.

SSRF. The server POSTs to a URL a browser supplied. An endpoint must be https, with no credentials and no
non-default port, and its host must be a real push service (``PUSH_SERVICE_HOSTS`` and ``PUSH_SERVICE_SUFFIXES``).
It is checked when stored and again before every send, and redirects are never followed.

Delivery never breaks the action that caused it. ``notifications.notify`` queues ``PushDelivery`` rows and sends
them once the transaction commits (bounded by count and time). ``send_pending`` retries 429, 5xx and network
failures with backoff, up to ``PushDelivery.MAX_ATTEMPTS``. 404 and 410 disable the subscription; 400, 413 and
other 4xx answers are permanent. Errors are stored as short categories, never response bodies.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import http.client
import ipaddress
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import timedelta
from email.utils import parsedate_to_datetime
from functools import lru_cache
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.core import checks
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record

from . import selectors
from .models import Membership, Notification, NotificationPreference, PushDelivery, PushSubscription

logger = logging.getLogger(__name__)

# --- What a lock screen shows -------------------------------------------------------------------------------------

TEST_KIND = "test"
#: (title, body) per notification kind. Generic on purpose: no names, titles or message text ever reach a lock
#: screen. A later "detailed text" option would add a second mapping here and choose between them per member.
MESSAGES: dict[str, tuple[str, str]] = {
    Notification.Kind.UPDATE: ("Vitalos", "There's an update on your project."),
    Notification.Kind.QUESTION: ("Vitalos", "A new question needs your answer."),
    Notification.Kind.DELIVERABLE: ("Vitalos", "A deliverable is ready for your review."),
    Notification.Kind.APPROVAL: ("Vitalos", "An approval is waiting for you."),
    Notification.Kind.BRIEF: ("Vitalos", "A brief is ready for your review."),
    Notification.Kind.DECISION: ("Vitalos", "A decision has been recorded."),
    Notification.Kind.MESSAGE: ("Vitalos", "You have a new message in your portal."),
    Notification.Kind.CHANGE: ("Vitalos", "There's an update on a change request."),
    TEST_KIND: ("Vitalos", "Test notification: notifications work on this device."),
}
DEFAULT_MESSAGE = ("Vitalos", "There's something new in your portal.")

# --- Limits -------------------------------------------------------------------------------------------------------

MAX_ENDPOINT_LENGTH = 2048
MAX_DEVICES_PER_MEMBER = 10
TTL_SECONDS = 24 * 3600  # a notification older than a day is not worth showing
VAPID_LIFETIME_SECONDS = 12 * 3600  # RFC 8292 allows at most 24 hours
TIMEOUT_SECONDS = 5
MAX_RESPONSE_BYTES = 4096
RECORD_SIZE = 4096
# RFC 8291 section 4: one 4096-octet record less the 86-octet header, the tag and the delimiter.
MAX_PAYLOAD_BYTES = 3993
RETRY_DELAYS_SECONDS = (60, 300)  # before the second and third attempts
MAX_RETRY_AFTER_SECONDS = 3600
DISABLE_AFTER_FAILURES = 5  # consecutive final failures before a device is switched off
IMMEDIATE_LIMIT = 20  # pushes sent straight after the action commits; the rest wait for send_pending
IMMEDIATE_BUDGET_SECONDS = 10
RATE_LIMITS_PER_HOUR = {
    "portal.push_subscribed": 20,
    "portal.push_removed": 30,
    "portal.push_test": 5,
    "portal.push_renewed": 5,
}
USER_AGENT = "Vitalos-Portal-Push/1"

# --- SSRF allowlist: real push services only -------------------------------------------------------------------------

PUSH_SERVICE_HOSTS = frozenset(
    {
        "fcm.googleapis.com",  # Chrome, Edge on Android, Samsung Internet, Opera, Brave
        "updates.push.services.mozilla.com",  # Firefox
        "push.services.mozilla.com",
        "web.push.apple.com",  # Safari on macOS and iOS 16.4+ (installed web apps)
    }
)
PUSH_SERVICE_SUFFIXES = (
    ".push.apple.com",
    ".notify.windows.com",  # Edge on Windows (WNS)
)
_HOSTNAME = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_KEY = re.compile(r"^[A-Za-z0-9_-]{43}$")
_B64URL = re.compile(r"^[A-Za-z0-9_-]*={0,2}$")


class PushError(Exception):
    """A refusal the member can be told about. The message never contains internals."""


# --- Encoding helpers -----------------------------------------------------------------------------------------------


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(value) -> bytes:
    if not isinstance(value, str) or len(value) > 256 or not _B64URL.fullmatch(value):
        raise ValueError("not base64url")
    value = value.rstrip("=")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError):
        raise ValueError("not base64url") from None


def endpoint_digest(endpoint: str) -> str:
    """SHA-256 of an endpoint, so the Account page can say "this device" without printing endpoints."""
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


# --- Keys -----------------------------------------------------------------------------------------------------------


@lru_cache(maxsize=4)
def _load_private_key(raw: str):
    if not _KEY.fullmatch(raw):
        return None
    try:
        scalar = int.from_bytes(b64url_decode(raw), "big")
        return ec.derive_private_key(scalar, ec.SECP256R1())
    except (ValueError, TypeError, OverflowError):
        return None


def vapid_key():
    """The application server's private key, or None when push is off (no key, or not a valid one)."""
    return _load_private_key(getattr(settings, "PORTAL_PUSH_VAPID_PRIVATE_KEY", "") or "")


def enabled() -> bool:
    return vapid_key() is not None


def _public_bytes(key) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def public_key() -> str:
    """The public key for ``pushManager.subscribe`` (65-byte uncompressed point, base64url), or ''."""
    key = vapid_key()
    return b64url(_public_bytes(key)) if key is not None else ""


def key_id() -> str:
    """Fingerprint of the current public key; a subscription made with another key cannot receive pushes."""
    key = vapid_key()
    return hashlib.sha256(_public_bytes(key)).hexdigest()[:16] if key is not None else ""


def check_vapid_key(app_configs=None, **kwargs):
    """System check: a key that is set but unusable leaves push off; say so without showing the value."""
    raw = getattr(settings, "PORTAL_PUSH_VAPID_PRIVATE_KEY", "") or ""
    if raw and not enabled():
        return [
            checks.Warning(
                "PORTAL_PUSH_VAPID_PRIVATE_KEY is set but is not a P-256 private key in base64url "
                "(43 characters), so portal push notifications are off.",
                id="portal.W001",
            )
        ]
    return []


# --- Endpoint allowlist (SSRF) --------------------------------------------------------------------------------------


def _origin(scheme: str, host: str, port: int | None) -> str:
    host = f"[{host}]" if ":" in host else host
    default = {"https": 443, "http": 80}.get(scheme)
    return f"{scheme}://{host}" if port in (None, default) else f"{scheme}://{host}:{port}"


def _dev_origins() -> set[str]:
    origins = set()
    for value in getattr(settings, "PORTAL_PUSH_DEV_ORIGINS", []) or []:
        try:
            parts = urlsplit(value.strip())
            origins.add(_origin(parts.scheme, parts.hostname or "", parts.port))
        except ValueError:
            continue
    return origins


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _allowed_host(host: str) -> bool:
    if host in PUSH_SERVICE_HOSTS:
        return True
    return any(host.endswith(suffix) and len(host) > len(suffix) for suffix in PUSH_SERVICE_SUFFIXES)


def endpoint_problem(endpoint) -> str:
    """'' when this server may POST to ``endpoint``; otherwise a short reason (never echoed to the browser)."""
    if not isinstance(endpoint, str) or not endpoint:
        return "missing"
    if len(endpoint) > MAX_ENDPOINT_LENGTH:
        return "too_long"
    if any(not (0x21 <= ord(ch) <= 0x7E) for ch in endpoint):
        return "invalid"
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        return "invalid"
    host = parts.hostname or ""
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return "credentials"
    if parts.fragment:
        return "invalid"
    dev = _dev_origins()
    if dev and _origin(parts.scheme, host, port) in dev:
        return ""  # a fake push server on this machine (development and tests only; production refuses it)
    if parts.scheme != "https":
        return "not_https"
    if port not in (None, 443):
        return "port"
    if not host or _is_ip_literal(host):
        return "ip_literal"
    if not _HOSTNAME.fullmatch(host) or not _allowed_host(host):
        return "host"
    return ""


# --- Subscriptions from the browser ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class SubscriptionData:
    endpoint: str
    p256dh: str  # base64url, no padding
    auth: str


def parse_subscription(data) -> SubscriptionData:
    """Validate ``{endpoint, keys: {p256dh, auth}}`` as ``PushSubscription.toJSON()`` produces it."""
    if not isinstance(data, dict):
        raise PushError("The browser sent an incomplete subscription.")
    endpoint = data.get("endpoint")
    if endpoint_problem(endpoint):
        raise PushError("This browser's push service isn't supported.")
    keys = data.get("keys")
    if not isinstance(keys, dict):
        raise PushError("The browser sent an incomplete subscription.")
    try:
        p256dh = b64url_decode(keys.get("p256dh"))
        auth = b64url_decode(keys.get("auth"))
    except ValueError:
        raise PushError("The browser sent an incomplete subscription.") from None
    if len(p256dh) != 65 or p256dh[0] != 4 or len(auth) != 16:
        raise PushError("The browser sent an incomplete subscription.")
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), p256dh)
    except ValueError:
        raise PushError("The browser sent an incomplete subscription.") from None
    return SubscriptionData(endpoint=endpoint, p256dh=b64url(p256dh), auth=b64url(auth))


def device_label(user_agent: str) -> str:
    """A short, coarse label ("Chrome on Android"). The raw user agent is never stored."""
    ua = user_agent or ""
    if "Edg/" in ua or "EdgA/" in ua or "EdgiOS/" in ua:
        browser = "Edge"
    elif "SamsungBrowser/" in ua:
        browser = "Samsung Internet"
    elif "OPR/" in ua or "Opera" in ua:
        browser = "Opera"
    elif "Firefox/" in ua or "FxiOS/" in ua:
        browser = "Firefox"
    elif "CriOS/" in ua or "Chrome/" in ua or "Chromium/" in ua:
        browser = "Chrome"
    elif "Safari/" in ua or "AppleWebKit/" in ua:
        browser = "Safari"
    else:
        browser = "Browser"
    if "iPhone" in ua:
        system = "iPhone"
    elif "iPad" in ua:
        system = "iPad"
    elif "Android" in ua:
        system = "Android"
    elif "Windows" in ua:
        system = "Windows"
    elif "CrOS" in ua:
        system = "ChromeOS"
    elif "Macintosh" in ua or "Mac OS X" in ua:
        system = "Mac"
    elif "Linux" in ua:
        system = "Linux"
    else:
        system = ""
    return f"{browser} on {system}" if system else browser


def over_limit(user, action: str) -> bool:
    """Per-member hourly limit, counted from the audit trail (durable, shared by every worker)."""
    from apps.audit.models import AuditEvent

    since = timezone.now() - timedelta(hours=1)
    count = AuditEvent.objects.filter(actor=user, action=action, created_at__gte=since).count()
    return count >= RATE_LIMITS_PER_HOUR[action]


def devices(user):
    """The member's devices that can receive pushes (active, made with the current key while push is on)."""
    qs = PushSubscription.objects.filter(member__user=user, disabled_at__isnull=True)
    if enabled():
        qs = qs.filter(vapid_key_id=key_id())
    return qs.order_by("-created_at", "-id")


def _disable(sub: PushSubscription, reason: str) -> None:
    if sub.disabled_at is None:
        sub.disabled_at = timezone.now()
        sub.disabled_reason = reason
        sub.save(update_fields=["disabled_at", "disabled_reason"])


def _enforce_device_cap(user) -> None:
    active = PushSubscription.objects.filter(member__user=user, disabled_at__isnull=True).order_by(
        "-created_at", "-id"
    )
    for extra in active[MAX_DEVICES_PER_MEMBER:]:
        _disable(extra, PushSubscription.Reason.LIMIT)


def subscribe(member: Membership, data: SubscriptionData, *, user_agent: str = "", request=None):
    """Store (or refresh) this browser's subscription for ``member``. Returns ``(subscription, created)``.

    An endpoint belongs to one browser profile. If another person registered it before (a shared computer), the
    person signed in now holds that browser, so the older row is removed and this one takes its place. The browser
    proves it is the same one by presenting the same keys: knowing only another person's endpoint is not enough."""
    if not enabled():
        raise PushError("Notifications on this device aren't available yet.")
    now = timezone.now()
    try:
        with transaction.atomic():
            existing = (
                PushSubscription.objects.select_for_update(of=("self",))
                .select_related("member")
                .filter(endpoint=data.endpoint)
                .first()
            )
            if existing is not None and existing.member.user_id != member.user_id:
                same_browser = hmac.compare_digest(
                    existing.auth.encode(), data.auth.encode()
                ) and hmac.compare_digest(existing.p256dh.encode(), data.p256dh.encode())
                if not same_browser:
                    raise PushError(
                        "This device is set up for someone else. Sign out of the portal there, then try again."
                    )
                existing.delete()
                existing = None
            created = existing is None
            sub = existing or PushSubscription(endpoint=data.endpoint, created_at=now)
            sub.member = member
            sub.p256dh = data.p256dh
            sub.auth = data.auth
            sub.vapid_key_id = key_id()
            sub.label = device_label(user_agent)[:60]
            sub.failure_count = 0
            sub.disabled_at = None
            sub.disabled_reason = ""
            sub.save()
            _enforce_device_cap(member.user)
    except IntegrityError:  # the same endpoint registered by a simultaneous request
        raise PushError("This device was registered a moment ago. Reload the page.") from None
    record(
        "portal.push_subscribed",
        request=request,
        actor=member.user,
        entity=sub,
        summary=f"Turned on notifications: {sub.label}",
    )
    return sub, created


def find_device(user, *, pk=None, endpoint=None) -> PushSubscription | None:
    """One of ``user``'s own subscriptions by id or endpoint; anything else is None (the view answers 404)."""
    qs = PushSubscription.objects.filter(member__user=user)
    if pk is not None:
        try:
            return qs.filter(pk=int(pk)).first()
        except (TypeError, ValueError):
            return None
    if isinstance(endpoint, str) and 0 < len(endpoint) <= MAX_ENDPOINT_LENGTH:
        return qs.filter(endpoint=endpoint).first()
    return None


def remove(sub: PushSubscription, *, request=None, reason: str = "Removed a device") -> None:
    user = sub.member.user
    label = sub.label
    sub.delete()
    record("portal.push_removed", request=request, actor=user, summary=f"{reason}: {label}")


def forget_device(user, endpoint: str, *, request=None) -> bool:
    """Signing out turns notifications off for the browser that signed out (shared devices)."""
    sub = find_device(user, endpoint=endpoint) if endpoint else None
    if sub is None:
        return False
    remove(sub, request=request, reason="Signed out on a device")
    return True


def renew(old_endpoint, old_auth, data: SubscriptionData, *, request=None) -> bool:
    """Replace a subscription the browser rotated (``pushsubscriptionchange`` in the service worker).

    The worker has no session or CSRF token, so the request proves itself with the old subscription's endpoint and
    authentication secret, which only that browser and this server know. Any mismatch is a silent refusal."""
    if not enabled() or not isinstance(old_endpoint, str) or len(old_endpoint) > MAX_ENDPOINT_LENGTH:
        return False
    try:
        presented = b64url(b64url_decode(old_auth))
    except ValueError:
        return False
    try:
        return _renew(old_endpoint, presented, data, request=request)
    except IntegrityError:  # the new endpoint was registered by a simultaneous request
        return False


def _renew(old_endpoint: str, presented: str, data: SubscriptionData, *, request=None) -> bool:
    with transaction.atomic():
        sub = (
            PushSubscription.objects.select_for_update(of=("self",))
            .select_related("member__user")
            .filter(endpoint=old_endpoint)
            .first()
        )
        if sub is None or not hmac.compare_digest(sub.auth.encode(), presented.encode()):
            return False
        user = sub.member.user
        if selectors.get_membership(user) is None:
            return False
        from apps.audit.models import AuditEvent

        since = timezone.now() - timedelta(hours=1)
        recent = AuditEvent.objects.filter(
            action="portal.push_renewed", entity_type="portal.pushsubscription", entity_id=str(sub.pk)
        ).filter(created_at__gte=since)
        if recent.count() >= RATE_LIMITS_PER_HOUR["portal.push_renewed"]:
            return False
        if PushSubscription.objects.filter(endpoint=data.endpoint).exclude(pk=sub.pk).exists():
            return False
        sub.endpoint = data.endpoint
        sub.p256dh = data.p256dh
        sub.auth = data.auth
        sub.vapid_key_id = key_id()
        sub.failure_count = 0
        sub.disabled_at = None
        sub.disabled_reason = ""
        sub.save()
    record(
        "portal.push_renewed",
        request=request,
        actor=user,
        entity=sub,
        summary=f"The browser renewed its subscription: {sub.label}",
    )
    return True


# --- Encryption (RFC 8291, aes128gcm) --------------------------------------------------------------------------------


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    """HKDF-SHA256 extract and expand (RFC 5869)."""
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def _encrypt(payload: bytes, ua_public: bytes, auth_secret: bytes, sender_key, salt: bytes) -> bytes:
    """The aes128gcm message body. ``sender_key`` and ``salt`` are fresh for every message; tests pass the RFC 8291
    Appendix A values here (the only caller that does)."""
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("payload too large for one record")
    if len(auth_secret) != 16 or len(salt) != 16:
        raise ValueError("auth secret and salt must be 16 bytes")
    receiver = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    as_public = _public_bytes(sender_key)
    ecdh_secret = sender_key.exchange(ec.ECDH(), receiver)
    key_info = b"WebPush: info\x00" + ua_public + as_public
    ikm = _hkdf(auth_secret, ecdh_secret, key_info, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)  # 0x02: the last (and only) record
    header = salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    return header + ciphertext


def encrypt(payload: bytes, ua_public: bytes, auth_secret: bytes) -> bytes:
    return _encrypt(payload, ua_public, auth_secret, ec.generate_private_key(ec.SECP256R1()), os.urandom(16))


# --- VAPID (RFC 8292) ------------------------------------------------------------------------------------------------


def _audience(endpoint: str) -> str:
    parts = urlsplit(endpoint)
    return _origin(parts.scheme, parts.hostname or "", parts.port)


def vapid_authorization(endpoint: str, *, now: float | None = None, key=None) -> str:
    key = key or vapid_key()
    if key is None:
        raise PushError("Notifications on this device aren't available yet.")
    issued = int(time.time() if now is None else now)
    header = {"typ": "JWT", "alg": "ES256"}
    claims = {
        "aud": _audience(endpoint),
        "exp": issued + VAPID_LIFETIME_SECONDS,
        "sub": settings.PORTAL_PUSH_SUBJECT,
    }
    signing_input = ".".join(
        b64url(json.dumps(part, separators=(",", ":")).encode("utf-8")) for part in (header, claims)
    )
    r, s = decode_dss_signature(key.sign(signing_input.encode("ascii"), ec.ECDSA(hashes.SHA256())))
    token = f"{signing_input}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={token}, k={b64url(_public_bytes(key))}"


# --- Payload --------------------------------------------------------------------------------------------------------


def _portal_path(name: str, kwargs: dict | None = None) -> str:
    """Same-origin path of a customer route (``/notifications/1/open/`` on the portal host, ``/portal/...``
    locally). On its own it reveals nothing; following it re-checks access."""
    from .access import portal_absolute

    return urlsplit(portal_absolute(name, kwargs)).path


def message_for(kind: str, url: str) -> dict:
    title, body = MESSAGES.get(kind, DEFAULT_MESSAGE)
    return {"title": title, "body": body, "url": url, "tag": f"vitalos-{kind}"}


def _payload(delivery: PushDelivery) -> bytes:
    if delivery.notification_id:
        url = _portal_path("notification_open", {"pk": delivery.notification_id})
    else:
        url = _portal_path("account_device")  # the test notification opens the page it was sent from
    message = message_for(delivery.kind, url)
    return json.dumps(message, separators=(",", ":")).encode("utf-8")


# --- HTTP ------------------------------------------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is a failure: the endpoint was checked, wherever it points to was not."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class HttpResult:
    status: int
    retry_after: int | None = None


def _retry_after(headers) -> int | None:
    value = (headers.get("Retry-After") if headers is not None else None) or ""
    value = value.strip()
    if value.isdigit():
        return int(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None or when.tzinfo is None:
        return None
    return max(0, int((when - timezone.now()).total_seconds()))


def _send_http(endpoint: str, body: bytes, headers: dict, timeout: float) -> HttpResult:
    """POST once, never following a redirect. Reads at most ``MAX_RESPONSE_BYTES`` and keeps none of it. Transport
    failures raise (``TimeoutError``, ``URLError``, ``OSError``) and are categorised by ``deliver``."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(  # noqa: S310 - endpoint_problem() allows https push services only  # nosec B310
        endpoint, data=body, method="POST", headers=headers
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            response.read(MAX_RESPONSE_BYTES)
            return HttpResult(getattr(response, "status", 200))
    except urllib.error.HTTPError as exc:
        try:
            exc.read(MAX_RESPONSE_BYTES)
        except (OSError, http.client.HTTPException):
            pass
        finally:
            exc.close()
        return HttpResult(exc.code, _retry_after(exc.headers))


def _classify(status: int) -> tuple[str, str]:
    """(outcome, category) for a push service's status code."""
    if 200 <= status < 300:
        return "sent", ""
    if status in (404, 410):
        return "gone", "gone"
    if status == 413:
        return "permanent", "too_large"
    if status == 429:
        return "retry", "rate_limited"
    if status >= 500:
        return "retry", "server_error"
    if status in (401, 403):
        return "permanent", "unauthorised"
    if 300 <= status < 400:
        return "permanent", "redirect"
    return "permanent", "rejected"


# --- Delivery --------------------------------------------------------------------------------------------------------


def queue(note: Notification, pref) -> list[int]:
    """Queue a push to each of the recipient's devices when push is on and their preference allows it."""
    if not enabled() or not pref.wants_push(note.kind):
        return []
    current = key_id()
    stale = PushSubscription.objects.filter(member__user_id=note.user_id, disabled_at__isnull=True).exclude(
        vapid_key_id=current
    )
    stale.update(disabled_at=timezone.now(), disabled_reason=PushSubscription.Reason.KEY)
    ids = []
    for sub in devices(note.user):
        delivery, created = PushDelivery.objects.get_or_create(
            notification=note, subscription=sub, defaults={"kind": note.kind}
        )
        if created:
            ids.append(delivery.pk)
    return ids


def schedule(ids: list[int]) -> None:
    """Send queued pushes once the current transaction commits (nothing goes out for an action that rolled back)."""
    if ids:
        pending = list(ids)
        transaction.on_commit(lambda: send_now(pending), robust=True)


def send_now(ids: list[int]) -> None:
    started = time.monotonic()
    for index, pk in enumerate(ids):
        if index >= IMMEDIATE_LIMIT or time.monotonic() - started > IMMEDIATE_BUDGET_SECONDS:
            return  # the rest stay queued for send_pending
        deliver(pk)


def _refusal(d: PushDelivery, sub: PushSubscription, now) -> str:
    """Why this delivery must not be sent now (a final category), or ''."""
    if not enabled():
        return "push_off"
    if sub.disabled_at is not None:
        return "device_off"
    if sub.vapid_key_id != key_id():
        _disable(sub, PushSubscription.Reason.KEY)
        return "old_key"
    user = sub.member.user
    if d.notification_id:
        note = d.notification
        if note.user_id != user.pk or selectors.get_membership(user, note.organisation_id) is None:
            return "not_member"
        pref = NotificationPreference.objects.filter(user_id=user.pk).first()
        if pref is not None and not pref.wants_push(d.kind):
            return "preference_off"
    elif d.kind != TEST_KIND or selectors.get_membership(user) is None:
        return "not_member"
    if (now - d.created_at).total_seconds() > TTL_SECONDS:
        return "expired"
    if endpoint_problem(sub.endpoint):
        _disable(sub, PushSubscription.Reason.BLOCKED)
        return "blocked_endpoint"
    return ""


def _final_failure(d: PushDelivery, sub: PushSubscription, category: str) -> None:
    d.status = PushDelivery.Status.FAILED
    d.last_error = category
    d.attempts = max(d.attempts, PushDelivery.MAX_ATTEMPTS)
    d.save()
    sub.failure_count += 1
    sub.save(update_fields=["failure_count"])
    if sub.failure_count >= DISABLE_AFTER_FAILURES:
        _disable(sub, PushSubscription.Reason.FAILING)


def deliver(delivery_id: int, *, manual: bool = False) -> PushDelivery | None:
    """Attempt one push. Idempotent (a sent or cancelled delivery is returned untouched) and never raises.

    ``manual`` (staff "Retry now") may try once more after the automatic attempts ran out; every re-check in
    ``_refusal`` still applies (membership, preference, device state, key, one-day expiry, allowlist)."""
    try:
        with transaction.atomic():
            d = (
                PushDelivery.objects.select_for_update(of=("self",))
                .select_related("subscription__member__user", "notification")
                .get(pk=delivery_id)
            )
            if d.status == PushDelivery.Status.SENT or d.last_error == PushDelivery.CANCELLED_ERROR:
                return d
            if not manual and d.attempts >= PushDelivery.MAX_ATTEMPTS:
                return d
            sub = d.subscription
            now = timezone.now()
            refusal = _refusal(d, sub, now)
            if refusal:
                d.status = PushDelivery.Status.FAILED
                d.last_error = refusal
                d.attempts = max(d.attempts, PushDelivery.MAX_ATTEMPTS)
                d.save()
                return d
            try:
                body = encrypt(_payload(d), b64url_decode(sub.p256dh), b64url_decode(sub.auth))
                headers = {
                    "Authorization": vapid_authorization(sub.endpoint),
                    "Content-Encoding": "aes128gcm",
                    "Content-Type": "application/octet-stream",
                    "TTL": str(TTL_SECONDS),
                    "Urgency": "normal",
                    "Topic": f"portal-{d.kind}"[:32],
                    "User-Agent": USER_AGENT,
                }
            except (ValueError, PushError):
                _final_failure(d, sub, "bad_keys")
                return d
            d.attempts += 1
            retry_after = None
            try:
                result = _send_http(sub.endpoint, body, headers, TIMEOUT_SECONDS)
            except TimeoutError:
                outcome, category = "retry", "timeout"
            except urllib.error.URLError as exc:
                timed_out = isinstance(exc.reason, TimeoutError)
                outcome, category = "retry", "timeout" if timed_out else "network"
            except (OSError, http.client.HTTPException, ValueError):
                outcome, category = "retry", "network"
            else:
                outcome, category = _classify(result.status)
                retry_after = result.retry_after
            if outcome == "sent":
                d.status = PushDelivery.Status.SENT
                d.sent_at = now
                d.last_error = ""
                d.save()
                sub.last_success_at = now
                sub.failure_count = 0
                sub.save(update_fields=["last_success_at", "failure_count"])
                return d
            if outcome == "gone":
                d.status = PushDelivery.Status.FAILED
                d.last_error = category
                d.attempts = max(d.attempts, PushDelivery.MAX_ATTEMPTS)
                d.save()
                _disable(sub, PushSubscription.Reason.GONE)
                record(
                    "portal.push_disabled",
                    entity=sub,
                    summary=f"The push service ended a subscription ({sub.label})",
                )
                return d
            retryable = outcome == "retry" and d.kind != TEST_KIND
            if retryable and d.attempts < PushDelivery.MAX_ATTEMPTS:
                delay = RETRY_DELAYS_SECONDS[min(d.attempts, len(RETRY_DELAYS_SECONDS)) - 1]
                if retry_after:
                    delay = max(delay, min(retry_after, MAX_RETRY_AFTER_SECONDS))
                d.status = PushDelivery.Status.FAILED
                d.last_error = category
                d.next_attempt_at = now + timedelta(seconds=delay)
                d.save()
                logger.warning("portal push will be retried", extra={"delivery": d.pk, "error": category})
                return d
            _final_failure(d, sub, category)
            logger.warning("portal push failed", extra={"delivery": d.pk, "error": category})
            return d
    except PushDelivery.DoesNotExist:
        return None
    except Exception:  # noqa: BLE001 - e.g. database trouble: the action that queued this must still succeed
        logger.exception("portal push delivery crashed", extra={"delivery": delivery_id})
        return None


def send_pending(limit: int = 100) -> dict:
    """Bounded retry of queued and failed pushes that are due and under the attempt cap."""
    if not enabled():
        return {"attempted": 0, "sent": 0, "failed": 0}
    due = list(
        PushDelivery.objects.filter(
            status__in=[PushDelivery.Status.QUEUED, PushDelivery.Status.FAILED],
            attempts__lt=PushDelivery.MAX_ATTEMPTS,
            next_attempt_at__lte=timezone.now(),
        )
        .order_by("next_attempt_at", "pk")
        .values_list("pk", flat=True)[:limit]
    )
    sent = failed = 0
    for pk in due:
        result = deliver(pk)
        if result is None:
            continue
        if result.status == PushDelivery.Status.SENT:
            sent += 1
        else:
            failed += 1
    return {"attempted": len(due), "sent": sent, "failed": failed}


TEST_RESULTS = {
    "": "Sent. It should appear on this device in a few seconds.",
    "gone": "This device's subscription has ended. Turn notifications off, then on again.",
    "old_key": "Notifications need turning on again on this device.",
    "unauthorised": "The push service didn't accept the notification. Turn notifications off, then on again.",
    "rate_limited": "The push service is busy. Try again in a few minutes.",
    "push_off": "Notifications on this device aren't available yet.",
}
TEST_FAILED = "The push service didn't answer. Try again in a few minutes."


def send_test(sub: PushSubscription, *, request=None) -> tuple[bool, str]:
    """Send the member's own test notification to one of their devices, straight away. (ok, message)"""
    delivery = PushDelivery.objects.create(subscription=sub, kind=TEST_KIND)
    record(
        "portal.push_test",
        request=request,
        actor=sub.member.user,
        entity=sub,
        summary=f"Sent a test notification: {sub.label}",
    )
    result = deliver(delivery.pk)
    if result is not None and result.status == PushDelivery.Status.SENT:
        return True, TEST_RESULTS[""]
    category = result.last_error if result is not None else ""
    return False, TEST_RESULTS.get(category, TEST_FAILED) if category else TEST_FAILED


def page_context(user) -> dict:
    """What Account › Notifications on this device needs for its card and the device list."""
    listed = list(devices(user))
    for sub in listed:
        sub.digest = endpoint_digest(sub.endpoint)
    return {
        "available": enabled(),
        "public_key": public_key(),
        "devices": listed,
        "digests": ",".join(sub.digest for sub in listed),
    }
