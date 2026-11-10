"""POST /api/inbound/relay: signature, clock window, replay, and each event type's alerts and emails."""

import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from apps.accounts.roles import SERVICE_LEAD, SUPERADMIN
from apps.relay import alerts, preferences
from apps.relay.fake import ALEX
from apps.relay.models import (
    EMAIL,
    IN_APP,
    RelayAlertLog,
    RelayInboundEvent,
    RelayInboxState,
    RelayNotification,
    RelayPreference,
    bucket_for,
)

from .conftest import RELAY_WEBHOOK_SECRET

URL = "/api/inbound/relay"


def sign(body: bytes, ts: str, secret: str = RELAY_WEBHOOK_SECRET) -> str:
    canonical = f"{ts}\nPOST\n{URL}\n\n{hashlib.sha256(body).hexdigest()}"
    return "v1=" + hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


@pytest.fixture
def team(make_user):
    owner = make_user(SUPERADMIN, email="owner@example.test", full_name="Sam Taylor")
    lead = make_user(SERVICE_LEAD, email="lead@example.test", full_name="Alex Lead")
    make_user("Viewer", email="viewer@example.test")
    make_user(SERVICE_LEAD, email="gone@example.test", is_active=False)
    return owner, lead


@pytest.fixture
def post(client, relay):
    def _post(event_type, data=None, *, event_id=None, counts=None, ts=None, signature=None, raw=None):
        payload = {
            "id": event_id or str(uuid.uuid4()),
            "type": event_type,
            "at": timezone.now().isoformat(),
            "counts": counts if counts is not None else {"needs": 2, "live": 1},
            "data": data or {},
        }
        body = raw if raw is not None else json.dumps(payload).encode()
        stamp = str(int(time.time()) if ts is None else ts)
        return client.post(
            URL,
            data=body,
            content_type="application/json",
            HTTP_X_RELAY_TIMESTAMP=stamp,
            HTTP_X_RELAY_SIGNATURE=signature or sign(body, stamp),
        )

    return _post


def handoff_data(**extra):
    data = {
        "conversationId": ALEX,
        "displayName": "Alex Morgan",
        "trigger": "not_helpful",
        "lastVisitorMessage": "Roughly how long would that take?",
        "pagePath": "/application-modernisation",
        "requestedAt": "2026-10-15T13:24:00Z",
    }
    data.update(extra)
    return data


# --- Authentication ------------------------------------------------------------------------------


def test_bad_signature_is_rejected(post, team):
    response = post("handoff.requested", handoff_data(), signature="v1=" + "0" * 64)
    assert response.status_code == 401 and response.json()["error"]["code"] == "bad_signature"
    assert not RelayNotification.objects.exists()


def test_wrong_secret_is_rejected(post, team):
    body = json.dumps({"id": str(uuid.uuid4()), "type": "inbox.changed", "data": {}}).encode()
    stamp = str(int(time.time()))
    response = post("inbox.changed", raw=body, ts=stamp, signature=sign(body, stamp, "another-secret"))
    assert response.status_code == 401


def test_stale_timestamp_is_rejected(post, team):
    response = post("handoff.requested", handoff_data(), ts=int(time.time()) - 301)
    assert response.status_code == 401 and response.json()["error"]["code"] == "stale"


def test_repeated_event_id_is_acknowledged_once(post, team, mailoutbox):
    event_id = str(uuid.uuid4())
    first = post("handoff.requested", handoff_data(), event_id=event_id)
    second = post("handoff.requested", handoff_data(), event_id=event_id)
    assert first.json() == {"ok": True}
    assert second.status_code == 200 and second.json() == {"ok": True, "duplicate": True}
    assert RelayInboundEvent.objects.count() == 1
    assert RelayNotification.objects.count() == 2  # owner and lead, once
    assert len(mailoutbox) == 2


def test_endpoint_is_404_when_relay_is_not_configured(client, settings, db):
    settings.RELAY_API_BASE_URL = ""
    settings.RELAY_CLIENT = "http"
    assert client.post(URL, data=b"{}", content_type="application/json").status_code == 404


def test_endpoint_fails_closed_without_a_secret(post, settings):
    settings.RELAY_WEBHOOK_SECRET = ""
    assert post("inbox.changed").status_code == 503


def test_malformed_body_is_400(post, team):
    body = b'{"type":"inbox.changed"}'
    stamp = str(int(time.time()))
    assert post("x", raw=body, ts=stamp, signature=sign(body, stamp)).status_code == 400


def test_only_post(client, relay):
    assert client.get(URL).status_code == 405


# --- Events --------------------------------------------------------------------------------------


