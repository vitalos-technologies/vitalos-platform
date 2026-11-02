"""AI & Data Delivery and Operations read the client portal (WS-006, ADR-055, ADR-056).

Synthetic data only (``tests.portal_helpers.build_world``: two clearly fake organisations whose internal-only
fields carry marker strings). The pages are staff-only, show only operational facts, never an internal note,
link to Client portal staff pages only for staff who can open them, and run a fixed number of queries.
"""

from __future__ import annotations

import datetime as dt
import re

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.aidata import lifecycle
from apps.portal import selectors as portal_selectors
from apps.portal import services, staff_selectors
from apps.portal.models import (
    ChangeRequest,
    ChangeStatus,
    DeliverableVersion,
    Event,
    InformationRequest,
    ManagedService,
    Project,
    ServiceStatusReport,
)
from tests.portal_helpers import INTERNAL, build_world, make_staff
from tests.portal_helpers import client_for as portal_client

DELIVERY = "/ai-data/lifecycle/delivery/"
OPERATIONS = "/ai-data/lifecycle/operations/"
EXTRA_INTERNAL = {
    "late_milestone": "INTERNAL-LATE-MILESTONE-NOTE-j66",
    "blocker": "INTERNAL-BLOCKER-NOTE-k77",
    "change": "INTERNAL-CHANGE-REQUEST-NOTE-l88",
    "report": "INTERNAL-STATUS-REPORT-NOTE-m99",
    "project_c": "INTERNAL-PROJECT-C-NOTE-n00",
    "done": "INTERNAL-COMPLETE-PROJECT-NOTE-o11",
}


def _published(obj, staff):
    services.set_published(obj, True, actor=staff)
    return obj


@pytest.fixture
def world(db):
    return build_world()


@pytest.fixture
def delivery_world(world):
    """build_world plus: overdue milestones, blockers for each party, decided/superseded/withdrawn versions,
    change requests, draft and answered questions, and a complete project that must be left out."""
    w, staff = world, world.staff
    today = timezone.localdate()
    now = timezone.now()

    # Project A: one more milestone, late, after the "waiting for the customer" one.
    w.late = services.save_milestone(
        w.project_a,
        actor=staff,
        title="Matching rules agreed",
        status="in_progress",
        target_date=today - dt.timedelta(days=3),
        position=4,
        internal_notes=EXTRA_INTERNAL["late_milestone"],
    )
    # Blockers: Vitalos (past due), customer (no due date), customer but done (ignored).
    w.blocker_v = services.save_item(
        w.project_a,
        actor=staff,
        kind="blocker",
        party="vitalos",
        text="Test environment not yet provisioned",
        due_date=today - dt.timedelta(days=2),
        internal_notes=EXTRA_INTERNAL["blocker"],
    )
    services.save_item(w.project_a, actor=staff, kind="blocker", party="customer", text="Ledger access")
    services.save_item(
        w.project_a, actor=staff, kind="blocker", party="customer", text="Old blocker", is_done=True
    )
    services.save_item(w.project_b, actor=staff, kind="blocker", party="customer", text="Mailbox access")
    # v1 (project A) has waited ten days for a decision.
    DeliverableVersion.objects.filter(pk=w.v1.pk).update(shared_at=now - dt.timedelta(days=10))
    # Approved, changes requested, superseded (counts once), withdrawn and information-only versions.
    approved = services.save_deliverable(w.project_a, actor=staff, title="Approved deliverable")
    av = services.create_version(approved, actor=staff, summary="a1")
    services.share_version(av, actor=staff)
    _published(approved, staff)
    services.approve_version(w.approver, av, comment="Fine.")
    sent_back = services.save_deliverable(w.project_a, actor=staff, title="Sent back deliverable")
    _published(sent_back, staff)
    sv = services.create_version(sent_back, actor=staff, summary="s1")
    services.share_version(sv, actor=staff)
    services.request_version_changes(w.approver, sv, comment="Needs the totals.")
    superseded = services.save_deliverable(w.project_a, actor=staff, title="Two versions")
    _published(superseded, staff)
    for summary in ("first", "second"):
        services.share_version(services.create_version(superseded, actor=staff, summary=summary), actor=staff)
    withdrawn = services.save_deliverable(w.project_a, actor=staff, title="Withdrawn deliverable")
    wv = services.create_version(withdrawn, actor=staff, summary="w1")
    services.share_version(wv, actor=staff)
    services.withdraw_version(wv, actor=staff)
    info_only = services.save_deliverable(w.project_a, actor=staff, title="For information")
    services.share_version(
        services.create_version(info_only, actor=staff, summary="i1", requires_approval=False), actor=staff
    )
    # Change requests: one open, one decided.
    w.change = services.request_change(
        w.contrib, w.project_a, title="Add a supplier", description="One more supplier.", affects="scope"
    )
    ChangeRequest.objects.filter(pk=w.change.pk).update(internal_notes=EXTRA_INTERNAL["change"])
    closed = services.request_change(
        w.contrib, w.project_a, title="Earlier ask", description="Done.", affects="dates"
    )
    services.review_change(
        closed, to_status=ChangeStatus.UNDER_REVIEW, response="Looking.", note="", actor=staff
    )
    services.review_change(
        closed, to_status=ChangeStatus.DECLINED, response="Not this time.", note="", actor=staff
    )
    # Questions: q_a (challenge-level) was sent nine days ago; a draft and an answered one do not count.
    InformationRequest.objects.filter(pk=w.q_a.pk).update(published_at=now - dt.timedelta(days=9))
    services.ask_question(w.ch_a, question="Draft question", actor=staff, publish=False)
    answered = services.ask_question(w.ch_a, question="Answered question", actor=staff)
    services.answer_question(w.contrib, answered, body="Yes.")
    # Project C (same challenge as A, on hold): its only open milestone is overdue.
    w.project_c = services.save_project(
        w.ch_a,
        actor=staff,
        name="Statement import follow-on",
        status="on_hold",
        target_date=today - dt.timedelta(days=1),
        internal_notes=EXTRA_INTERNAL["project_c"],
    )
    services.save_milestone(
        w.project_c,
        actor=staff,
        title="Import design",
        status="blocked",
        target_date=today - dt.timedelta(days=5),
        position=1,
    )
    # A complete project: everything on it is left out.
    w.done = services.save_project(
        w.ch_a,
        actor=staff,
        name="Finished discovery",
        status="complete",
        internal_notes=EXTRA_INTERNAL["done"],
    )
    services.save_milestone(
        w.done,
        actor=staff,
        title="Never closed",
        status="in_progress",
        target_date=today - dt.timedelta(days=30),
    )
    services.save_item(
        w.done,
        actor=staff,
        kind="blocker",
        party="vitalos",
        text="Stale blocker",
        due_date=today - dt.timedelta(days=30),
    )
    ChangeRequest.objects.create(project=w.done, raised_by=w.contrib.user, title="Late ask", description="x")
    return w


