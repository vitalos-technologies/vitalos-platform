"""Every customer-facing read goes through this module.

Each function takes the viewer's ``Membership`` and returns only what that organisation may see AND staff have
published. Views, search, notifications, exports, downloads and AI context builders all use these helpers, so
isolation is enforced on the server in one place and never by hiding things in templates. A record from another
organisation, or an unpublished one, behaves exactly like one that does not exist (``Http404``).
"""

from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.db.models import Exists, Max, OuterRef, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import (
    Approval,
    BriefStatus,
    BriefVersion,
    Challenge,
    ChangeRequest,
    Deliverable,
    DeliverableVersion,
    Event,
    File,
    FileVersion,
    FileVisibility,
    InformationRequest,
    ManagedService,
    Membership,
    Message,
    Milestone,
    MilestoneStatus,
    Notification,
    Project,
    ProjectItem,
    ServiceStatusReport,
    Thread,
    Update,
)


def _pk(value) -> int:
    """A primary key from untrusted input (a POST field or query string). Anything that is not a plain
    positive integer that fits the database column is a 404, exactly like a record that does not exist."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise Http404 from None
    if not 0 < number < 2**63:
        raise Http404
    return number


# --- Membership ---------------------------------------------------------------------------------------------------


def get_membership(user, organisation_id: int | None = None) -> Membership | None:
    """The user's live membership: accepted, not revoked, and the user and organisation both active."""
    if user is None or not user.is_authenticated or not user.is_active:
        return None
    qs = Membership.objects.select_related("user", "organisation").filter(
        user=user,
        is_active=True,
        accepted_at__isnull=False,
        revoked_at__isnull=True,
        organisation__is_active=True,
    )
    if organisation_id is not None:
        qs = qs.filter(organisation_id=organisation_id)
    return qs.order_by("organisation__name").first()


def live_member_users(organisation):
    """Members of ``organisation`` who may currently receive portal notifications and email."""
    return Membership.objects.select_related("user").filter(
        organisation=organisation,
        is_active=True,
        accepted_at__isnull=False,
        revoked_at__isnull=True,
        user__is_active=True,
        organisation__is_active=True,
    )


# --- Challenges, briefs ---------------------------------------------------------------------------------------------


def challenges(member):
    return Challenge.objects.filter(organisation_id=member.organisation_id, shared_at__isnull=False)


def get_challenge(member, pk):
    return get_object_or_404(challenges(member), pk=_pk(pk))


def briefs(member, challenge):
    """Proposed, agreed, superseded or change-requested versions; never drafts."""
    get_challenge(member, challenge.pk)
    return BriefVersion.objects.filter(challenge=challenge, proposed_at__isnull=False).exclude(
        status=BriefStatus.DRAFT
    )


def get_brief(member, pk):
    brief = get_object_or_404(
        BriefVersion.objects.select_related("challenge").exclude(status=BriefStatus.DRAFT),
        pk=_pk(pk),
        proposed_at__isnull=False,
    )
    if brief.challenge.organisation_id != member.organisation_id or brief.challenge.shared_at is None:
        raise Http404
    return brief


def agreed_brief(member, challenge):
    return briefs(member, challenge).filter(status=BriefStatus.AGREED).order_by("-number").first()


def pending_brief(member, challenge):
    return briefs(member, challenge).filter(status=BriefStatus.PROPOSED).order_by("-number").first()


# --- Projects -------------------------------------------------------------------------------------------------------


def projects(member):
    return Project.objects.select_related("challenge").filter(
        challenge__in=challenges(member), published_at__isnull=False
    )


def get_project(member, pk):
    return get_object_or_404(projects(member), pk=_pk(pk))


def milestones(member, project=None):
    qs = Milestone.objects.filter(project__in=projects(member), published_at__isnull=False)
    if project is not None:
        qs = qs.filter(project=project)
    return qs


def get_milestone(member, pk):
    return get_object_or_404(milestones(member).select_related("project__challenge"), pk=_pk(pk))


def items(member, project):
    return ProjectItem.objects.filter(project=project, published_at__isnull=False).filter(
        project__in=projects(member)
    )


def deliverables(member, project=None):
    qs = Deliverable.objects.select_related("project__challenge").filter(
        project__in=projects(member), published_at__isnull=False
    )
    if project is not None:
        qs = qs.filter(project=project)
    return qs