def test_handoff_requested_alerts_everyone_with_access(post, team, mailoutbox):
    owner, lead = team
    response = post("handoff.requested", handoff_data(), counts={"needs": 3, "live": 1})
    assert response.status_code == 200
    rows = RelayNotification.objects.order_by("recipient__email")
    assert [row.recipient for row in rows] == [lead, owner]
    first = rows[0]
    assert first.title == "Alex Morgan needs a person"
    assert first.body == "Marked an answer not helpful"
    assert first.url == f"/relay/inbox/{ALEX}/"
    assert first.meta == {
        "tag": "NOT HELPFUL",
        "page": "/application-modernisation",
        "quote": "Roughly how long would that take?",
    }
    assert sorted(m.to[0] for m in mailoutbox) == ["lead@example.test", "owner@example.test"]
    message = mailoutbox[0]
    assert message.subject == "Site assistant (legacy): Alex Morgan needs a person"
    assert message.from_email == "Vitalos Relay <relay@notify.vitalos.co.uk>"
    assert message.extra_headers["Auto-Submitted"] == "auto-generated"
    text = message.body
    assert "SITE ASSISTANT · NEEDS A PERSON" in text
    assert "Alex Morgan is waiting for a reply." in text
    assert "Alex marked an AI answer as not helpful and asked to talk to a person." in text
    assert "> “Roughly how long would that take?”" in text
    assert "Trigger: Not helpful, then asked for a person" in text
    assert "Waiting since: 14:24 BST, 15 October 2026" in text
    assert f"/relay/inbox/{ALEX}?ref=email" in text
    assert "It never signs you in on its own." in text
    assert "ONE EMAIL PER CONVERSATION EVERY 10 MINUTES AT MOST" in text
    html = message.alternatives[0][0]
    assert "Alex Morgan is waiting for a reply." in html
    state = RelayInboxState.load()
    assert (state.needs, state.live) == (3, 1)
    assert RelayAlertLog.objects.filter(channel=IN_APP).count() == 2
    assert RelayAlertLog.objects.filter(channel=EMAIL).count() == 2


def test_quote_is_omitted_when_the_website_sends_no_snippet(post, team, mailoutbox):
    post("handoff.requested", handoff_data(lastVisitorMessage=None, trigger="explicit_request"))
    text = mailoutbox[0].body
    assert "Alex asked to talk to a person." in text and "\n> " not in text
    assert RelayNotification.objects.first().meta["quote"] == ""


def test_low_confidence_trigger_wording(post, team, mailoutbox):
    post("handoff.requested", handoff_data(trigger="low_confidence", displayName="Visitor 8C1D"))
    assert "The site assistant could not answer from published knowledge." in mailoutbox[0].body
    assert mailoutbox[0].subject == "Site assistant (legacy): Visitor 8C1D needs a person"


def test_ten_minute_email_dedupe_per_conversation_type_and_recipient(post, team, mailoutbox):
    post("handoff.requested", handoff_data())
    post("handoff.requested", handoff_data())
    assert len(mailoutbox) == 2  # one each for the owner and the lead
    assert RelayNotification.objects.count() == 4  # in-app is not de-duplicated
    later = timezone.now() + timedelta(minutes=11)
    with mock.patch("django.utils.timezone.now", return_value=later):
        post("handoff.requested", handoff_data())
    assert len(mailoutbox) == 4
    buckets = set(RelayAlertLog.objects.filter(channel=EMAIL).values_list("bucket", flat=True))
    assert len(buckets) == 2


def test_alert_log_bucket_is_unique():
    now = timezone.now()
    assert bucket_for(now) == int(now.timestamp()) // 600


def test_visitor_replied_goes_to_the_assigned_admin(post, team, mailoutbox):
    owner, lead = team
    post(
        "visitor.replied",
        {
            "conversationId": ALEX,
            "displayName": "Alex Morgan",
            "assignedAdminId": f"sa:{lead.pk}",
            "lastVisitorMessage": "Thanks",
            "pagePath": "/",
        },
    )
    assert list(RelayNotification.objects.values_list("recipient", flat=True)) == [lead.pk]
    assert [m.to for m in mailoutbox] == [["lead@example.test"]]
    assert mailoutbox[0].subject == "Site assistant (legacy): Alex Morgan replied"
    assert "sent a new message in your conversation" in mailoutbox[0].body


def test_visitor_replied_without_assignee_goes_to_everyone(post, team, mailoutbox):
    data = {"conversationId": ALEX, "displayName": "Alex Morgan", "assignedAdminId": None, "pagePath": "/"}
    post("visitor.replied", data)
    assert RelayNotification.objects.count() == 2
    data["assignedAdminId"] = "sa:999999"  # unknown or no longer allowed: everyone
    post("visitor.replied", data)
    assert RelayNotification.objects.count() == 4


