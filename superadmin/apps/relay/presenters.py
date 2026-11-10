"""Turn admin API data into what the templates show: labels, times and status nodes.

Presentation only. Nothing here decides what may happen to a conversation; the website does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .client import user_id_from_admin_id

STATUS_WAITING = "awaiting_human"
STATUS_HUMAN = "human"
STATUS_AI = "ai"
STATUS_CLOSED = "closed"

TABS = (("needs", "Needs a person"), ("live", "Live"), ("ai", "AI"), ("closed", "Closed"))
TAB_KEYS = tuple(key for key, _ in TABS)

TAG_LABELS = {
    "NOT_HELPFUL": "NOT HELPFUL",
    "NOT_IN_KNOWLEDGE": "NOT IN KNOWLEDGE",
    "ASKED_FOR_A_PERSON": "ASKED FOR A PERSON",
    "MODEL_FLAG": "FLAGGED BY AI",
}


@dataclass(frozen=True)
class Trigger:
    tag: str  # mono tag, as on the toast and list
    detail: str  # bell detail line
    sentence: str  # email and context line; {first} is the visitor's first name
    label: str  # email "Trigger" row


TRIGGERS = {
    "not_helpful": Trigger(
        "NOT HELPFUL",
        "Marked an answer not helpful",
        "{first} marked an AI answer as not helpful and asked to talk to a person.",
        "Not helpful, then asked for a person",
    ),
    "explicit_request": Trigger(
        "ASKED FOR A PERSON",
        "Asked to talk to a person",
        "{first} asked to talk to a person.",
        "Asked for a person",
    ),
    "low_confidence": Trigger(
        "NOT IN KNOWLEDGE",
        "The site assistant had no answer in knowledge",
        "The site assistant could not answer from published knowledge.",
        "Not in published knowledge",
    ),
    "model_flag": Trigger(
        "FLAGGED BY AI",
        "The AI flagged the conversation for a person",
        "The AI flagged the conversation for a person.",
        "Flagged by the AI",
    ),
    "admin_initiated": Trigger(
        "STARTED BY STAFF",
        "A colleague asked for a person",
        "A colleague asked for a person to join.",
        "Started by staff",
    ),
}
DEFAULT_TRIGGER = Trigger("NEEDS A PERSON", "Asked for a person", "{first} needs a person.", "Needs a person")


def trigger(key: str | None) -> Trigger:
    return TRIGGERS.get(key or "", DEFAULT_TRIGGER)


def parse_time(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = parse_datetime(value)
    except ValueError:
        return None
    if parsed is not None and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, UTC)
    return parsed


def local(moment: datetime | None) -> datetime | None:
    return timezone.localtime(moment) if moment else None


def clock(value) -> str:
    """``14:24`` in Europe/London."""
    moment = local(parse_time(value))
    return moment.strftime("%H:%M") if moment else ""


def long_date(value) -> str:
    """``14:24 BST, 15 October 2026`` in Europe/London."""
    moment = local(parse_time(value))
    if moment is None:
        return ""
    return f"{moment:%H:%M} {moment.tzname()}, {moment.day} {moment:%B %Y}"


def _minutes(delta: timedelta) -> int:
    return max(int(delta.total_seconds() // 60), 0)


def short_age(since, now: datetime | None = None) -> str:
    """``4M``, ``3H``, ``2D``: the mono status column."""
    moment = parse_time(since)
    if moment is None:
        return ""
    minutes = _minutes((now or timezone.now()) - moment)
    if minutes < 60:
        return f"{max(minutes, 1)}M"
    if minutes < 48 * 60:
        return f"{minutes // 60}H"
    return f"{minutes // (24 * 60)}D"


def long_age(since, now: datetime | None = None) -> str:
    """``4 min``, ``3 h``, ``2 days``."""
    moment = parse_time(since)
    if moment is None:
        return ""
    minutes = _minutes((now or timezone.now()) - moment)
    if minutes < 60:
        return f"{max(minutes, 1)} min"
    if minutes < 48 * 60:
        return f"{minutes // 60} h"
    return f"{minutes // (24 * 60)} days"


def first_name(display_name: str | None) -> str:
    """ "Alex" for "Alex Morgan"; "The visitor" for "Visitor 8C1D" or nothing."""
    name = (display_name or "").strip()
    if not name or name.startswith("Visitor "):
        return "The visitor"
    return name.split()[0]


def page_path(value: str | None) -> str:
    if not value:
        return ""
    parts = urlsplit(value)
    return (parts.path or "/") if parts.scheme else value


def node(status: str) -> str:
    """Status node: filled mineral = person live, ring = waiting, cobalt dot = AI, grey ring = closed."""
    return {STATUS_WAITING: "waiting", STATUS_HUMAN: "live", STATUS_AI: "ai"}.get(status, "closed")


def row(item: dict, now: datetime | None = None) -> dict:
    """One line of the conversation list."""
    now = now or timezone.now()
    status = item.get("status") or ""
    assigned = item.get("assigned") or None
    if status == STATUS_WAITING:
        label, tone = f"WAITING {short_age(item.get('waitingSince'), now)}".strip(), "mineral"
    elif status == STATUS_HUMAN:
        label, tone = f"LIVE · {assigned['initials']}" if assigned else "LIVE", "muted"
    elif status == STATUS_AI:
        label, tone = f"AI · {short_age(item.get('lastMessageAt'), now)}".strip(" ·"), "muted"
    else:
        label, tone = "CLOSED", "muted"
    tags = [TAG_LABELS.get(tag, tag.replace("_", " ")) for tag in item.get("tags") or []]
    last = item.get("lastMessage") or {}
    return {
        "id": item.get("id"),
        "name": item.get("displayName") or "Visitor",
        "status": status,
        "node": node(status),
        "status_label": label,
        "status_tone": tone,
        "last_message": last.get("body") or "",
        "tag": tags[0] if tags else "",
        "page_path": item.get("pagePath") or "",
        "emphasis": status in (STATUS_WAITING, STATUS_HUMAN),
    }


SYSTEM_LABELS = {
    "admin_joined": "{name} JOINED",
    "ai_paused": "RELAY AI PAUSED",
    "ai_back": "RELAY AI IS BACK",
    "closed": "CONVERSATION CLOSED",
}


def system_label(message: dict) -> str:
    meta = message.get("meta") or {}
    key = message.get("body") or ""
    at = clock(message.get("createdAt"))
    if key == "handoff_requested":
        consent = " · CONSENT GIVEN" if meta.get("consent") else ""
        return f"HANDOFF REQUESTED · {at}{consent}"
    template = SYSTEM_LABELS.get(key)
    if template is None:
        return f"{key.replace('_', ' ').upper()} · {at}".strip(" ·")
    name = (meta.get("name") or message.get("adminName") or "A colleague").upper()
    label = f"{template.format(name=name)} · {at}"
    if key == "closed":
        # The visitor's review of the whole conversation, given after it closed.
        rating = message.get("feedback")
        if rating == 1:
            label += " · VISITOR RATED IT HELPFUL"
        elif rating == -1:
            label += " · VISITOR RATED IT NOT HELPFUL"
    return label


def message(item: dict) -> dict:
    """One entry in the thread. ``head`` is the strong part of the mono label, ``tail`` the rest."""
    sender = item.get("senderType") or "system"
    at = clock(item.get("createdAt"))
    entry = {
        "id": item.get("id"),
        "kind": sender,
        "body": item.get("body") or "",
        "created_at": item.get("createdAt") or "",
        "time": at,
        "head": "",
        "tail": at,
        "label": "",
        "flag": "",
        "citations": [],
    }
    if sender == "visitor":
        entry["label"] = f"VISITOR · {at}"
    elif sender == "ai":
        parts = [at]
        citations = [c for c in item.get("citations") or [] if isinstance(c, dict)]
        if citations:
            parts.append(f"{len(citations)} SOURCE{'S' if len(citations) != 1 else ''}")
        if item.get("latencyMs"):
            parts.append(f"{item['latencyMs'] / 1000:.1f}S")
        entry["head"] = "RELAY · AI"
        entry["tail"] = " · ".join(part for part in parts if part)
        entry["flag"] = "MARKED NOT HELPFUL" if item.get("feedback") == -1 else ""
        entry["citations"] = [
            {"n": c.get("n"), "title": c.get("title") or "", "url": c.get("url") or ""} for c in citations
        ]
    elif sender == "admin":
        entry["head"] = (item.get("adminName") or "Vitalos").upper()
    elif sender == "note":
        entry["head"] = f"NOTE · {(item.get('adminName') or 'Vitalos').upper()}"
    else:
        entry["kind"] = "system"
        entry["label"] = system_label(item)
    entry["label"] = entry["label"] or " · ".join(part for part in (entry["head"], entry["tail"]) if part)
    return entry


def thread_status(conversation: dict, now: datetime | None = None) -> tuple[str, str]:
    """(label, tone) for the thread header's mono status line."""
    status = conversation.get("status") or ""
    assigned = conversation.get("assigned") or None
    if status == STATUS_WAITING:
        since = (conversation.get("handoff") or {}).get("requestedAt")
        wait = long_age(since, now).upper()
        return (f"NEEDS A PERSON · WAITING {wait}" if wait else "NEEDS A PERSON"), "mineral"
    if status == STATUS_HUMAN:
        return (f"LIVE · {assigned['name'].upper()}" if assigned else "LIVE"), "mineral"
    if status == STATUS_AI:
        return "RELAY AI IS ANSWERING", "muted"
    closed = clock(conversation.get("closedAt"))
    return (f"CLOSED · {closed}" if closed else "CLOSED"), "muted"


