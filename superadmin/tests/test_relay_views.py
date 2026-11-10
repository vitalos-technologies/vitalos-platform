"""Relay tab: role guards, every page, actions forwarded and audited, nav, badge, pulse and deep links."""

import json
import re
import uuid

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.relay import services
from apps.relay.client import RelayError
from apps.relay.fake import ALEX, CMS_DOC, JORDAN, TEAM_ANSWER, VISITOR_8C1D
from apps.relay.models import RelayAlertLog, RelayInboxState, RelayNotification

from .conftest import HX


def calls(state, method=None):
    return [call for call in state.calls if method is None or call[0] == method]


# --- Access --------------------------------------------------------------------------------------

PAGES = [
    "/relay/inbox/",
    f"/relay/inbox/{ALEX}/",
    "/relay/knowledge/",
    "/relay/knowledge/?view=confirm",
    "/relay/knowledge/?view=held",
    f"/relay/knowledge/{TEAM_ANSWER}/",
    f"/relay/knowledge/{CMS_DOC}/",
    "/relay/knowledge/new/",
    "/relay/insights/",
    "/relay/settings/",
    "/relay/me/prefs/",
]


@pytest.mark.parametrize("path", PAGES)
def test_every_page_renders_for_superadmin(client_for, superadmin, relay, path):
    response = client_for(superadmin).get(path)
    assert response.status_code == 200, path
    body = response.content.decode()
    assert "Site assistant (legacy)<span" in body and 'id="relay-config"' in body


def test_relay_root_redirects_to_the_inbox(client_for, superadmin, relay):
    response = client_for(superadmin).get("/relay/")
    assert response.status_code == 302 and response["Location"] == "/relay/inbox/"


def test_viewer_gets_403_everywhere(client_for, viewer, relay):
    client = client_for(viewer)
    for path in PAGES + ["/relay/notifications/", "/relay/bell/"]:
        assert client.get(path).status_code == 403, path
    assert client.post(f"/relay/inbox/{ALEX}/join/").status_code == 403
    assert client.get("/relay/badge/").content == b""
    assert client.get("/relay/pulse/").json() == {"enabled": False}


def test_lead_can_reply_but_not_manage(client_for, lead, relay):
    client = client_for(lead)
    assert client.get("/relay/inbox/").status_code == 200
    response = client.post(
        f"/relay/inbox/{ALEX}/reply/",
        {"text": "Hello Alex", "client_message_id": str(uuid.uuid4()), "email_if_away": "on"},
        **HX,
    )
    assert response.status_code == 200
    assert client.get("/relay/settings/").status_code == 403
    assert client.post("/relay/settings/", {}).status_code == 403
    for action in ("publish", "archive", "reindex"):
        assert client.post(f"/relay/knowledge/{TEAM_ANSWER}/{action}/").status_code == 403
    assert client.post("/relay/knowledge/reindex-all/").status_code == 403
    assert client.post("/relay/knowledge/faq/sync/").status_code == 403
    body = client.get("/relay/knowledge/").content.decode()
    assert "Re-index all" not in body
    assert 'data-relay-nav="settings"' not in body


def test_anonymous_goes_to_login_with_a_relative_next(client, relay):
    response = client.get(f"/relay/inbox/{ALEX}/?ref=email")
    assert response.status_code == 302
    assert response["Location"].startswith("/login/?next=")
    assert f"/relay/inbox/{ALEX}/%3Fref%3Demail" in response["Location"]


def test_email_deep_link_without_slash_lands_on_the_thread_after_sign_in(client, superadmin, relay):
    from .conftest import login

    path = f"/relay/inbox/{ALEX}?ref=email"
    response = client.get(path)
    assert response.status_code == 302
    next_url = response["Location"].split("next=", 1)[1]
    login(client, superadmin)
    from urllib.parse import unquote

    landing = client.get(unquote(next_url))
    assert landing.status_code == 200
    body = landing.content.decode()
    assert "Alex Morgan" in body and 'data-relay-thread="' + ALEX in body