def _body(client, url):
    response = client.get(url)
    assert response.status_code == 200
    return response.content.decode()


def _row(body, attr, pk):
    match = re.search(rf'<tr {attr}="{pk}".*?</tr>', body, re.S)
    assert match, f"no row {attr}={pk}"
    return match.group(0)


# --- Delivery: counts, table, attention -------------------------------------------------------------------


def test_delivery_counts_from_portal_records(delivery_world):
    w = delivery_world
    d = lifecycle.delivery_overview(staff_links=True)
    assert d.active_projects == 2  # A and B; C is on hold
    assert d.open_projects == 3 and d.other_open_projects == 1
    assert d.milestones_overdue == 2  # A's late milestone and C's; the complete project's is left out
    assert d.milestones_awaiting_customer == 1
    assert (d.blockers_vitalos, d.blockers_customer) == (1, 2)
    # v1 (A), vb1 (B) and the second version of "Two versions"; not approved, sent back, withdrawn or info-only.
    assert d.awaiting_decision == 3
    assert d.open_changes == 1
    assert d.open_questions == 2  # q_a (challenge A) and q_b (challenge B); not the draft or the answered one
    rows = {row.pk: row for row in d.projects}
    assert set(rows) == {w.project_a.pk, w.project_b.pk, w.project_c.pk}
    a, b, c = rows[w.project_a.pk], rows[w.project_b.pk], rows[w.project_c.pk]
    assert (a.blockers_vitalos, a.blockers_customer, a.awaiting_decision, a.open_changes) == (1, 1, 2, 1)
    assert (b.blockers_vitalos, b.blockers_customer, b.awaiting_decision, b.open_changes) == (0, 1, 1, 0)
    # A question on the challenge (no project) counts for each of its projects, and once in the total.
    assert (a.open_questions, b.open_questions, c.open_questions) == (1, 1, 1)
    # The next milestone is the first open one in the portal's order; C's is overdue.
    assert a.next_milestone.title == "Prototype review" and not a.next_milestone.overdue
    assert c.next_milestone.title == "Import design" and c.next_milestone.overdue
    assert c.target_passed and c.status_label == "On hold"


