"""Delivery and Operations for the AI & Data lifecycle pages (ADR-055, WS-006), read from the client portal
(ADR-056). Nothing here writes and nothing is invented: every number counts real portal records.

* Staff-only, like every AI & Data page (SuperAdmin and ServiceLead). Links to the Client portal staff pages are
  built only when the caller says the viewer may open them (``staff_links``), so they are never in the page
  otherwise.
* Rows reach the template as view models built from an allow-list of fields. The queries never load
  ``internal_notes`` (or any other internal-only field), so the pages cannot show one.
* Each page is a fixed number of queries whatever the number of rows: six for Delivery, two for Operations.
* The portal's own rules are reused, not redefined: "awaiting a customer decision" is
  ``staff_selectors.awaiting_decision_versions`` and "stale" is ``selectors.stale_before``
  (``PORTAL_STATUS_STALE_HOURS``).
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from django.conf import settings
from django.db.models import F, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce, Greatest
from django.urls import reverse
from django.utils import timezone

from apps.portal import selectors as portal_selectors
from apps.portal import staff_selectors
from apps.portal.models import (
    ChangeRequest,
    ChangeStatus,
    Event,
    InformationRequest,
    ItemKind,
    ManagedService,
    Milestone,
    MilestoneStatus,
    Party,
    Project,
    ProjectItem,
    ProjectStatus,
    ServiceStatusReport,
)

#: A shared deliverable version, or a question sent to the customer, still waiting after this many days is
#: listed under "Needs attention". Seven days is one weekly status-update cycle, the rhythm the statement-of-work
#: template suggests (docs/ai-data/commercial/08). It is a prompt to follow up, not the contractual review
#: period, which each statement of work sets (DECISIONS 137).
ATTENTION_AFTER_DAYS = 7
#: "Needs attention" is a short list: the longest-waiting items first, then "Showing n of m".
ATTENTION_LIMIT = 8

OPEN_CHANGE_STATUSES = (ChangeStatus.SUBMITTED, ChangeStatus.UNDER_REVIEW)
PROJECT_TONES = {
    ProjectStatus.PLANNING: "neutral",
    ProjectStatus.ACTIVE: "info",
    ProjectStatus.ON_HOLD: "warn",
    ProjectStatus.HANDOVER: "info",
}
SERVICE_TONES = {
    ServiceStatusReport.Status.OPERATIONAL: "ok",
    ServiceStatusReport.Status.DEGRADED: "warn",
    ServiceStatusReport.Status.INCIDENT: "error",
    ServiceStatusReport.Status.MAINTENANCE: "info",
    ServiceStatusReport.Status.UNKNOWN: "neutral",
}
#: Operations lists problems first: incident, degraded, no report yet, unknown, maintenance, operating normally.
SERVICE_ORDER = {
    ServiceStatusReport.Status.INCIDENT: 0,
    ServiceStatusReport.Status.DEGRADED: 1,
    "": 2,
    ServiceStatusReport.Status.UNKNOWN: 3,
    ServiceStatusReport.Status.MAINTENANCE: 4,
    ServiceStatusReport.Status.OPERATIONAL: 5,
}
PROBLEM_STATUSES = (ServiceStatusReport.Status.INCIDENT, ServiceStatusReport.Status.DEGRADED)


def _url(staff_links: bool, name: str, pk: int, anchor: str = "") -> str:
    if not staff_links:
        return ""
    return reverse(f"portaladmin:{name}", args=[pk]) + (f"#{anchor}" if anchor else "")


def _days(since: dt.date, today: dt.date) -> int:
    return max(0, (today - since).days)


def _late(days: int) -> str:
    return f"{days} day{'s' if days != 1 else ''} overdue"


def _waiting(days: int) -> str:
    return f"waiting {days} day{'s' if days != 1 else ''}"


# --- Delivery ---------------------------------------------------------------------------------------------------


@dataclass
class NextMilestone:
    title: str
    status_label: str
    target_date: dt.date | None
    overdue: bool


@dataclass
class ProjectRow:
    pk: int
    name: str
    status: str
    status_label: str
    tone: str
    published: bool
    target_date: dt.date | None
    target_passed: bool
    last_activity: dt.datetime
    organisation: str
    organisation_active: bool
    challenge_id: int
    challenge_title: str
    opportunity_ref: str
    opportunity_title: str
    opportunity_url: str
    project_url: str = ""
    organisation_url: str = ""
    next_milestone: NextMilestone | None = None
    blockers_vitalos: int = 0
    blockers_customer: int = 0
    awaiting_decision: int = 0
    open_questions: int = 0
    open_changes: int = 0

    @property
    def open_blockers(self) -> int:
        return self.blockers_vitalos + self.blockers_customer


@dataclass
class AttentionItem:
    kind: str
    title: str
    detail: str
    evidence: str
    since: dt.date
    url: str
    action: str


@dataclass
class DeliveryOverview:
    projects: list[ProjectRow] = field(default_factory=list)
    attention: list[AttentionItem] = field(default_factory=list)
    attention_total: int = 0
    active_projects: int = 0
    milestones_overdue: int = 0
    milestones_awaiting_customer: int = 0
    blockers_vitalos: int = 0
    blockers_customer: int = 0
    awaiting_decision: int = 0
    open_changes: int = 0
    open_questions: int = 0
    attention_after_days: int = ATTENTION_AFTER_DAYS

    @property
    def open_projects(self) -> int:
        return len(self.projects)

    @property
    def other_open_projects(self) -> int:
        return self.open_projects - self.active_projects

    @property
    def open_blockers(self) -> int:
        return self.blockers_vitalos + self.blockers_customer


def open_projects():
    """Projects in delivery: planning, active, on hold or handover. Complete projects are left out."""
    return Project.objects.exclude(status=ProjectStatus.COMPLETE)


def _project_rows(staff_links: bool, today: dt.date) -> list[ProjectRow]:
    # Latest activity: the newest customer-visible event on the project, or the project's own last change.
    newest_event = (
        Event.objects.filter(project=OuterRef("pk")).order_by("-occurred_at").values("occurred_at")[:1]
    )
    queryset = (
        open_projects()
        .select_related("challenge__organisation", "challenge__opportunity")
        .only(
            "id",
            "name",
            "status",
            "target_date",
            "published_at",
            "updated_at",
            "challenge",
            "challenge__title",
            "challenge__organisation",
            "challenge__organisation__name",
            "challenge__organisation__is_active",
            "challenge__opportunity",
            "challenge__opportunity__number",
            "challenge__opportunity__title",
        )
        .annotate(last_activity=Greatest(F("updated_at"), Coalesce(Subquery(newest_event), F("updated_at"))))
        .order_by("-last_activity", "-id")
    )
    rows = []
    for project in queryset:
        challenge = project.challenge
        opportunity = challenge.opportunity
        rows.append(
            ProjectRow(
                pk=project.pk,
                name=project.name,
                status=project.status,
                status_label=project.get_status_display(),
                tone=PROJECT_TONES.get(project.status, "neutral"),
                published=project.published_at is not None,
                target_date=project.target_date,
                target_passed=bool(project.target_date and project.target_date < today),
                last_activity=project.last_activity,
                organisation=challenge.organisation.name,
                organisation_active=challenge.organisation.is_active,
                challenge_id=challenge.pk,
                challenge_title=challenge.title,
                opportunity_ref=opportunity.ref if opportunity else "",
                opportunity_title=opportunity.title if opportunity else "",
                opportunity_url=opportunity.get_absolute_url() if opportunity else "",
                project_url=_url(staff_links, "project", project.pk),
                organisation_url=_url(staff_links, "org", challenge.organisation_id),
            )
        )
    return rows


def delivery_overview(*, staff_links: bool, today: dt.date | None = None, now=None) -> DeliveryOverview:
    """Contracted work in progress, from client portal records only. Six queries."""
    today = today or timezone.localdate()
    now = now or timezone.now()
    out = DeliveryOverview(projects=_project_rows(staff_links, today))
    by_pk = {row.pk: row for row in out.projects}
    by_challenge: dict[int, list[ProjectRow]] = defaultdict(list)
    for row in out.projects:
        by_challenge[row.challenge_id].append(row)
    out.active_projects = sum(1 for row in out.projects if row.status == ProjectStatus.ACTIVE)
    found: list[AttentionItem] = []

    def where(row: ProjectRow) -> str:
        return f"{row.organisation} / {row.name}"

    # Milestones not complete, in the portal's order (position, target date): the first is the next one.
    milestones = (
        Milestone.objects.filter(project__in=open_projects())
        .exclude(status=MilestoneStatus.COMPLETE)
        .order_by("project_id", "position", "target_date", "id")
        .values("id", "project_id", "title", "status", "target_date")
    )
    labels = dict(MilestoneStatus.choices)
    for m in milestones:
        row = by_pk.get(m["project_id"])
        if row is None:  # the project was completed between the two queries
            continue
        overdue = bool(m["target_date"] and m["target_date"] < today)
        if row.next_milestone is None:
            row.next_milestone = NextMilestone(
                title=m["title"],
                status_label=labels.get(m["status"], m["status"]),
                target_date=m["target_date"],
                overdue=overdue,
            )
        if m["status"] == MilestoneStatus.AWAITING_CUSTOMER:
            out.milestones_awaiting_customer += 1
        if overdue:
            out.milestones_overdue += 1
            days = _days(m["target_date"], today)
            found.append(
                AttentionItem(
                    kind="milestone",
                    title=f"Milestone overdue: {m['title']}",
                    detail=where(row),
                    evidence=f"Target {m['target_date']:%-d %b %Y}; {_late(days)}. {labels.get(m['status'], '')}.",
                    since=m["target_date"],
                    url=_url(staff_links, "project", row.pk, "ms-h"),
                    action="Open the project",
                )
            )

    # Open blockers, by who has to clear them.
    blockers = (
        ProjectItem.objects.filter(project__in=open_projects(), kind=ItemKind.BLOCKER, is_done=False)
        .order_by("due_date", "id")
        .values("id", "project_id", "party", "text", "due_date")
    )
    for item in blockers:
        row = by_pk.get(item["project_id"])
        if row is None:
            continue
        if item["party"] == Party.CUSTOMER:
            row.blockers_customer += 1
            out.blockers_customer += 1
        else:
            row.blockers_vitalos += 1
            out.blockers_vitalos += 1
        if item["due_date"] and item["due_date"] < today:
            days = _days(item["due_date"], today)
            who = Party(item["party"]).label if item["party"] in Party.values else item["party"]
            found.append(
                AttentionItem(
                    kind="blocker",
                    title=f"Blocker past due ({who}): {item['text']}",
                    detail=where(row),
                    evidence=f"Due {item['due_date']:%-d %b %Y}; {_late(days)}.",
                    since=item["due_date"],
                    url=_url(staff_links, "project", row.pk, "it-h"),
                    action="Open the project",
                )
            )

    # Deliverable versions waiting for the customer's decision (the portal's own definition).
    waiting_since = now - dt.timedelta(days=ATTENTION_AFTER_DAYS)
    versions = (
        staff_selectors.awaiting_decision_versions()
        .filter(deliverable__project__in=open_projects())
        .order_by("shared_at", "id")
        .values(
            "id", "number", "shared_at", "deliverable_id", "deliverable__title", "deliverable__project_id"
        )
    )
    for v in versions:
        row = by_pk.get(v["deliverable__project_id"])
        if row is None:
            continue
        row.awaiting_decision += 1
        out.awaiting_decision += 1
        if v["shared_at"] < waiting_since:
            shared = timezone.localdate(v["shared_at"])
            found.append(
                AttentionItem(
                    kind="deliverable",
                    title=f"Waiting for a decision: {v['deliverable__title']} v{v['number']}",
                    detail=where(row),
                    evidence=f"Shared {shared:%-d %b %Y}; {_waiting(_days(shared, today))}.",
                    since=shared,
                    url=_url(staff_links, "deliverable", v["deliverable_id"]),
                    action="Open the deliverable",
                )
            )

    # Questions sent to the customer and not yet answered. A question on the challenge (no project) counts
    # for each project of that challenge in the table, and once in the total.
    questions = (
        InformationRequest.objects.filter(status=InformationRequest.Status.OPEN, published_at__isnull=False)
        .filter(
            Q(project__in=open_projects())
            | Q(project__isnull=True, challenge_id__in=open_projects().values("challenge_id"))
        )
        .order_by("published_at", "id")
        .values("id", "question", "challenge_id", "project_id", "published_at")
    )
    for q in questions:
        rows = (
            [by_pk[q["project_id"]]] if q["project_id"] in by_pk else by_challenge.get(q["challenge_id"], [])
        )
        if not rows:
            continue
        for row in rows:
            row.open_questions += 1
        out.open_questions += 1
        if q["published_at"] < waiting_since:
            sent = timezone.localdate(q["published_at"])
            first = rows[0]
            found.append(
                AttentionItem(
                    kind="question",
                    title=f"Unanswered question: {q['question']}",
                    detail=where(first)
                    if q["project_id"]
                    else f"{first.organisation} / {first.challenge_title}",
                    evidence=f"Sent {sent:%-d %b %Y}; {_waiting(_days(sent, today))}.",
                    since=sent,
                    url=_url(staff_links, "challenge", q["challenge_id"], "q-h"),
                    action="Open the challenge",
                )
            )

    # Change requests the customer raised that staff have not decided yet.
    changes = Counter(
        ChangeRequest.objects.filter(
            project__in=open_projects(), status__in=OPEN_CHANGE_STATUSES
        ).values_list("project_id", flat=True)
    )
    for project_id, count in changes.items():
        row = by_pk.get(project_id)
        if row is None:
            continue
        row.open_changes = count
        out.open_changes += count

    found.sort(key=lambda item: (item.since, item.kind, item.title))
    out.attention_total = len(found)
    out.attention = found[:ATTENTION_LIMIT]
    return out


# --- Operations --------------------------------------------------------------------------------------------------


@dataclass
class ServiceRow:
    pk: int
    name: str
    organisation: str
    organisation_active: bool
    project: str
    published: bool
    has_report: bool = False
    status: str = ""
    status_label: str = "No report yet"
    tone: str = "neutral"
    source_label: str = ""
    summary: str = ""
    reported_at: dt.datetime | None = None
    stale: bool = False
    customer_visible: bool = False
    visibility_note: str = ""
    organisation_url: str = ""
    project_url: str = ""
    report_url: str = ""

    @property
    def problem(self) -> bool:
        return self.status in PROBLEM_STATUSES


@dataclass
class OperationsOverview:
    services: list[ServiceRow] = field(default_factory=list)
    stale_hours: int = 0

    @property
    def total(self) -> int:
        return len(self.services)

    @property
    def problems(self) -> int:
        return sum(1 for s in self.services if s.problem)

    @property
    def stale(self) -> int:
        return sum(1 for s in self.services if s.stale)

    @property
    def no_report(self) -> int:
        return sum(1 for s in self.services if not s.has_report)


def operations_overview(*, staff_links: bool, now=None) -> OperationsOverview:
    """Managed services across organisations with their latest status report. Two queries.

    "Latest" is the newest report staff recorded, published or not; ``customer_visible`` says whether the
    customer sees it (the service and the report are both published). Stale follows the portal's rule."""
    now = now or timezone.now()
    newest = (
        ServiceStatusReport.objects.filter(service=OuterRef("pk"))
        .order_by("-reported_at", "-id")
        .values("pk")[:1]
    )
    services = list(
        ManagedService.objects.select_related("organisation", "project")
        .only(
            "id",
            "name",
            "published_at",
            "organisation",
            "organisation__name",
            "organisation__is_active",
            "project",
            "project__name",
        )
        .annotate(latest_report_id=Subquery(newest))
    )
    report_ids = [s.latest_report_id for s in services if s.latest_report_id]
    reports = {
        r["id"]: r
        for r in ServiceStatusReport.objects.filter(pk__in=report_ids).values(
            "id", "status", "source", "summary", "reported_at", "published_at"
        )
    }
    cutoff = portal_selectors.stale_before(now)
    statuses = dict(ServiceStatusReport.Status.choices)
    sources = dict(ServiceStatusReport.Source.choices)
    rows = []
    for s in services:
        row = ServiceRow(
            pk=s.pk,
            name=s.name,
            organisation=s.organisation.name,
            organisation_active=s.organisation.is_active,
            project=s.project.name if s.project_id else "",
            published=s.published_at is not None,
            organisation_url=_url(staff_links, "org", s.organisation_id, "svc-h"),
            project_url=_url(staff_links, "project", s.project_id) if s.project_id else "",
            report_url=_url(staff_links, "service_report", s.pk),
        )
        report = reports.get(s.latest_report_id)
        if report is not None:
            row.has_report = True
            row.status = report["status"]
            row.status_label = statuses.get(report["status"], report["status"])
            row.tone = SERVICE_TONES.get(report["status"], "neutral")
            row.source_label = sources.get(report["source"], report["source"])
            row.summary = report["summary"]
            row.reported_at = report["reported_at"]
            row.stale = report["reported_at"] < cutoff
            row.customer_visible = row.published and report["published_at"] is not None
        if not row.published:
            row.visibility_note = "Not published"
        elif row.has_report and not row.customer_visible:
            row.visibility_note = "Latest report not published"
        rows.append(row)
    rows.sort(
        key=lambda r: (SERVICE_ORDER.get(r.status, 9), not r.stale, r.organisation.lower(), r.name.lower())
    )
    return OperationsOverview(services=rows, stale_hours=settings.PORTAL_STATUS_STALE_HOURS)