def test_reminder(post, team, mailoutbox):
    post(
        "handoff.reminder",
        {**handoff_data(), "minutesWaiting": 10, "nth": 1},
    )
    row = RelayNotification.objects.first()
    assert row.title == "No one has joined Alex Morgan" and row.body == "Reminder after 10 minutes"
    assert mailoutbox[0].subject == "Site assistant (legacy): Alex Morgan is still waiting"
    assert "No one has joined after 10 minutes. This is reminder 1." in mailoutbox[0].body


def test_no_answer_is_in_app_only_by_default(post, team, mailoutbox):
    post(
        "relay.no_answer",
        {"conversationId": ALEX, "question": "What are your day rates?", "pagePath": "/pricing"},
    )
    assert RelayNotification.objects.count() == 2
    assert RelayNotification.objects.first().title == "The site assistant had no answer in knowledge"
    assert mailoutbox == []


def test_digest_is_email_only(post, team, mailoutbox):
    post(
        "digest.daily",
        {
            "waitingNow": 1,
            "yesterday": {
                "conversations": 12,
                "handoffs": 3,
                "handoffRate": 0.25,
                "helpful": 7,
                "notHelpful": 1,
                "aiResolved": 9,
            },
            "openGaps": 2,
            "topGaps": [{"question": "What are your day rates?", "count": 2}],
        },
    )
    assert not RelayNotification.objects.exists()
    assert len(mailoutbox) == 2
    text = mailoutbox[0].body
    assert mailoutbox[0].subject == "Site assistant (legacy) daily digest"
    assert "Hand-off rate: 25%" in text and "- What are your day rates? (2)" in text
    post("digest.daily", {"waitingNow": 0, "yesterday": {}})
    assert len(mailoutbox) == 2  # one digest a day


def test_token_cap_and_faq_go_to_superadmins(post, team, mailoutbox):
    owner, _lead = team
    post("relay.token_cap", {"day": "2026-10-15", "tokensUsed": 2000000, "cap": 2000000})
    post("faq.attention", {"held": 2, "consecutiveFailures": 3, "runId": str(uuid.uuid4())})
    assert set(RelayNotification.objects.values_list("recipient", flat=True)) == {owner.pk}
    assert sorted(m.subject for m in mailoutbox) == [
        "Site assistant (legacy): Master FAQ sync needs attention",
        "Site assistant (legacy): daily token cap reached",
    ]


def test_inbox_changed_only_updates_counts(post, team, mailoutbox):
    post("inbox.changed", {}, counts={"needs": 5, "live": 0})
    assert not RelayNotification.objects.exists() and mailoutbox == []
    assert RelayInboxState.load().needs == 5


def test_unknown_event_types_are_ignored(post, team):
    assert post("something.new", {"x": 1}).json() == {"ok": True}
    assert not RelayNotification.objects.exists()


def test_preferences_are_respected(post, team, mailoutbox):
    owner, lead = team
    grid = preferences.defaults()
    grid["handoff_requested"] = {"in_app": False, "email": False}
    preferences.save(lead, grid, sound=False, browser=False)
    post("handoff.requested", handoff_data())
    assert list(RelayNotification.objects.values_list("recipient", flat=True)) == [owner.pk]
    assert [m.to for m in mailoutbox] == [["owner@example.test"]]
    assert RelayPreference.objects.get(user=lead).prefs["handoff_requested"] == {
        "in_app": False,
        "email": False,
    }


def test_daily_email_limit_stops_relay_email(post, team, mailoutbox, settings):
    settings.RESEND_DAILY_LIMIT = 1
    post("handoff.requested", handoff_data())
    assert len(mailoutbox) == 1
    assert RelayNotification.objects.count() == 2


def test_a_failed_send_does_not_stop_the_others_and_frees_the_bucket(team, relay, mailoutbox):
    calls = {"n": 0}
    from apps.relay import emails

    real_send = emails.send

    def flaky(message, recipient):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("smtp down")
        real_send(message, recipient)

    with mock.patch.object(emails, "send", side_effect=flaky):
        outcome = alerts.handle("handoff.requested", handoff_data())
    assert outcome.emails == 1 and outcome.skipped == 1
    assert len(mailoutbox) == 1
    assert RelayAlertLog.objects.filter(channel=EMAIL).count() == 1


def test_event_with_a_bad_conversation_id_does_nothing(post, team):
    post("handoff.requested", handoff_data(conversationId="not-a-uuid"))
    assert not RelayNotification.objects.exists()