def test_delivery_attention_list(delivery_world, settings):
    d = lifecycle.delivery_overview(staff_links=True)
    kinds = sorted(item.kind for item in d.attention)
    assert kinds == ["blocker", "deliverable", "milestone", "milestone", "question"]
    assert d.attention_total == 5
    # Longest waiting first: v1 shared ten days ago, then q_a sent nine days ago.
    assert [item.kind for item in d.attention[:2]] == ["deliverable", "question"]
    urls = {item.kind: item.url for item in d.attention}
    assert urls["deliverable"] == f"/client-portal/deliverables/{delivery_world.deliv_a.pk}/"
    assert urls["question"] == f"/client-portal/challenges/{delivery_world.ch_a.pk}/#q-h"
    assert urls["blocker"] == f"/client-portal/projects/{delivery_world.project_a.pk}/#it-h"
    assert "Vitalos" in next(item.title for item in d.attention if item.kind == "blocker")


def test_attention_threshold_is_a_named_constant(delivery_world, monkeypatch):
    monkeypatch.setattr(lifecycle, "ATTENTION_AFTER_DAYS", 12)
    kinds = {item.kind for item in lifecycle.delivery_overview(staff_links=True).attention}
    assert "deliverable" not in kinds and "question" not in kinds
    monkeypatch.setattr(lifecycle, "ATTENTION_LIMIT", 2)
    d = lifecycle.delivery_overview(staff_links=True)
    assert len(d.attention) == 2 and d.attention_total == 3


def test_delivery_page_shows_counts_table_and_links(delivery_world):
    w = delivery_world
    body = _body(portal_client(w.staff), DELIVERY)
    assert 'data-testid="delivery-counts"' in body and 'data-testid="empty-state"' not in body
    assert "Vitalos 1 · Customer 2" in body
    row = _row(body, "data-project", w.project_a.pk)
    assert f'href="/client-portal/projects/{w.project_a.pk}/"' in row
    assert f'href="{w.opp_a.get_absolute_url()}"' in row and w.opp_a.ref in row
    assert f'href="/client-portal/orgs/{w.org_a.pk}/"' in row
    row_c = _row(body, "data-project", w.project_c.pk)
    assert 'data-testid="milestone-overdue"' in row_c and "Passed" in row_c
    # Every row links to its own opportunity: the challenge's.
    assert f'href="{w.opp_b.get_absolute_url()}"' in _row(body, "data-project", w.project_b.pk)
    # Complete projects are left out.
    assert "Finished discovery" not in body and "Never closed" not in body and "Stale blocker" not in body
    assert body.count('data-testid="attention-item"') == 5
    # The needs panel is honest about what is connected.
    assert "Connected" in body and "Blockers are shown. Summaries not built." in body
    assert "Not built. Acceptance criteria already exist on approved discovery." in body


def test_delivery_orders_by_latest_activity(delivery_world):
    w = delivery_world
    now = timezone.now()
    Project.objects.filter(pk__in=[w.project_a.pk, w.project_b.pk, w.project_c.pk]).update(
        updated_at=now - dt.timedelta(days=20)
    )
    Event.objects.update(occurred_at=now - dt.timedelta(days=20))
    Project.objects.filter(pk=w.project_b.pk).update(updated_at=now - dt.timedelta(days=1))
    services.event(w.ch_a, "test", "Synthetic activity", project=w.project_c)
    order = [row.pk for row in lifecycle.delivery_overview(staff_links=True).projects]
    assert order == [w.project_c.pk, w.project_b.pk, w.project_a.pk]


# --- Operations ---------------------------------------------------------------------------------------------