def get_deliverable(member, pk):
    return get_object_or_404(deliverables(member), pk=_pk(pk))


def versions(member, deliverable):
    """Shared, not withdrawn, newest first. A new version never inherits an earlier one's decision."""
    get_deliverable(member, deliverable.pk)
    return DeliverableVersion.objects.filter(
        deliverable=deliverable, shared_at__isnull=False, withdrawn_at__isnull=True
    )


def get_version(member, pk):
    version = get_object_or_404(
        DeliverableVersion.objects.select_related("deliverable__project__challenge", "file_version__file"),
        pk=_pk(pk),
        shared_at__isnull=False,
        withdrawn_at__isnull=True,
    )
    get_deliverable(member, version.deliverable_id)
    return version


def latest_version(member, deliverable):
    return versions(member, deliverable).order_by("-number").first()


def decisions(version):
    """Review and contractual decisions on this one version (staff and customer see the same facts)."""
    return list(Approval.objects.filter(version=version).order_by("created_at", "id"))


def has_newer_version(version) -> bool:
    """True when a newer version of the same deliverable is shared and not withdrawn."""
    return DeliverableVersion.objects.filter(
        deliverable_id=version.deliverable_id,
        number__gt=version.number,
        shared_at__isnull=False,
        withdrawn_at__isnull=True,
    ).exists()


def version_state(version) -> str:
    """approved, changes_requested, superseded or pending: from this version's own decisions only.

    This is the display state. Whether a decision may still be recorded is ``has_newer_version``, which the
    services check separately so that an approved version that was later superseded accepts nothing more."""
    rows = Approval.objects.filter(version=version, kind=Approval.Kind.REVIEW)
    if rows.filter(decision=Approval.Decision.APPROVED).exists():
        return "approved"
    newer = has_newer_version(version)
    if rows.filter(decision=Approval.Decision.CHANGES).exists():
        return "superseded" if newer else "changes_requested"
    return "superseded" if newer else "pending"


def contract_accepted(version) -> bool:
    return Approval.objects.filter(version=version, decision=Approval.Decision.ACCEPTED).exists()


# --- Questions, change requests, updates -----------------------------------------------------------------------------


def information_requests(member, challenge=None):
    qs = InformationRequest.objects.select_related("challenge", "project").filter(
        challenge__in=challenges(member), published_at__isnull=False
    )
    if challenge is not None:
        qs = qs.filter(challenge=challenge)
    return qs


def get_information_request(member, pk):
    return get_object_or_404(information_requests(member), pk=_pk(pk))


def change_requests(member, project=None):
    qs = ChangeRequest.objects.select_related("project__challenge").filter(project__in=projects(member))
    if project is not None:
        qs = qs.filter(project=project)
    return qs


def get_change_request(member, pk):
    return get_object_or_404(change_requests(member), pk=_pk(pk))


def updates(member, challenge=None, project=None):
    qs = Update.objects.select_related("challenge", "project").filter(
        challenge__in=challenges(member), status=Update.Status.PUBLISHED, published_at__isnull=False
    )
    if challenge is not None:
        qs = qs.filter(challenge=challenge)
    if project is not None:
        qs = qs.filter(project=project)
    return qs


def get_update(member, pk):
    return get_object_or_404(updates(member), pk=_pk(pk))


# --- Discussion -------------------------------------------------------------------------------------------------------


def threads(member, challenge=None):
    qs = Thread.objects.select_related("challenge", "milestone", "deliverable").filter(
        challenge__in=challenges(member), is_internal=False
    )
    if challenge is not None:
        qs = qs.filter(challenge=challenge)
    return qs


def get_thread(member, pk):
    return get_object_or_404(threads(member), pk=_pk(pk))


def messages(member, thread):
    get_thread(member, thread.pk)
    return Message.objects.select_related("author").filter(thread=thread)


def thread_for(member, challenge, *, milestone=None, deliverable=None):
    """The (customer-visible) thread for a scope, created on first use by a customer post."""
    qs = threads(member, challenge).filter(milestone=milestone, deliverable=deliverable)
    return qs.first()


# --- Files --------------------------------------------------------------------------------------------------------------


