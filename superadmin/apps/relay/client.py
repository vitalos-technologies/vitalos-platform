"""Client for the website's signed Relay admin API (docs/relay/API.md, base ``/api/relay/admin``).

Django only presents and forwards: every rule about conversations (status transitions, who may reply,
retention) is enforced by the website. Each request carries the signed-in admin as ``X-Relay-Admin``;
Django has already authenticated and authorised that admin before calling.

``HttpRelayClient`` talks to the website. ``FakeRelayClient`` (``apps/relay/fake.py``) keeps sample data
in memory for tests and local UI work (``RELAY_CLIENT=fake``). ``get_client(user)`` picks one.
Request and response bodies are never logged.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Protocol

from django.conf import settings

from apps.accounts.roles import is_superadmin

from . import signing

logger = logging.getLogger(__name__)

API_PREFIX = "/api/relay/admin"
TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
USER_AGENT = "vitalos-superadmin-relay/1.0"

ERROR_MESSAGES = {
    "not_configured": "The site assistant is not connected yet. Ask a super admin to set the RELAY_API_* settings.",
    "unavailable": "The site assistant could not be reached. Try again in a moment.",
    "timeout": "The site assistant took too long to answer. Try again in a moment.",
    "bad_response": "The site assistant sent an unexpected answer. Try again in a moment.",
    "bad_signature": "The site assistant refused the request signature. Check RELAY_ADMIN_API_SECRET on both apps.",
    "stale": "The site assistant refused the request time. Check the server clock.",
    "forbidden": "You do not have permission to do that.",
    "not_found": "That conversation or entry no longer exists.",
    "conflict": "That changed while you were looking at it. Refresh and try again.",
    "read_only": "This entry comes from its source and cannot be edited here.",
    "invalid": "The site assistant could not accept that. Check the fields and try again.",
    "disabled": "The site assistant is switched off on the website.",
}


class RelayError(Exception):
    """A failed admin API call. ``code`` is the API's error code; ``status`` the HTTP status (0: none)."""

    def __init__(self, code: str, status: int = 0, message: str = ""):
        self.code = code or "unavailable"
        self.status = status
        self.detail = message
        super().__init__(f"Relay API error {self.code} ({status})")

    @property
    def user_message(self) -> str:
        return ERROR_MESSAGES.get(self.code, ERROR_MESSAGES["unavailable"])


def _initials(user) -> str:
    name = (user.full_name or user.email.split("@")[0]).replace(".", " ").split()
    return "".join(part[0] for part in name[:2]).upper()[:4] or "?"


def admin_identity(user) -> dict[str, str]:
    """The ``X-Relay-Admin`` identity: ``{"id": "sa:<pk>", name, initials, email, role}``."""
    return {
        "id": f"sa:{user.pk}",
        "name": (user.full_name or user.email.split("@")[0])[:120],
        "initials": _initials(user),
        "email": user.email,
        "role": "SuperAdmin" if is_superadmin(user) else "ServiceLead",
    }


