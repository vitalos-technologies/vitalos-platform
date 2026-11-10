"""Relay actions: forward to the website's admin API as the signed-in admin, then audit.

Django does not decide whether an action is allowed for a conversation's state; the website does and
answers 409 when it is not. Django checks only who may act (roles) and records what was done.
Audit summaries never contain message text or a visitor's email address.
"""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.audit.services import record

from . import alerts, selectors
from .client import admin_identity, get_client
from .models import RelayInboxState

CONVERSATION = "relay.conversation"
DOCUMENT = "relay.document"
SETTINGS_CACHE_KEY = "relay:settings"
SETTINGS_CACHE_SECONDS = 300
REALTIME_CACHE_KEY = "relay:realtime"
REALTIME_CACHE_SECONDS = 6 * 60 * 60


def _require_access(user) -> None:
    if not selectors.can_access(user):
        raise PermissionDenied


def _require_manage(user) -> None:
    if not selectors.can_manage(user):
        raise PermissionDenied


def _audit(action, request, entity_type, entity_id, summary, **meta) -> None:
    record(
        action, request=request, entity_type=entity_type, entity_id=str(entity_id), summary=summary, **meta
    )


# --- Conversations -------------------------------------------------------------------------------


def join(user, conversation_id, request=None) -> dict:
    _require_access(user)
    data = get_client(user).join(conversation_id)
    _audit("relay.joined", request, CONVERSATION, conversation_id, "Joined a site assistant conversation")
    return data


def assign(user, conversation_id, assignee, request=None) -> dict:
    _require_access(user)
    if not selectors.can_access(assignee) or not assignee.is_active:
        raise PermissionDenied
    data = get_client(user).assign(conversation_id, admin_identity(assignee))
    _audit(
        "relay.assigned",
        request,
        CONVERSATION,
        conversation_id,
        f"Assigned a site assistant conversation to {assignee.email}",
        assignee=f"sa:{assignee.pk}",
    )
    return data


def hand_back(user, conversation_id, request=None) -> dict:
    _require_access(user)
    data = get_client(user).handback(conversation_id)
    _audit(
        "relay.handed_back", request, CONVERSATION, conversation_id, "Handed a conversation back to the AI"
    )
    return data


def close(user, conversation_id, request=None) -> dict:
    _require_access(user)
    data = get_client(user).close(conversation_id)
    _audit("relay.closed", request, CONVERSATION, conversation_id, "Closed a site assistant conversation")
    return data


def reply(user, conversation_id, text, client_message_id, email_if_away, request=None) -> dict:
    _require_access(user)
    data = get_client(user).reply(conversation_id, text, client_message_id, email_if_away)
    _audit(
        "relay.replied",
        request,
        CONVERSATION,
        conversation_id,
        "Replied in a site assistant conversation",
        characters=len(text),
        emailed=bool((data or {}).get("emailed")),
    )
    return data


def note(user, conversation_id, text, request=None) -> dict:
    _require_access(user)
    data = get_client(user).note(conversation_id, text)
    _audit(
        "relay.noted", request, CONVERSATION, conversation_id, "Added an internal note", characters=len(text)
    )
    return data


def typing(user, conversation_id) -> bool:
    """Forward a typing ping at most every 3 seconds per admin and conversation. No audit."""
    _require_access(user)
    if not cache.add(f"relay:typing:{user.pk}:{conversation_id}", 1, timeout=3):
        return False
    get_client(user).typing(conversation_id)
    return True


def delete(user, conversation_id, request=None) -> dict:
    _require_access(user)
    data = get_client(user).delete(conversation_id)
    _audit("relay.deleted", request, CONVERSATION, conversation_id, "Deleted a site assistant conversation")
    return data


def transcript(user, conversation_id, request=None) -> str:
    _require_access(user)
    text = str((get_client(user).transcript(conversation_id) or {}).get("text") or "")
    _audit(
        "relay.transcript_copied",
        request,
        CONVERSATION,
        conversation_id,
        "Copied a site assistant transcript",
    )
    return text


def save_to_knowledge(user, conversation_id, message_id, request=None) -> str:
    _require_access(user)
    document_id = str(
        (get_client(user).save_to_knowledge(conversation_id, message_id) or {}).get("documentId") or ""
    )
    _audit(
        "relay.knowledge_saved",
        request,
        DOCUMENT,
        document_id,
        "Saved a reply to site assistant knowledge as a draft",
        conversation=str(conversation_id),
    )
    return document_id


def set_availability(user, available: bool, request=None, *, heartbeat: bool = False) -> dict:
    """POST /presence. The 60-second heartbeat repeats the current value and is not audited."""
    _require_access(user)
    data = get_client(user).set_presence(available)
    if not heartbeat:
        _audit(
            "relay.availability_changed",
            request,
            "accounts.user",
            user.pk,
            "Available for the site assistant" if available else "Not available for the site assistant",
            available=bool(available),
        )
    return data


# --- Knowledge -----------------------------------------------------------------------------------


def create_document(user, fields: dict, request=None) -> dict:
    _require_access(user)
    document = (get_client(user).create_document(fields) or {}).get("document") or {}
    _audit(
        "relay.knowledge_saved",
        request,
        DOCUMENT,
        document.get("id", ""),
        "Added a draft site assistant knowledge entry",
    )
    return document