def thread(conversation: dict, messages: list[dict], user, now: datetime | None = None) -> dict:
    status = conversation.get("status") or ""
    assigned = conversation.get("assigned") or None
    mine = bool(assigned) and user_id_from_admin_id(assigned.get("id")) == user.pk
    label, tone = thread_status(conversation, now)
    entries = [message(item) for item in messages]
    last_admin = next((m for m in reversed(entries) if m["kind"] == "admin"), None)
    last = entries[-1]["created_at"] if entries else ""
    first = first_name(conversation.get("displayName"))
    return {
        "id": conversation.get("id"),
        "name": conversation.get("displayName") or "Visitor",
        "first_name": first,
        "visitor_ref": "the visitor" if first == "The visitor" else first,
        "has_email": bool((conversation.get("contact") or {}).get("email")),
        "status": status,
        "status_label": label,
        "status_tone": tone,
        "assigned": assigned,
        "assigned_id": (assigned or {}).get("id", ""),
        "is_mine": mine,
        "is_closed": status == STATUS_CLOSED,
        "is_live": status == STATUS_HUMAN,
        "can_join": status in (STATUS_WAITING, STATUS_AI) or (status == STATUS_HUMAN and not mine),
        "can_hand_back": status == STATUS_HUMAN,
        "joined": status == STATUS_HUMAN and mine,
        "messages": entries,
        "last_message_at": last,
        "last_admin_message_id": last_admin["id"] if last_admin else "",
    }