def files(member, challenge=None, project=None):
    qs = File.objects.select_related("challenge", "project").filter(
        Exists(FileVersion.objects.filter(file=OuterRef("pk"), customer_visible=True)),
        challenge__in=challenges(member),
        visibility=FileVisibility.CUSTOMER,
    )
    if challenge is not None:
        qs = qs.filter(challenge=challenge)
    if project is not None:
        qs = qs.filter(project=project)
    return qs


def get_file(member, pk):
    return get_object_or_404(files(member), pk=_pk(pk))


def file_versions(member, file):
    """The versions of a visible file that staff have made visible to the customer, newest first."""
    get_file(member, file.pk)
    return FileVersion.objects.filter(file=file, customer_visible=True)


def get_file_version(member, pk):
    version = get_object_or_404(
        FileVersion.objects.select_related("file__challenge"), pk=_pk(pk), customer_visible=True
    )
    get_file(member, version.file_id)
    return version


# --- Managed services -------------------------------------------------------------------------------------------------


def services(member):
    return ManagedService.objects.filter(organisation_id=member.organisation_id, published_at__isnull=False)


def get_service(member, pk):
    return get_object_or_404(services(member), pk=_pk(pk))


def latest_report(service):
    """Newest published report, or None."""
    return service.reports.filter(published_at__isnull=False).order_by("-reported_at", "-id").first()


def stale_before(now=None):
    """The one stale rule for status reports: a report made before this moment is older than
    ``PORTAL_STATUS_STALE_HOURS`` and is shown as stale (customer service cards and the staff Operations page)."""
    return (now or timezone.now()) - dt.timedelta(hours=settings.PORTAL_STATUS_STALE_HOURS)


def is_stale(reported_at, now=None) -> bool:
    return reported_at < stale_before(now)


def report_freshness(report) -> dict:
    """Source, last-updated and stale flag. A manual report older than PORTAL_STATUS_STALE_HOURS is stale."""
    if report is None:
        return {"has_report": False}
    stale = is_stale(report.reported_at)
    return {
        "has_report": True,
        "stale": stale,
        "source": report.source,
        "source_label": report.get_source_display(),
        "reported_at": report.reported_at,
        "is_manual": report.source == ServiceStatusReport.Source.MANUAL,
    }


# --- Notifications and activity ------------------------------------------------------------------------------------------


def notifications(user):
    """The user's notifications for organisations they are still a live member of."""
    org_ids = list(
        Membership.objects.filter(
            user=user, is_active=True, accepted_at__isnull=False, revoked_at__isnull=True
        ).values_list("organisation_id", flat=True)
    )
    return Notification.objects.filter(user=user, organisation_id__in=org_ids)


def events(member, challenge=None, project=None, since=None):
    """Activity the customer may see. An event stays in the table when staff unpublish or withdraw the thing
    it names, so it is filtered here, on read: the feed, the dashboard and the AI "what changed" source all
    use this one function and never show a record that is no longer visible."""
    qs = Event.objects.filter(challenge__in=challenges(member)).filter(
        Q(project__isnull=True) | Q(project__in=projects(member))
    )
    qs = qs.exclude(
        Q(version__isnull=False)
        & (Q(version__shared_at__isnull=True) | Q(version__withdrawn_at__isnull=False))
    ).exclude(Q(milestone__isnull=False) & Q(milestone__published_at__isnull=True))
    gated = {
        "deliverable": deliverables(member),
        "question": information_requests(member),
        "update": updates(member),
        "file": files(member),
    }
    for url_name, visible in gated.items():
        ids = list(visible.values_list("pk", flat=True))
        qs = qs.exclude(Q(url_name=url_name) & ~Q(url_kwargs__pk__in=ids))
    if challenge is not None:
        qs = qs.filter(challenge=challenge)
    if project is not None:
        qs = qs.filter(project=project)
    if since is not None:
        qs = qs.filter(occurred_at__gt=since)
    return qs


# --- Composite views the dashboard and the AI both use --------------------------------------------------------------------