def test_login_ignores_an_absolute_next(client, superadmin, relay):
    from .conftest import login

    login(client, superadmin)
    response = client.get("/login/?next=https://evil.example/relay/")
    assert response.status_code == 302 and not response["Location"].startswith("https://evil")


def test_relay_is_404_when_not_configured(client_for, superadmin, settings, db):
    settings.RELAY_API_BASE_URL = ""
    settings.RELAY_CLIENT = "http"
    assert client_for(superadmin).get("/relay/inbox/").status_code == 404


# --- Navigation and badge ------------------------------------------------------------------------


def test_nav_item_hidden_when_relay_is_not_configured(client_for, superadmin, settings, seeded):
    settings.RELAY_API_BASE_URL = ""
    settings.RELAY_CLIENT = "http"
    body = client_for(superadmin).get("/").content.decode()
    assert 'data-nav="relay"' not in body and "relay-alerts.js" not in body


def test_nav_item_and_toast_root_shown_when_configured(client_for, superadmin, relay, seeded):
    body = client_for(superadmin).get("/").content.decode()
    assert 'data-nav="relay"' in body and 'data-testid="relay-badge-slot"' in body
    assert "relay-alerts.js" in body and 'id="relay-toasts"' in body


def test_nav_item_hidden_from_viewers(client_for, viewer, relay, seeded):
    body = client_for(viewer).get("/").content.decode()
    assert 'data-nav="relay"' not in body and 'id="relay-toasts"' not in body


def test_badge_reads_local_state_and_refreshes_from_the_api_at_most_once_a_minute(
    client_for, superadmin, relay
):
    client = client_for(superadmin)
    body = client.get("/relay/badge/").content.decode()
    assert 'data-testid="relay-badge"' in body and "</span>2<span" in body
    assert len(calls(relay, "GET")) == 1
    client.get("/relay/badge/")
    assert len(calls(relay, "GET")) == 1  # throttled
    RelayInboxState.objects.filter(pk=1).update(needs=0, updated_at=timezone.now())
    assert "relay-badge" not in client.get("/relay/badge/").content.decode()


# --- Inbox ---------------------------------------------------------------------------------------


def test_inbox_lists_needs_first_with_status_nodes_and_tags(client_for, superadmin, relay):
    body = client_for(superadmin).get("/relay/inbox/").content.decode()
    assert body.index("Visitor 8C1D") < body.index("Alex Morgan")
    assert 'data-node="waiting"' in body
    assert "WAITING 12M" in body and "WAITING 4M" in body
    assert "NOT IN KNOWLEDGE" in body and "NOT HELPFUL" in body and "/application-modernisation" in body
    assert "Needs a person" in body and "Search name, email or message" in body


def test_inbox_tabs_and_search_partial(client_for, superadmin, relay):
    client = client_for(superadmin)
    body = client.get("/relay/inbox/?tab=live", HTTP_HX_TARGET="relay-list", **HX).content.decode()
    assert "Jordan Ellis" in body and "LIVE · ST" in body and 'hx-swap-oob="true"' in body
    assert "Alex Morgan" not in body
    body = client.get("/relay/inbox/?tab=needs&q=morgan", HTTP_HX_TARGET="relay-list", **HX).content.decode()
    assert "Alex Morgan" in body and "Visitor 8C1D" not in body
    assert ("GET", "/inbox", f"sa:{superadmin.pk}") in relay.calls


def test_thread_shows_messages_context_and_alerts(client_for, superadmin, relay):
    RelayAlertLog.objects.create(
        conversation_id=ALEX, channel="in_app", type="handoff_requested", recipient=superadmin, bucket=1
    )
    body = client_for(superadmin).get(f"/relay/inbox/{ALEX}/").content.decode()
    assert "NEEDS A PERSON · WAITING" in body
    assert "VISITOR ·" in body and "RELAY · AI" in body and "3 SOURCES" in body and "1.4S" in body
    assert "MARKED NOT HELPFUL" in body
    assert "HANDOFF REQUESTED ·" in body and "CONSENT GIVEN" in body
    assert "Join conversation" in body and "Join and send" in body
    assert "Joining pauses the AI for this conversation." in body
    assert "Email this reply if Alex has left" in body
    assert "alex.morgan@example.com" in body and "Example Care Group" in body
    assert "Consent to contact" in body and "notice v1.0" in body
    assert "In-app sent to 1 admin at" in body and "Next reminder at" in body
    assert "Send to HubSpot · phase 2" in body


