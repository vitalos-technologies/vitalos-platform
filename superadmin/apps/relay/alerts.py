"""Turn website webhook events into Relay alerts: in-app rows, emails and the badge counts.

Rules:
- Recipients are active users who may use Relay. ``visitor.replied`` goes to the assigned admin when
  there is one, otherwise to everyone. Token cap and FAQ alerts go to SuperAdmins.
- Each person's grid (preferences.py) decides in-app and email per type.
- At most one email per conversation, type and recipient every 10 minutes (RelayAlertLog), and at most
  one digest, token cap or FAQ email per recipient a day.
- Emails stop at RESEND_DAILY_LIMIT for the day, counted with the enquiry emails (one Resend account).
The webhook answers within the website's 5-second budget: a handful of admins means a handful of sends.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from . import emails, preferences, presenters, selectors
from .models import (
    DIGEST,
    EMAIL,
    FAQ_ATTENTION,
    HANDOFF_REQUESTED,
    IN_APP,
    NO_ANSWER,
    REMINDER,
    TOKEN_CAP,
    VISITOR_REPLIED,
    RelayAlertLog,
    RelayInboxState,
    RelayNotification,
    bucket_for,
)

logger = logging.getLogger(__name__)

EMAIL_WINDOW = timedelta(minutes=10)
DAILY_TYPES = (DIGEST, TOKEN_CAP, FAQ_ATTENTION)
QUOTE_LIMIT = 280

# Webhook event type -> alert type.
EVENT_TYPES = {
    "handoff.requested": HANDOFF_REQUESTED,
    "visitor.replied": VISITOR_REPLIED,
    "handoff.reminder": REMINDER,
    "relay.no_answer": NO_ANSWER,
    "relay.token_cap": TOKEN_CAP,
    "faq.attention": FAQ_ATTENTION,
    "digest.daily": DIGEST,
}


@dataclass
class Alert:
    """What one event means for the people who hear about it."""

    kind: str
    recipients: list
    title: str = ""
    body: str = ""
    url: str = ""
    conversation_id: str | None = None
    meta: dict = field(default_factory=dict)
    email_options: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)  # the event's data, for the email


@dataclass
class Outcome:
    in_app: int = 0
    emails: int = 0
    skipped: int = 0


def update_counts(counts) -> None:
    """Store the website's counts for the sidebar badge (ignores anything malformed)."""
    if not isinstance(counts, dict):
        return
    values = {}
    for key in ("needs", "live"):
        value = counts.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            values[key] = value
    if not values:
        return
    RelayInboxState.load()
    RelayInboxState.objects.filter(pk=1).update(**values, updated_at=timezone.now())


CONVERSATION_TYPES = (HANDOFF_REQUESTED, VISITOR_REPLIED, REMINDER, NO_ANSWER)


def _uuid(value) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        return None


def _quote(text) -> str:
    return " ".join(str(text or "").split())[:QUOTE_LIMIT]


def _thread_url(conversation_id: str) -> str:
    return f"/relay/inbox/{conversation_id}/"


def _toast_meta(tag: str, page: str, quote: str = "") -> dict:
    return {"tag": tag, "page": page or "", "quote": quote}


def build_alert(event_type: str, data: dict) -> Alert | None:
    alert = _build_alert(event_type, data)
    if alert is not None:
        alert.data = data
    return alert