def encode_admin(identity: dict | None) -> str:
    """base64url (no padding) of compact UTF-8 JSON, or "" when there is no admin."""
    if not identity:
        return ""
    raw = json.dumps(identity, separators=(",", ":"), ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def user_id_from_admin_id(admin_id: str | None) -> int | None:
    """``"sa:12"`` -> 12; anything else -> None."""
    value = (admin_id or "").removeprefix("sa:")
    return int(value) if (admin_id or "").startswith("sa:") and value.isdigit() else None


class RelayClient(Protocol):
    """The admin API, one method per route. Every method returns the response's ``data``."""

    # Inbox and threads
    def inbox(self, tab: str = "needs", q: str = "", cursor: str = "") -> dict: ...
    def conversation(self, conversation_id: str) -> dict: ...
    def messages(self, conversation_id: str, after: str = "") -> dict: ...
    def join(self, conversation_id: str) -> dict: ...
    def assign(self, conversation_id: str, admin: dict) -> dict: ...
    def handback(self, conversation_id: str) -> dict: ...
    def close(self, conversation_id: str) -> dict: ...
    def reply(self, conversation_id: str, text: str, client_message_id: str, email_if_away: bool) -> dict: ...
    def note(self, conversation_id: str, text: str) -> dict: ...
    def typing(self, conversation_id: str) -> dict: ...
    def delete(self, conversation_id: str) -> dict: ...
    def save_to_knowledge(self, conversation_id: str, message_id: str) -> dict: ...
    def transcript(self, conversation_id: str) -> dict: ...
    # Presence
    def set_presence(self, available: bool) -> dict: ...
    def presence(self) -> dict: ...
    # Knowledge
    def knowledge(self, source: str = "", status: str = "", section: str = "", q: str = "") -> dict: ...
    def document(self, document_id: str) -> dict: ...
    def create_document(self, fields: dict) -> dict: ...
    def update_document(self, document_id: str, fields: dict) -> dict: ...
    def publish(self, document_id: str) -> dict: ...
    def archive(self, document_id: str) -> dict: ...
    def reindex(self, document_id: str) -> dict: ...
    def reindex_all(self) -> dict: ...
    def gaps(self, days: int = 30) -> dict: ...
    def ignore_gap(self, gap_id: str) -> dict: ...
    def test_retrieval(self, question: str, page_path: str = "") -> dict: ...
    def faq(self) -> dict: ...
    def faq_sync(self, full: bool = False) -> dict: ...
    # Insights, settings, email log
    def insights(self, days: int = 30) -> dict: ...
    def get_settings(self) -> dict: ...
    def put_settings(self, relay_settings: dict) -> dict: ...
    def email_log(self) -> dict: ...


def _id(value) -> str:
    """Path segments are always canonical uuids (the URL routes also require them)."""
    return str(uuid.UUID(str(value)))


class AdminApiMixin:
    """Maps each named method onto ``self._call(method, path, query, body)``."""

    def _call(self, method: str, path: str, query: dict | None = None, body: dict | None = None) -> Any:
        raise NotImplementedError

    def inbox(self, tab="needs", q="", cursor=""):
        return self._call("GET", "/inbox", {"tab": tab, "q": q, "cursor": cursor})

    def conversation(self, conversation_id):
        return self._call("GET", f"/conversations/{_id(conversation_id)}")

    def messages(self, conversation_id, after=""):
        return self._call("GET", f"/conversations/{_id(conversation_id)}/messages", {"after": after})

    def join(self, conversation_id):
        return self._call("POST", f"/conversations/{_id(conversation_id)}/join", body={})

    def assign(self, conversation_id, admin):
        target = {key: admin[key] for key in ("id", "name", "initials")}
        return self._call("POST", f"/conversations/{_id(conversation_id)}/assign", body={"admin": target})

    def handback(self, conversation_id):
        return self._call("POST", f"/conversations/{_id(conversation_id)}/handback", body={})

    def close(self, conversation_id):
        return self._call("POST", f"/conversations/{_id(conversation_id)}/close", body={})

    def reply(self, conversation_id, text, client_message_id, email_if_away):
        body = {"text": text, "clientMessageId": _id(client_message_id), "emailIfAway": bool(email_if_away)}
        return self._call("POST", f"/conversations/{_id(conversation_id)}/reply", body=body)

    def note(self, conversation_id, text):
        return self._call("POST", f"/conversations/{_id(conversation_id)}/note", body={"text": text})

    def typing(self, conversation_id):
        return self._call("POST", f"/conversations/{_id(conversation_id)}/typing", body={})

    def delete(self, conversation_id):
        return self._call("DELETE", f"/conversations/{_id(conversation_id)}")

    def save_to_knowledge(self, conversation_id, message_id):
        body = {"messageId": _id(message_id)}
        return self._call("POST", f"/conversations/{_id(conversation_id)}/save-to-knowledge", body=body)

    def transcript(self, conversation_id):
        return self._call("GET", f"/conversations/{_id(conversation_id)}/transcript")

    def set_presence(self, available):
        return self._call("POST", "/presence", body={"available": bool(available)})

    def presence(self):
        return self._call("GET", "/presence")

    def knowledge(self, source="", status="", section="", q=""):
        return self._call(
            "GET", "/knowledge", {"source": source, "status": status, "section": section, "q": q}
        )

    def document(self, document_id):
        return self._call("GET", f"/knowledge/{_id(document_id)}")

    def create_document(self, fields):
        return self._call("POST", "/knowledge", body=fields)

    def update_document(self, document_id, fields):
        return self._call("PATCH", f"/knowledge/{_id(document_id)}", body=fields)

    def publish(self, document_id):
        return self._call("POST", f"/knowledge/{_id(document_id)}/publish", body={})

    def archive(self, document_id):
        return self._call("POST", f"/knowledge/{_id(document_id)}/archive", body={})

    def reindex(self, document_id):
        return self._call("POST", f"/knowledge/{_id(document_id)}/reindex", body={})

    def reindex_all(self):
        return self._call("POST", "/knowledge/reindex-all", body={})

    def gaps(self, days=30):
        return self._call("GET", "/knowledge/gaps", {"days": str(int(days))})

    def ignore_gap(self, gap_id):
        return self._call("POST", f"/knowledge/gaps/{_id(gap_id)}/ignore", body={})

    def test_retrieval(self, question, page_path=""):
        body = {"question": question}
        if page_path:
            body["pagePath"] = page_path
        return self._call("POST", "/knowledge/test", body=body)

    def faq(self):
        return self._call("GET", "/knowledge/faq")

    def faq_sync(self, full=False):
        return self._call("POST", "/knowledge/faq/sync", body={"full": bool(full)})

    def insights(self, days=30):
        return self._call("GET", "/insights", {"days": str(int(days))})

    def get_settings(self):
        return self._call("GET", "/settings")

    def put_settings(self, relay_settings):
        return self._call("PUT", "/settings", body={"settings": relay_settings})

    def email_log(self):
        return self._call("GET", "/email-log")


class HttpRelayClient(AdminApiMixin):
    """Signed HTTPS calls to the website (stdlib urllib, 8-second timeout)."""

    def __init__(self, base_url: str, secret: str, admin: dict | None = None, timeout: int = TIMEOUT_SECONDS):
        self.base_url = (base_url or "").rstrip("/")
        self.secret = secret or ""
        self.admin = admin
        self.timeout = timeout

    def build_request(
        self,
        method: str,
        path: str,
        query: dict | None = None,
        body: dict | None = None,
        now: float | None = None,
    ) -> urllib.request.Request:
        if not self.base_url or not self.secret:
            raise RelayError("not_configured")
        pairs = [(key, value) for key, value in (query or {}).items() if value not in ("", None)]
        url = f"{self.base_url}{API_PREFIX}{path}"
        if pairs:
            url += "?" + urllib.parse.urlencode(pairs)
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("https", "http") or not parts.netloc:
            raise RelayError("not_configured")
        path_with_query = parts.path + (f"?{parts.query}" if parts.query else "")
        raw = b"" if body is None else json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
        timestamp = str(int(now if now is not None else time.time()))
        admin_header = encode_admin(self.admin)
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "X-Relay-Timestamp": timestamp,
            "X-Relay-Signature": signing.sign(
                self.secret, signing.canonical(timestamp, method, path_with_query, admin_header, raw)
            ),
        }
        if admin_header:
            headers["X-Relay-Admin"] = admin_header
        if body is not None:
            headers["Content-Type"] = "application/json"
        # The URL is RELAY_API_BASE_URL (an operator setting, http or https only, checked above).
        return urllib.request.Request(  # noqa: S310
            url, data=raw if body is not None else None, method=method, headers=headers
        )

    def _call(self, method, path, query=None, body=None):
        request = self.build_request(method, path, query, body)
        log_path = API_PREFIX + path  # Never the query (it can hold a search) or a body.
        try:
            # The URL is built from RELAY_API_BASE_URL (operator setting), not from user input.
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310  # nosec B310
                status = response.status
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            code = "unavailable"
            try:
                payload = json.loads(exc.read(65536) or b"{}")
                code = str((payload.get("error") or {}).get("code") or "") or code
            except (ValueError, AttributeError, OSError):
                pass
            if exc.code == 404 and code == "unavailable":
                code = "not_found"
            logger.warning("Relay API error", extra={"path": log_path, "status": exc.code, "code": code})
            raise RelayError(code, exc.code) from None
        except TimeoutError:
            logger.warning("Relay API timeout", extra={"path": log_path})
            raise RelayError("timeout") from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            if isinstance(getattr(exc, "reason", None), TimeoutError):
                logger.warning("Relay API timeout", extra={"path": log_path})
                raise RelayError("timeout") from None
            logger.warning("Relay API unreachable", extra={"path": log_path, "error": type(exc).__name__})
            raise RelayError("unavailable") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise RelayError("bad_response", status)
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            raise RelayError("bad_response", status) from None
        if not isinstance(payload, dict) or "data" not in payload:
            raise RelayError("bad_response", status)
        return payload["data"]


def is_configured() -> bool:
    """Relay is switched on for this deployment (the tab shows, the webhook answers)."""
    return bool(settings.RELAY_API_BASE_URL) or settings.RELAY_CLIENT == "fake"


def get_client(user=None) -> RelayClient:
    """The client for ``user`` (signs as them), or an anonymous one (no ``X-Relay-Admin``)."""
    admin = admin_identity(user) if user is not None and user.is_authenticated else None
    if settings.RELAY_CLIENT == "fake":
        from .fake import FakeRelayClient

        return FakeRelayClient(admin)
    return HttpRelayClient(settings.RELAY_API_BASE_URL, settings.RELAY_ADMIN_API_SECRET, admin)