def test_thread_partial_and_marks_alerts_read(client_for, superadmin, relay):
    note = RelayNotification.objects.create(
        recipient=superadmin,
        type="handoff_requested",
        conversation_id=ALEX,
        title="Alex Morgan needs a person",
    )
    response = client_for(superadmin).get(f"/relay/inbox/{ALEX}/", HTTP_HX_TARGET="relay-thread", **HX)
    assert response.status_code == 200
    assert "<html" not in response.content.decode()
    note.refresh_from_db()
    assert note.read_at is not None


def test_unknown_conversation_is_404(client_for, superadmin, relay):
    assert client_for(superadmin).get(f"/relay/inbox/{uuid.uuid4()}/").status_code == 404


def test_messages_after_appends_and_reports_status(client_for, superadmin, relay):
    response = client_for(superadmin).get(f"/relay/inbox/{JORDAN}/messages/?after=2000-01-01T00:00:00Z")
    body = response.content.decode()
    assert "Thanks, that&#x27;s useful" in body or "Thanks, that's useful" in body
    assert 'data-relay-state data-status="human"' in body


ACTIONS = [
    ("join", {}, "relay.joined", "POST", f"/conversations/{ALEX}/join"),
    ("handback", {}, "relay.handed_back", "POST", f"/conversations/{ALEX}/handback"),
    ("close", {}, "relay.closed", "POST", f"/conversations/{ALEX}/close"),
    (
        "note",
        {"text": "Call them tomorrow about the Example Care Group contract"},
        "relay.noted",
        "POST",
        f"/conversations/{ALEX}/note",
    ),
]


@pytest.mark.parametrize(("action", "data", "audit", "method", "path"), ACTIONS)
def test_actions_call_the_api_and_are_audited_without_pii(
    client_for, superadmin, relay, action, data, audit, method, path
):
    if action == "handback":
        services.join(superadmin, ALEX)
    response = client_for(superadmin).post(f"/relay/inbox/{ALEX}/{action}/", data, **HX)
    assert response.status_code == 200
    assert (method, path, f"sa:{superadmin.pk}") in relay.calls
    event = AuditEvent.objects.filter(action=audit).latest("created_at")
    assert event.entity_type == "relay.conversation" and event.entity_id == ALEX
    assert "Example Care Group" not in event.summary and "alex.morgan@example.com" not in event.summary
    assert json.loads(response["HX-Trigger"])["relay-inbox-changed"] is True


def test_reply_forwards_text_and_audits_without_the_text(client_for, superadmin, relay):
    message_id = str(uuid.uuid4())
    response = client_for(superadmin).post(
        f"/relay/inbox/{ALEX}/reply/",
        {
            "text": "Hello Alex, about Example Care Group",
            "client_message_id": message_id,
            "email_if_away": "on",
        },
        **HX,
    )
    assert response.status_code == 200
    assert "Hello Alex, about Example Care Group" in response.content.decode()
    assert "Send" in response.content.decode()
    event = AuditEvent.objects.get(action="relay.replied")
    assert "Example Care Group" not in event.summary and "Example Care Group" not in json.dumps(
        event.metadata
    )
    assert event.metadata["characters"] == len("Hello Alex, about Example Care Group")


def test_reply_validation(client_for, superadmin, relay):
    response = client_for(superadmin).post(
        f"/relay/inbox/{ALEX}/reply/", {"text": "", "client_message_id": "x"}, **HX
    )
    assert response["HX-Reswap"] == "none" and "vsa-toast" in response["HX-Trigger"]
    assert not calls(relay, "POST")


