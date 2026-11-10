"""Relay records owned by the Super Admin (ADR-035, docs/relay/API.md).

Conversations, messages and knowledge live in the website's database and are only read and changed
through the signed admin API. This app keeps what belongs to staff: in-app alerts, notification
preferences, the alert log that de-duplicates email, processed webhook ids and the badge counts.

Type and channel values are validated in code (``TYPES``, ``CHANNELS``) rather than with field
``choices``, so adding a type later needs no AlterField migration (those stop the automatic deploy).
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

# Notification and alert types. Keys are stored; labels are the "My notifications" wording.
HANDOFF_REQUESTED = "handoff_requested"
VISITOR_REPLIED = "visitor_replied"
REMINDER = "reminder"
NO_ANSWER = "no_answer"
DIGEST = "digest"
TOKEN_CAP = "token_cap"  # noqa: S105  # nosec B105 - an alert type, not a credential
FAQ_ATTENTION = "faq_attention"
TYPES = {
    HANDOFF_REQUESTED: "A visitor asks for a person",
    VISITOR_REPLIED: "Visitor replies in my conversation",
    REMINDER: "No one has joined after the reminder delay",
    NO_ANSWER: "The site assistant could not answer (no handoff)",
    DIGEST: "Daily digest",
    TOKEN_CAP: "Daily token cap reached",
    FAQ_ATTENTION: "Master FAQ sync needs attention",
}

IN_APP = "in_app"
EMAIL = "email"
CHANNELS = (IN_APP, EMAIL)

# Alerts are bucketed in 10-minute windows: at most one email per conversation, type and recipient.
BUCKET_SECONDS = 600


def bucket_for(moment) -> int:
    return int(moment.timestamp()) // BUCKET_SECONDS


class RelayNotification(models.Model):
    """An in-app Relay alert for one admin: the Relay bell, the toast and the browser notification."""

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="relay_notifications"
    )
    type = models.CharField(max_length=32)
    conversation_id = models.UUIDField(null=True, blank=True, db_index=True)
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=300, blank=True)
    url = models.CharField(max_length=500, blank=True)
    # Toast details: {"quote": visitor words (≤280, only when the website sends them), "tag", "page"}.
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["recipient", "read_at"], name="relay_notif_unread_idx")]

    def __str__(self):
        return self.title

    @property
    def is_read(self) -> bool:
        return self.read_at is not None


class RelayPreference(models.Model):
    """One admin's Relay alert choices: the in-app/email grid, sound and browser notifications."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="relay_pref")
    prefs = models.JSONField(default=dict, blank=True)
    sound = models.BooleanField(default=False)
    browser = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Site assistant preferences for {self.user}"


class RelayAlertLog(models.Model):
    """Every alert delivered, per channel. De-duplicates email and feeds the thread's ALERTS line."""

    conversation_id = models.UUIDField(null=True, blank=True)
    channel = models.CharField(max_length=16)
    type = models.CharField(max_length=32)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    bucket = models.BigIntegerField()
    sent_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-sent_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation_id", "channel", "type", "recipient", "bucket"],
                name="relay_alert_once_per_bucket",
            )
        ]
        indexes = [models.Index(fields=["conversation_id", "sent_at"], name="relay_alert_conv_idx")]

    def __str__(self):
        return f"{self.channel} {self.type} to {self.recipient_id} at {self.sent_at:%Y-%m-%d %H:%M}"


class RelayInboundEvent(models.Model):
    """Webhook event ids already processed: the website retries, and a repeated id is ignored."""

    id = models.UUIDField(primary_key=True)
    type = models.CharField(max_length=40)
    received_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.type} {self.id}"


class RelayInboxState(models.Model):
    """Singleton (pk=1): the latest counts from the website, for the sidebar badge."""

    needs = models.PositiveIntegerField(default=0)
    live = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Site assistant inbox: {self.needs} need a person, {self.live} live"

    @classmethod
    def load(cls) -> "RelayInboxState":
        state, _ = cls.objects.get_or_create(pk=1)
        return state