def actions_required(member) -> list[dict]:
    """ "What we need from you": everything waiting on the customer, from visible records only."""
    out: list[dict] = []
    today = timezone.localdate()
    for q in information_requests(member).filter(status=InformationRequest.Status.OPEN):
        out.append(
            {
                "kind": "question",
                "title": q.question,
                "due": q.due_date,
                "overdue": bool(q.due_date and q.due_date < today),
                "url_name": "question",
                "url_kwargs": {"pk": q.pk},
                "needs": "contributor",
                "context": q.challenge.title,
            }
        )
    for ch in challenges(member):
        brief = pending_brief(member, ch)
        if brief:
            out.append(
                {
                    "kind": "brief",
                    "title": f"Review proposed brief v{brief.number}",
                    "due": None,
                    "overdue": False,
                    "url_name": "challenge",
                    "url_kwargs": {"pk": ch.pk},
                    "needs": "approver",
                    "context": ch.title,
                }
            )
    for deliverable in deliverables(member):
        version = latest_version(member, deliverable)
        if version and version.requires_approval and version_state(version) == "pending":
            out.append(
                {
                    "kind": "approval",
                    "title": f"Review {deliverable.title} (version {version.number})",
                    "due": None,
                    "overdue": False,
                    "url_name": "deliverable",
                    "url_kwargs": {"pk": deliverable.pk},
                    "needs": "approver",
                    "context": deliverable.project.name,
                }
            )
    for project in projects(member):
        for item in items(member, project).filter(
            party="customer", is_done=False, kind__in=["dependency", "blocker"]
        ):
            out.append(
                {
                    "kind": "dependency",
                    "title": item.text,
                    "due": item.due_date,
                    "overdue": bool(item.due_date and item.due_date < today),
                    "url_name": "project",
                    "url_kwargs": {"pk": project.pk},
                    "needs": "",
                    "context": project.name,
                }
            )
    out.sort(key=lambda row: (row["due"] is None, row["due"] or today))
    return out


def blockers(member) -> list[dict]:
    out = []
    for project in projects(member):
        for item in items(member, project).filter(kind="blocker", is_done=False):
            out.append({"text": item.text, "party": item.get_party_display(), "project": project})
        for m in milestones(member, project).filter(status=MilestoneStatus.BLOCKED):
            out.append({"text": f"Milestone blocked: {m.title}", "party": "Vitalos", "project": project})
    return out


def next_milestone(member):
    qs = milestones(member).exclude(status=MilestoneStatus.COMPLETE).select_related("project")
    dated = qs.filter(target_date__isnull=False).order_by("target_date", "position").first()
    return dated or qs.order_by("position", "id").first()


def recent_deliverable_versions(member, limit=5):
    return (
        DeliverableVersion.objects.select_related("deliverable__project")
        .filter(deliverable__in=deliverables(member), shared_at__isnull=False, withdrawn_at__isnull=True)
        .order_by("-shared_at")[:limit]
    )


def next_number(model, field_filter: dict) -> int:
    top = model.objects.filter(**field_filter).aggregate(top=Max("number"))["top"] or 0
    return top + 1


# --- Search ---------------------------------------------------------------------------------------------------------------


def search(member, query: str, limit: int = 8) -> dict[str, list]:
    """Search customer-visible fields of customer-visible records only. Internal notes are never searched."""
    q = (query or "").strip()
    if len(q) < 2:
        return {}
    q = q[:100]
    return {
        "Challenges": list(
            challenges(member).filter(
                Q(title__icontains=q) | Q(submitted_problem__icontains=q) | Q(status_note__icontains=q)
            )[:limit]
        ),
        "Projects": list(
            projects(member).filter(
                Q(name__icontains=q) | Q(summary__icontains=q) | Q(agreed_scope__icontains=q)
            )[:limit]
        ),
        "Deliverables": list(
            deliverables(member).filter(Q(title__icontains=q) | Q(description__icontains=q))[:limit]
        ),
        "Updates": list(updates(member).filter(Q(title__icontains=q) | Q(body__icontains=q))[:limit]),
        "Questions": list(
            information_requests(member).filter(Q(question__icontains=q) | Q(detail__icontains=q))[:limit]
        ),
        "Discussion": list(
            Message.objects.select_related("thread__challenge").filter(
                thread__in=threads(member), body__icontains=q
            )[:limit]
        ),
        "Files": list(files(member).filter(title__icontains=q)[:limit]),
    }