def test_assign_to_a_relay_user_only(client_for, superadmin, lead, viewer, relay):
    client = client_for(superadmin)
    response = client.post(f"/relay/inbox/{ALEX}/assign/", {"assignee": lead.pk}, **HX)
    assert response.status_code == 200
    assert relay.data["conversations"][ALEX]["assigned"]["id"] == f"sa:{lead.pk}"
    assert AuditEvent.objects.get(action="relay.assigned").summary.endswith("lead@example.test")
    response = client.post(f"/relay/inbox/{ALEX}/assign/", {"assignee": viewer.pk}, **HX)
    assert response["HX-Reswap"] == "none"


def test_delete_needs_an_inline_confirmation(client_for, superadmin, relay):
    client = client_for(superadmin)
    response = client.post(f"/relay/inbox/{VISITOR_8C1D}/delete/", {}, **HX)
    assert response["HX-Reswap"] == "none" and VISITOR_8C1D in relay.data["conversations"]
    response = client.post(f"/relay/inbox/{VISITOR_8C1D}/delete/", {"confirm": "delete"}, **HX)
    assert response.status_code == 204 and response["HX-Redirect"] == "/relay/inbox/"
    assert VISITOR_8C1D not in relay.data["conversations"]
    assert AuditEvent.objects.get(action="relay.deleted").summary == "Deleted a site assistant conversation"


def test_typing_is_throttled(client_for, superadmin, relay):
    client = client_for(superadmin)
    assert client.post(f"/relay/inbox/{ALEX}/typing/").status_code == 204
    assert client.post(f"/relay/inbox/{ALEX}/typing/").status_code == 204
    assert len([c for c in relay.calls if c[1].endswith("/typing")]) == 1


def test_transcript_and_save_to_knowledge(client_for, superadmin, relay):
    client = client_for(superadmin)
    response = client.get(f"/relay/inbox/{JORDAN}/transcript/")
    assert response.status_code == 200 and "VISITOR" in response.json()["text"]
    assert AuditEvent.objects.filter(action="relay.transcript_copied").exists()
    message_id = relay.data["conversations"][JORDAN]["messages"][3]["id"]
    response = client.post(f"/relay/inbox/{JORDAN}/save-to-knowledge/", {"message_id": message_id}, **HX)
    assert response.status_code == 204
    assert "relay-saved" in response["HX-Trigger"]
    assert AuditEvent.objects.filter(action="relay.knowledge_saved").exists()


def test_api_errors_are_shown_not_raised(client_for, superadmin, relay):
    relay.fail_next(RelayError("conflict", 409))
    response = client_for(superadmin).post(f"/relay/inbox/{ALEX}/join/", **HX)
    assert response.status_code == 200 and response["HX-Reswap"] == "none"
    assert "changed while you were looking" in json.loads(response["HX-Trigger"])["vsa-toast"]["message"]
    relay.fail_next(RelayError("unavailable"))
    body = client_for(superadmin).get("/relay/inbox/").content.decode()
    assert "The site assistant could not be reached" in body


# --- Availability, bell, pulse, prefs ------------------------------------------------------------


def test_availability_switch_and_heartbeat(client_for, superadmin, relay):
    client = client_for(superadmin)
    response = client.post("/relay/me/availability", {"available": "1"}, **HX)
    assert 'aria-checked="true"' in response.content.decode()
    assert relay.data["presence"][f"sa:{superadmin.pk}"] is True
    assert AuditEvent.objects.filter(action="relay.availability_changed").count() == 1
    assert client.post("/relay/me/availability", {"heartbeat": "1"}).status_code == 204
    assert AuditEvent.objects.filter(action="relay.availability_changed").count() == 1
    assert len([c for c in relay.calls if c[1] == "/presence" and c[0] == "POST"]) == 2