def _build_alert(event_type: str, data: dict) -> Alert | None:
    kind = EVENT_TYPES.get(event_type)
    if kind is None or not isinstance(data, dict):
        return None
    conversation_id = _uuid(data.get("conversationId"))
    if kind in CONVERSATION_TYPES and conversation_id is None:
        return None
    everyone = list(selectors.relay_users())
    name = data.get("displayName") or "A visitor"
    page = data.get("pagePath") or ""
    if kind == HANDOFF_REQUESTED:
        reason = presenters.trigger(data.get("trigger"))
        return Alert(
            kind,
            everyone,
            f"{name} needs a person",
            reason.detail,
            _thread_url(conversation_id),
            conversation_id,
            _toast_meta(reason.tag, page, _quote(data.get("lastVisitorMessage"))),
        )
    if kind == VISITOR_REPLIED:
        assignee = selectors.user_for_admin_id(data.get("assignedAdminId"))
        return Alert(
            kind,
            [assignee] if assignee else everyone,
            f"{name} replied",
            "Replied in your conversation" if assignee else "Replied in a live conversation",
            _thread_url(conversation_id),
            conversation_id,
            _toast_meta("VISITOR REPLIED", page, _quote(data.get("lastVisitorMessage"))),
            {"assigned": bool(assignee)},
        )
    if kind == REMINDER:
        minutes = int(data.get("minutesWaiting") or 0)
        return Alert(
            kind,
            everyone,
            f"No one has joined {name}",
            f"Reminder after {minutes} minutes" if minutes else "Reminder",
            _thread_url(conversation_id),
            conversation_id,
            _toast_meta("STILL WAITING", page, _quote(data.get("lastVisitorMessage"))),
        )
    if kind == NO_ANSWER:
        return Alert(
            kind,
            everyone,
            "The site assistant had no answer in knowledge",
            f"Question on {page}" if page else "A question the site assistant could not answer",
            _thread_url(conversation_id),
            conversation_id,
            _toast_meta("NOT IN KNOWLEDGE", page, _quote(data.get("question"))),
        )
    if kind == TOKEN_CAP:
        return Alert(
            kind,
            list(selectors.superadmins()),
            "The site assistant reached its daily token cap",
            f"{data.get('tokensUsed', 0):,} of {data.get('cap', 0):,} tokens used",
            "/relay/settings/",
            None,
            _toast_meta("TOKEN CAP", ""),
        )
    if kind == FAQ_ATTENTION:
        return Alert(
            kind,
            list(selectors.superadmins()),
            "Master FAQ sync needs attention",
            f"{data.get('held', 0)} held · {data.get('consecutiveFailures', 0)} failed runs in a row",
            "/relay/knowledge/?view=held",
            None,
            _toast_meta("MASTER FAQ", ""),
        )
    return Alert(kind, everyone, "Site assistant daily digest", "", "/relay/insights/", None, {})


def _log(alert: Alert, channel: str, user, now: datetime) -> RelayAlertLog | None:
    try:
        with transaction.atomic():
            return RelayAlertLog.objects.create(
                conversation_id=alert.conversation_id,
                channel=channel,
                type=alert.kind,
                recipient=user,
                bucket=bucket_for(now),
                sent_at=now,
            )
    except IntegrityError:
        return None


def _start_of_day(now: datetime) -> datetime:
    return timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)


def _email_due(alert: Alert, user, now: datetime) -> bool:
    since = _start_of_day(now) if alert.kind in DAILY_TYPES else now - EMAIL_WINDOW
    return not RelayAlertLog.objects.filter(
        channel=EMAIL,
        type=alert.kind,
        recipient=user,
        conversation_id=alert.conversation_id,
        sent_at__gte=since,
    ).exists()


def emails_sent_today(now: datetime) -> int:
    from apps.enquiries.notifications import emails_sent_today as enquiry_emails

    relay = RelayAlertLog.objects.filter(channel=EMAIL, sent_at__gte=_start_of_day(now)).count()
    return relay + enquiry_emails(now)


def deliver(alert: Alert, now: datetime | None = None) -> Outcome:
    now = now or timezone.now()
    outcome = Outcome()
    users = [user for user in alert.recipients if user is not None and user.is_active]
    if not users:
        return outcome
    prefs = preferences.for_users(users)
    to_email = []
    for user in users:
        pref = prefs[user.pk]
        if alert.kind != DIGEST and pref.wants(alert.kind, IN_APP):
            RelayNotification.objects.create(
                recipient=user,
                type=alert.kind,
                conversation_id=alert.conversation_id,
                title=alert.title[:200],
                body=alert.body[:300],
                url=alert.url[:500],
                meta=alert.meta,
                created_at=now,
            )
            _log(alert, IN_APP, user, now)
            outcome.in_app += 1
        if pref.wants(alert.kind, EMAIL) and user.email:
            to_email.append(user)
    if not to_email:
        return outcome
    message = None
    sent_today = emails_sent_today(now)
    for user in to_email:
        if sent_today >= settings.RESEND_DAILY_LIMIT:
            logger.warning(
                "Daily email limit reached; Relay alert emails skipped", extra={"type": alert.kind}
            )
            outcome.skipped += len(to_email) - to_email.index(user)
            break
        if not _email_due(alert, user, now):
            outcome.skipped += 1
            continue
        log = _log(alert, EMAIL, user, now)
        if log is None:  # Another delivery claimed this bucket a moment ago.
            outcome.skipped += 1
            continue
        try:
            message = message or emails.build(alert.kind, alert.data, **alert.email_options)
            emails.send(message, user.email)
        except Exception:  # noqa: BLE001 - one failed recipient must not stop the others
            logger.warning(
                "Relay alert email failed", extra={"recipient": user.pk, "type": alert.kind}, exc_info=True
            )
            log.delete()
            outcome.skipped += 1
            continue
        outcome.emails += 1
        sent_today += 1
    return outcome


def handle(event_type: str, data: dict, now: datetime | None = None) -> Outcome:
    """Build and deliver the alert for one event. Unknown types do nothing."""
    alert = build_alert(event_type, data)
    return deliver(alert, now) if alert is not None else Outcome()