def update_document(user, document_id, fields: dict, request=None) -> dict:
    _require_access(user)
    document = (get_client(user).update_document(document_id, fields) or {}).get("document") or {}
    _audit("relay.knowledge_saved", request, DOCUMENT, document_id, "Edited a site assistant knowledge entry")
    return document


def publish(user, document_id, request=None) -> dict:
    _require_manage(user)
    document = (get_client(user).publish(document_id) or {}).get("document") or {}
    _audit(
        "relay.knowledge_published",
        request,
        DOCUMENT,
        document_id,
        "Published a site assistant knowledge entry",
    )
    return document


def archive(user, document_id, request=None) -> dict:
    _require_manage(user)
    document = (get_client(user).archive(document_id) or {}).get("document") or {}
    _audit(
        "relay.knowledge_archived",
        request,
        DOCUMENT,
        document_id,
        "Archived a site assistant knowledge entry",
    )
    return document


def reindex(user, document_id, request=None) -> dict:
    _require_manage(user)
    document = (get_client(user).reindex(document_id) or {}).get("document") or {}
    _audit("relay.reindexed", request, DOCUMENT, document_id, "Re-indexed a site assistant knowledge entry")
    return document


def reindex_all(user, request=None) -> dict:
    _require_manage(user)
    data = get_client(user).reindex_all() or {}
    _audit(
        "relay.reindexed",
        request,
        DOCUMENT,
        "all",
        "Re-indexed all site assistant knowledge",
        documents=data.get("documents"),
        chunks=data.get("chunks"),
    )
    return data


def faq_sync(user, full: bool = False, request=None) -> dict:
    _require_manage(user)
    run = (get_client(user).faq_sync(full) or {}).get("run") or {}
    _audit("relay.faq_synced", request, DOCUMENT, "faq", "Synced the Master FAQ", full=bool(full))
    return run


# --- Settings ------------------------------------------------------------------------------------


def relay_settings(user, *, fresh: bool = False) -> dict | None:
    """RelaySettings, cached for 5 minutes (used for reminder times and labels). None if unreachable."""
    from .client import RelayError

    cached = None if fresh else cache.get(SETTINGS_CACHE_KEY)
    if cached is not None:
        return cached
    try:
        value = (get_client(user).get_settings() or {}).get("settings")
    except RelayError:
        return None
    if isinstance(value, dict):
        cache.set(SETTINGS_CACHE_KEY, value, SETTINGS_CACHE_SECONDS)
        return value
    return None


def save_settings(user, current: dict, changes: dict, request=None) -> dict:
    """Full replace (PUT): ``changes`` on top of ``current``, so keys the form does not show survive."""
    _require_manage(user)
    merged = {**current, **changes}
    saved = (get_client(user).put_settings(merged) or {}).get("settings") or merged
    changed = sorted(key for key in changes if current.get(key) != changes[key])
    cache.set(SETTINGS_CACHE_KEY, saved, SETTINGS_CACHE_SECONDS)
    _audit(
        "relay.settings_changed",
        request,
        "relay.settings",
        "settings",
        "Changed site assistant settings: " + (", ".join(changed) if changed else "no changes"),
        changed=changed,
    )
    return saved


def new_client_message_id() -> str:
    return str(uuid.uuid4())


# --- Badge and realtime --------------------------------------------------------------------------

BADGE_STALE = timedelta(seconds=60)


def badge_count(user) -> int:
    """Needs-a-person count from the local state; refreshed from the API at most once a minute."""
    from .client import RelayError

    state = RelayInboxState.load()
    stale = state.updated_at is None or timezone.now() - state.updated_at > BADGE_STALE
    if stale and cache.add("relay:badge-refresh", 1, timeout=int(BADGE_STALE.total_seconds())):
        try:
            data = get_client(user).inbox(tab="needs") or {}
        except RelayError:
            return state.needs
        alerts.update_counts(data.get("counts"))
        remember_realtime(data.get("realtime"))
        state.refresh_from_db()
    return state.needs


def remember_realtime(realtime) -> dict | None:
    """Keep the inbox's realtime details (URL, publishable key, channel) for every Relay page."""
    config = realtime_from(realtime)
    if config:
        cache.set(REALTIME_CACHE_KEY, config, REALTIME_CACHE_SECONDS)
    return config


def realtime_from(realtime) -> dict | None:
    """Validated {socket, origin, key, topic} for relay.js, or None. Only https projects are accepted."""
    if not isinstance(realtime, dict):
        return None
    url = str(realtime.get("url") or "").rstrip("/")
    key = str(realtime.get("key") or "")
    channel = str(realtime.get("channel") or "")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc or parts.path not in ("", "/") or not key:
        return None
    # The website derives the admin topic from the shared secret; never fall back to a fixed name.
    if not re.fullmatch(r"relay:a:[0-9a-f]{40}", channel):
        return None
    origin = f"wss://{parts.netloc}"
    socket = f"{origin}/realtime/v1/websocket?" + urlencode({"apikey": key, "vsn": "1.0.0"})
    return {"socket": socket, "origin": origin, "topic": f"realtime:{channel}"}


def realtime_config() -> dict | None:
    return cache.get(REALTIME_CACHE_KEY)