def test_bell_menu_and_mark_all_read(client_for, superadmin, relay):
    RelayNotification.objects.create(
        recipient=superadmin,
        type="handoff_requested",
        conversation_id=ALEX,
        title="Alex Morgan needs a person",
        body="Marked an answer not helpful",
    )
    client = client_for(superadmin)
    body = client.get("/relay/notifications/", **HX).content.decode()
    assert "Alex Morgan needs a person" in body and "Marked an answer not helpful · 1 min" in body
    assert "Mark all read" in body and "Notification settings" in body
    assert ", 1 unread" in client.get("/relay/bell/").content.decode()
    client.post("/relay/notifications/read-all/", **HX)
    assert not RelayNotification.objects.filter(read_at__isnull=True).exists()


def test_open_notification_redirects_only_to_local_urls(client_for, superadmin, relay):
    good = RelayNotification.objects.create(
        recipient=superadmin, type="reminder", title="x", url=f"/relay/inbox/{ALEX}/"
    )
    bad = RelayNotification.objects.create(
        recipient=superadmin, type="reminder", title="y", url="https://evil.example/"
    )
    client = client_for(superadmin)
    assert client.post(f"/relay/notifications/{good.pk}/open/")["Location"] == f"/relay/inbox/{ALEX}/"
    assert client.post(f"/relay/notifications/{bad.pk}/open/")["Location"] == "/relay/inbox/"


def test_pulse_returns_new_unread_alerts_since_the_cursor(client_for, superadmin, lead, relay):
    client = client_for(superadmin)
    first = client.get("/relay/pulse/").json()
    assert first["enabled"] is True and first["items"] == []
    cursor = first["cursor"]
    item = RelayNotification.objects.create(
        recipient=superadmin,
        type="handoff_requested",
        conversation_id=ALEX,
        title="Alex Morgan needs a person",
        url=f"/relay/inbox/{ALEX}/",
        meta={"tag": "NOT HELPFUL", "page": "/application-modernisation", "quote": "Roughly how long?"},
    )
    RelayNotification.objects.create(recipient=lead, type="handoff_requested", title="Not for you")
    data = client.get(f"/relay/pulse/?since={cursor}").json()
    assert [i["id"] for i in data["items"]] == [item.pk]
    assert data["items"][0]["meta"] == "NOT HELPFUL · /APPLICATION-MODERNISATION · NOW"
    assert data["items"][0]["quote"] == "Roughly how long?"
    assert data["cursor"] == item.pk and data["unread"] == 1
    assert client.get(f"/relay/pulse/?since={item.pk}").json()["items"] == []


def test_prefs_grid_sound_and_browser(client_for, lead, relay):
    client = client_for(lead)
    body = client.get("/relay/me/prefs/").content.decode()
    assert "A visitor asks for a person" in body and "No one has joined after 10 minutes" in body
    assert "Daily digest" in body and "Sound: off" in body and "Allow browser notifications" in body
    client.post("/relay/me/prefs/", {"handoff_requested-email": "on", "digest-email": "on"})
    from apps.relay import preferences

    prefs = preferences.get(lead)
    assert prefs.grid["handoff_requested"] == {"in_app": False, "email": True}
    assert prefs.grid["digest"] == {"in_app": False, "email": True}
    client.post("/relay/me/prefs/", {"toggle": "sound"})
    assert preferences.get(lead).sound is True
    client.post("/relay/me/prefs/", {"toggle": "browser", "browser_value": "1"})
    assert preferences.get(lead).browser is True
    assert AuditEvent.objects.filter(action="relay.preferences_changed").count() == 3


# --- Knowledge, insights, settings ---------------------------------------------------------------


def test_knowledge_page_shows_sources_entries_and_gaps(client_for, superadmin, relay):
    body = client_for(superadmin).get("/relay/knowledge/").content.decode()
    for text in ("WEBSITE · CMS", "RELAY KNOWLEDGE · REPO", "TEAM ANSWERS", "MASTER FAQ · NOTION"):
        assert text in body
    assert "42 pages" in body and "31 live" in body and "4 awaiting confirmation · using snapshot" in body
    assert "Draft · review" in body and "Published" in body and "ABT-01" in body and "Open in Notion" in body
    assert "Do you hold ISO 27001 certification?" in body and "Add to Master FAQ" in body
    assert "https://app.notion.com/p/3fae4b3411f9808cb450c69d43e8f22c" in body
    assert "Answer threshold 0.4" in body