@pytest.fixture
def ops_world(world, settings):
    settings.PORTAL_STATUS_STALE_HOURS = 72
    w, staff = world, world.staff
    now = timezone.now()
    w.svc_incident = _published(
        services.save_service(w.org_b, name="Triage mailbox", project=w.project_b, actor=staff), staff
    )
    services.report_status(
        w.svc_incident,
        status="operational",
        summary="Fine",
        actor=staff,
        reported_at=now - dt.timedelta(hours=5),
    )
    w.incident = services.report_status(
        w.svc_incident,
        status="incident",
        summary="Mail is not arriving.",
        actor=staff,
        reported_at=now - dt.timedelta(hours=1),
    )
    ServiceStatusReport.objects.filter(pk=w.incident.pk).update(internal_notes=EXTRA_INTERNAL["report"])
    w.svc_stale = _published(services.save_service(w.org_a, name="Statement import", actor=staff), staff)
    services.report_status(
        w.svc_stale,
        status="degraded",
        summary="Two late.",
        actor=staff,
        reported_at=now - dt.timedelta(hours=73),
    )
    w.svc_fresh_edge = _published(services.save_service(w.org_a, name="Nightly export", actor=staff), staff)
    services.report_status(
        w.svc_fresh_edge,
        status="operational",
        summary="",
        actor=staff,
        reported_at=now - dt.timedelta(hours=71),
    )
    w.svc_live = _published(services.save_service(w.org_a, name="Live feed", actor=staff), staff)
    ServiceStatusReport.objects.create(
        service=w.svc_live, status="maintenance", source="live", reported_at=now, published_at=now
    )
    w.svc_hidden = services.save_service(w.org_a, name="Not yet published", actor=staff)
    # build_world's published service gets a newer report that is not published: staff see it as the latest.
    w.unpublished_report = services.report_status(
        w.svc_a, status="operational", summary="Staff check", actor=staff, publish=False
    )
    return w


def test_operations_latest_report_and_stale(ops_world):
    w = ops_world
    o = lifecycle.operations_overview(staff_links=True)
    rows = {row.pk: row for row in o.services}
    assert o.total == 6  # build_world's svc_a plus five here
    incident = rows[w.svc_incident.pk]
    assert incident.status == "incident" and incident.status_label == "Incident" and incident.tone == "error"
    assert incident.source_label == "Manually reported by Vitalos" and not incident.stale
    assert incident.project == "Triage pilot"
    assert rows[w.svc_stale.pk].stale and rows[w.svc_stale.pk].status == "degraded"
    assert not rows[w.svc_fresh_edge.pk].stale
    assert rows[w.svc_live.pk].source_label == "Live"
    hidden = rows[w.svc_hidden.pk]
    assert not hidden.has_report and hidden.status_label == "No report yet" and not hidden.stale
    assert hidden.visibility_note == "Not published"
    assert (o.problems, o.stale, o.no_report) == (2, 1, 1)
    latest = rows[w.svc_a.pk]
    assert latest.summary == "Staff check" and not latest.customer_visible
    assert latest.visibility_note == "Latest report not published"
    assert rows[w.svc_incident.pk].customer_visible and rows[w.svc_incident.pk].visibility_note == ""
    # Problems first: the incident, then the degraded (stale) service.
    assert [row.pk for row in o.services[:2]] == [w.svc_incident.pk, w.svc_stale.pk]


def test_operations_stale_rule_is_the_portals(ops_world):
    """One definition: for the same report, the staff page and the customer card's report_freshness agree.
    (Staff see the newest report, published or not; the customer card uses the newest published one.)"""
    rows = {row.pk: row for row in lifecycle.operations_overview(staff_links=True).services}
    for service in ManagedService.objects.all():
        report = service.reports.order_by("-reported_at", "-id").first()
        fresh = portal_selectors.report_freshness(report)
        assert rows[service.pk].stale == fresh.get("stale", False), service.name
    assert sum(row.stale for row in rows.values()) == 1


def test_operations_page(ops_world):
    w = ops_world
    body = _body(portal_client(w.staff), OPERATIONS)
    assert 'data-testid="operations-counts"' in body
    row = _row(body, "data-service", w.svc_stale.pk)
    assert 'data-testid="service-stale"' in row and "Degraded" in row
    assert f'href="/client-portal/services/{w.svc_stale.pk}/report/"' in row
    assert f'href="/client-portal/orgs/{w.org_a.pk}/#svc-h"' in row
    assert "Manually reported by Vitalos" in row
    assert 'data-testid="service-stale"' not in _row(body, "data-service", w.svc_fresh_edge.pk)
    assert "Not published" in _row(body, "data-service", w.svc_hidden.pk)
    assert "Mail is not arriving." in _row(body, "data-service", w.svc_incident.pk)
    for label in ("Incident summaries", "Exceptions", "Monthly report data"):
        assert label in body
    assert body.count("Not built.") >= 3


# --- Access, links, internal notes ----------------------------------------------------------------------------


@pytest.mark.parametrize("url", [DELIVERY, OPERATIONS])
def test_access_is_unchanged(db, url, viewer, norole, lead):
    from django.test import Client

    from tests.conftest import login

    for user in (viewer, norole):
        assert login(Client(), user).get(url).status_code == 403
    anonymous = Client().get(url)
    assert anonymous.status_code == 302 and "/login/" in anonymous["Location"]
    assert login(Client(), lead).get(url).status_code == 200