def context(
    conversation: dict, alerts: dict, relay_settings: dict | None, now: datetime | None = None
) -> dict:
    """The context panel: contact, AI summary, session and the ALERTS sentence."""
    now = now or timezone.now()
    contact = conversation.get("contact") or None
    session = conversation.get("session") or {}
    handoff = conversation.get("handoff") or None
    consent = ""
    if contact and contact.get("consentAt"):
        version = contact.get("noticeVersion")
        consent = f"Consent to contact · {clock(contact['consentAt'])}" + (
            f" · notice v{version}" if version else ""
        )
    started = clock(session.get("startedAt"))
    count = session.get("messageCount")
    started_text = " · ".join(
        part
        for part in (started, f"{count} message{'s' if count != 1 else ''}" if count is not None else "")
        if part
    )
    return {
        "contact": contact,
        "consent": consent,
        "summary": conversation.get("summary") or "",
        "session": [
            ("Page", page_path(session.get("pageUrl")) or conversation.get("pagePath") or "", True),
            ("Referrer", session.get("referrer") or "", False),
            ("Device", session.get("device") or "", False),
            ("Country", session.get("country") or "", False),
            ("Started", started_text, False),
        ],
        "alerts": alerts_sentence(conversation, alerts, relay_settings, now),
        "trigger": trigger((handoff or {}).get("trigger")) if handoff else None,
    }


def alerts_sentence(conversation: dict, alerts: dict, relay_settings: dict | None, now: datetime) -> str:
    """ "In-app sent to 2 admins at 14:24. Email sent at 14:24. Next reminder at 14:39 if no one joins.\""""
    parts = []
    if alerts.get("in_app_at"):
        count = alerts.get("in_app_recipients") or 0
        noun = "admin" if count == 1 else "admins"
        parts.append(f"In-app sent to {count} {noun} at {clock(alerts['in_app_at'])}.")
    if alerts.get("email_at"):
        parts.append(f"Email sent at {clock(alerts['email_at'])}.")
    handoff = conversation.get("handoff") or {}
    requested = parse_time(handoff.get("requestedAt"))
    if conversation.get("status") == STATUS_WAITING and requested and relay_settings:
        reminders = alerts.get("reminders") or 0
        key = "reminderMinutes" if reminders == 0 else "secondReminderMinutes" if reminders == 1 else ""
        minutes = relay_settings.get(key) if key else None
        if isinstance(minutes, int) and minutes > 0:
            due = requested + timedelta(minutes=minutes)
            if due > now:
                parts.append(f"Next reminder at {clock(due)} if no one joins.")
    return " ".join(parts) or "No alerts sent for this conversation."