def test_knowledge_faq_views(client_for, superadmin, lead, relay):
    body = client_for(superadmin).get("/relay/knowledge/?view=confirm").content.decode()
    assert "Not used by the site assistant" in body and "Confirm note" in body and "Sync now" in body
    body = client_for(lead).get("/relay/knowledge/?view=confirm").content.decode()
    assert "Confirm note" not in body and "Sync now" not in body
    body = client_for(superadmin).get("/relay/knowledge/?view=held").content.decode()
    assert "Mentions a certification" in body


def test_retrieval_test_marks_chunks_above_the_threshold(client_for, superadmin, relay):
    body = (
        client_for(superadmin)
        .post("/relay/knowledge/test/", {"question": "rescue a failing project"}, **HX)
        .content.decode()
    )
    assert "Engineering Rescue · §2" in body and "0.82" in body
    assert body.count("above the threshold") == 2
    assert "Answer threshold 0.4 · below it the site assistant offers a person" in body


def test_markdown_preview_is_safe(client_for, superadmin, relay):
    body = (
        client_for(superadmin)
        .post(
            "/relay/knowledge/preview/",
            {
                "body_md": "## Title\n\n**Bold** <script>alert(1)</script> [x](javascript:alert(1)) [ok](https://example.com)"
            },
            **HX,
        )
        .content.decode()
    )
    assert "<h3>Title</h3>" in body and "<strong>Bold</strong>" in body
    assert "<script>" not in body and "javascript:" not in body.replace("[x](javascript:alert(1))", "")
    assert 'href="https://example.com"' in body


def test_create_and_edit_a_team_answer(client_for, lead, relay):
    client = client_for(lead)
    body = client.get("/relay/knowledge/new/?question=What%20are%20your%20day%20rates%3F").content.decode()
    assert 'value="What are your day rates?"' in body
    response = client.post(
        "/relay/knowledge/new/", {"title": "Day rates", "type": "faq", "body_md": "We quote per engagement."}
    )
    assert response.status_code == 302 and "/relay/knowledge/" in response["Location"]
    assert AuditEvent.objects.filter(action="relay.knowledge_saved").exists()
    response = client.post(
        f"/relay/knowledge/{TEAM_ANSWER}/",
        {"title": "Can you work with our in-house team?", "type": "faq", "body_md": "Yes, often."},
    )
    assert response.status_code == 302
    assert relay.data["documents"][TEAM_ANSWER]["bodyMd"] == "Yes, often."


def test_cms_entries_are_read_only(client_for, superadmin, relay):
    client = client_for(superadmin)
    body = client.get(f"/relay/knowledge/{CMS_DOC}/").content.decode()
    assert "read-only here" in body and "Open the source" in body
    client.post(f"/relay/knowledge/{CMS_DOC}/", {"title": "Changed", "type": "offer", "body_md": "x"})
    assert relay.data["documents"][CMS_DOC]["title"] == "Application Modernisation"


def test_superadmin_publishes_archives_reindexes(client_for, superadmin, relay):
    client = client_for(superadmin)
    client.post(f"/relay/knowledge/{TEAM_ANSWER}/publish/")
    assert relay.data["documents"][TEAM_ANSWER]["status"] == "published"
    client.post(f"/relay/knowledge/{TEAM_ANSWER}/archive/")
    assert relay.data["documents"][TEAM_ANSWER]["status"] == "archived"
    client.post(f"/relay/knowledge/{TEAM_ANSWER}/reindex/")
    response = client.post("/relay/knowledge/reindex-all/", **HX)
    assert "Re-indexed 4 entries" in json.loads(response["HX-Trigger"])["vsa-toast"]["message"]
    client.post("/relay/knowledge/faq/sync/", **HX)
    actions = set(AuditEvent.objects.values_list("action", flat=True))
    assert {
        "relay.knowledge_published",
        "relay.knowledge_archived",
        "relay.reindexed",
        "relay.faq_synced",
    } <= actions