def test_staff_portal_links_only_for_staff_who_can_open_them(delivery_world, ops_world, monkeypatch):
    client = portal_client(delivery_world.staff)
    for url in (DELIVERY, OPERATIONS):
        assert "/client-portal/" in _body(client, url)
    from apps.portal import access

    monkeypatch.setattr(access, "staff_can_manage", lambda user: False)
    for url in (DELIVERY, OPERATIONS):
        body = _body(client, url)
        assert "/client-portal/" not in body
        assert delivery_world.project_a.name in body or url == OPERATIONS
    # The opportunity link is an AI & Data page, which this viewer can open.
    assert delivery_world.opp_a.get_absolute_url() in _body(client, DELIVERY)


def test_no_internal_notes_on_either_page(delivery_world, ops_world):
    client = portal_client(delivery_world.staff)
    for url in (DELIVERY, OPERATIONS):
        body = _body(client, url)
        for marker in (*INTERNAL.values(), *EXTRA_INTERNAL.values()):
            assert marker not in body, (url, marker)


# --- Empty states -------------------------------------------------------------------------------------------------


def test_empty_states_say_how_data_arrives(db):
    staff = make_staff()
    client = portal_client(staff)
    body = _body(client, DELIVERY)
    assert 'data-testid="empty-state"' in body and "No projects in delivery" in body
    assert "Link to client portal" in body and "Create portal project from proposal" in body
    assert 'href="/ai-data/pipeline/?stage=won"' in body
    body = _body(client, OPERATIONS)
    assert 'data-testid="empty-state"' in body and "No managed services yet" in body
    assert "Add one on the organisation" in body and 'href="/client-portal/"' in body


def test_only_complete_projects_is_still_empty(world):
    Project.objects.update(status="complete")
    body = _body(portal_client(world.staff), DELIVERY)
    assert "No projects in delivery" in body and 'data-testid="delivery-counts"' not in body


# --- Queries --------------------------------------------------------------------------------------------------------


def _add_projects(w, count):
    today = timezone.localdate()
    for n in range(count):
        p = services.save_project(w.ch_a, actor=w.staff, name=f"Extra {n}", status="active")
        services.save_milestone(
            p, actor=w.staff, title="M", status="in_progress", target_date=today - dt.timedelta(days=2)
        )
        services.save_item(p, actor=w.staff, kind="blocker", party="customer", text="B", due_date=today)
        services.ask_question(w.ch_a, question=f"Q{n}", project=p, actor=w.staff)
        svc = services.save_service(w.org_a, name=f"Service {n}", project=p, actor=w.staff)
        services.report_status(svc, status="degraded", summary="", actor=w.staff, publish=False)


def test_query_count_does_not_grow_with_rows(
    delivery_world, django_assert_num_queries, django_assert_max_num_queries
):
    w = delivery_world
    with django_assert_num_queries(6):
        lifecycle.delivery_overview(staff_links=True)
    with django_assert_num_queries(2):
        lifecycle.operations_overview(staff_links=True)
    client = portal_client(w.staff)
    counts = {}
    for size in ("small", "large"):
        if size == "large":
            _add_projects(w, 15)
        for url in (DELIVERY, OPERATIONS):
            with CaptureQueriesContext(connection) as ctx:
                assert client.get(url).status_code == 200
            counts[(size, url)] = len(ctx.captured_queries)
    assert counts[("small", DELIVERY)] == counts[("large", DELIVERY)]
    assert counts[("small", OPERATIONS)] == counts[("large", OPERATIONS)]
    with django_assert_max_num_queries(counts[("small", DELIVERY)]):
        client.get(DELIVERY)
    with django_assert_max_num_queries(counts[("small", OPERATIONS)]):
        client.get(OPERATIONS)


# --- The portal's own rule, written as a set ------------------------------------------------------------------------


def test_awaiting_decision_set_matches_version_state(delivery_world):
    awaiting = set(staff_selectors.awaiting_decision_versions().values_list("pk", flat=True))
    for v in DeliverableVersion.objects.filter(shared_at__isnull=False, withdrawn_at__isnull=True):
        expected = v.requires_approval and portal_selectors.version_state(v) == "pending"
        assert (v.pk in awaiting) == expected, v
    assert [v.pk for v in staff_selectors.outstanding_decisions()["versions"]] == list(
        staff_selectors.awaiting_decision_versions().order_by("shared_at", "id").values_list("pk", flat=True)
    )