def test_insights_periods(client_for, superadmin, relay):
    body = client_for(superadmin).get("/relay/insights/?days=7").content.decode()
    assert "Hand-off rate" in body and "14%" in body and "4 min 20 s" in body
    assert "What does Vitalos do?" in body and "$1.42" in body
    assert re.search(r'href="/relay/insights/\?days=7"[^>]*aria-current="true"', body)


def test_settings_save_is_a_full_replace_and_audited(client_for, superadmin, relay):
    client = client_for(superadmin)
    body = client.get("/relay/settings/").content.decode()
    assert "Needs owner approval in production" in body and "Notification recipients" in body
    assert "Email log · visitor emails" in body
    data = {
        "ai_enabled": "on",
        "model": "deepseek-flash",
        "days": ["1", "2", "3", "4", "5"],
        "start": "09:00",
        "end": "17:30",
        "out_of_hours_text": "Back tomorrow.",
        "reminder_minutes": "15",
        "second_reminder_minutes": "30",
        "email_snippet": "on",
        "greeting": "Hello.",
        "question_1": "One?",
        "question_2": "Two?",
        "question_3": "Three?",
        "question_4": "Four?",
        "confidence_threshold": "0.60",
        "daily_token_cap": "1000000",
        "no_contact_days": "90",
        "with_contact_days": "365",
        "allowed_origins": "https://www.vitalos.co.uk\nhttps://vitalos.co.uk/",
    }
    response = client.post("/relay/settings/", data)
    assert response.status_code == 302
    saved = relay.data["settings"]
    assert saved["reminderMinutes"] == 15 and saved["confidenceThreshold"] == 0.6
    assert saved["allowedOrigins"] == ["https://www.vitalos.co.uk", "https://vitalos.co.uk"]
    assert saved["businessHours"]["timezone"] == "Europe/London"
    assert saved["outOfHoursText"] == "Back tomorrow."
    event = AuditEvent.objects.get(action="relay.settings_changed")
    assert "reminderMinutes" in event.summary and "Back tomorrow" not in event.summary


def test_settings_validation(client_for, superadmin, relay):
    response = client_for(superadmin).post(
        "/relay/settings/", {"start": "18:00", "end": "09:00", "allowed_origins": "http://x"}
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Closing time must be after opening time." in body and "is not an https origin" in body
    assert not AuditEvent.objects.filter(action="relay.settings_changed").exists()


def test_realtime_widens_connect_src_on_relay_pages_only(client_for, superadmin, relay, seeded):
    services.remember_realtime(
        {"url": "https://abc.supabase.co", "key": "sb_publishable_x", "channel": "relay:a:" + "0" * 40}
    )
    client = client_for(superadmin)
    relay_page = client.get("/relay/inbox/")
    assert "wss://abc.supabase.co" in relay_page["Content-Security-Policy"]
    assert "realtime:relay:a:" + "0" * 40 in relay_page.content.decode()
    assert "wss://abc.supabase.co" not in client.get("/").get("Content-Security-Policy", "")


def test_realtime_config_rejects_non_https(relay):
    assert services.realtime_from({"url": "http://abc.supabase.co", "key": "k"}) is None
    assert services.realtime_from({"url": "https://abc.supabase.co/x", "key": "k"}) is None
    assert services.realtime_from({"url": "https://abc.supabase.co", "key": ""}) is None


def test_realtime_switch(client_for, superadmin, relay, settings):
    settings.RELAY_REALTIME_ENABLED = False
    services.remember_realtime({"url": "https://abc.supabase.co", "key": "sb_publishable_x"})
    response = client_for(superadmin).get("/relay/inbox/")
    assert "wss://abc.supabase.co" not in response["Content-Security-Policy"]
