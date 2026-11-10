"""Staff-side reads for the Client portal admin. Staff see everything, including internal-only fields, so these
are used ONLY by staff views (``staff_required``, or the AI & Data pages, which need the same SuperAdmin or
ServiceLead role), never by customer views, search, AI or notifications."""

from __future__ import annotations

from django.db.models import Exists, OuterRef, Q

from .models import (
    Approval,
    BriefStatus,
    BriefVersion,
    Challenge,
    ChangeRequest,
    ChangeStatus,
    Deliverable,
    DeliverableVersion,
    EmailDelivery,
    Event,
    InformationRequest,
    Invitation,
    Membership,
    Organisation,
)


def awaiting_decision_versions():
    """Deliverable versions waiting for a customer decision, in one query: the latest shared, not withdrawn
    version of its deliverable, needing approval, with no review decision (approved or changes requested).
    This is ``selectors.version_state(v) == "pending"`` on the latest version, written as a set."""
    shared = DeliverableVersion.objects.filter(shared_at__isnull=False, withdrawn_at__isnull=True)
    newer = shared.filter(deliverable=OuterRef("deliverable"), number__gt=OuterRef("number"))
    decided = Approval.objects.filter(
        version=OuterRef("pk"),
        kind=Approval.Kind.REVIEW,
        decision__in=[Approval.Decision.APPROVED, Approval.Decision.CHANGES],
    )
    return shared.filter(requires_approval=True).exclude(Exists(newer)).exclude(Exists(decided))


def outstanding_decisions() -> dict:
    """What is waiting on customers, across every organisation."""
    versions = list(
        awaiting_decision_versions()
        .select_related("deliverable__project__challenge__organisation")
        .order_by("shared_at", "id")
    )
    return {
        "versions": versions,
        "briefs": BriefVersion.objects.select_related("challenge__organisation").filter(
            status=BriefStatus.PROPOSED
        ),
        "questions": InformationRequest.objects.select_related("challenge__organisation").filter(
            status=InformationRequest.Status.OPEN, published_at__isnull=False
        ),
        "changes": ChangeRequest.objects.select_related("project__challenge__organisation").filter(
            status__in=[ChangeStatus.SUBMITTED, ChangeStatus.UNDER_REVIEW]
        ),
    }


def recent_customer_activity(limit=15):
    return Event.objects.select_related("challenge__organisation").filter(actor_is_customer=True)[:limit]


def failed_deliveries():
    """Emails whose last attempt failed (retrying or failed for good); not those staff cancelled."""
    return EmailDelivery.objects.filter(status=EmailDelivery.Status.FAILED).exclude(
        last_error=EmailDelivery.CANCELLED_ERROR
    )


def organisations():
    return Organisation.objects.all()


def members(organisation):
    return Membership.objects.select_related("user").filter(organisation=organisation).order_by("-created_at")


# State shown on the Members table and the Client portal users list: key (badge tone) and label.
STATE_LABELS = {
    "invited": "Invited",
    "expired": "Invitation expired",
    "active": "Active",
    "suspended": "Suspended",
}


def member_state(member, latest_invitation=None) -> str:
    """invited, expired, active or suspended. ``latest_invitation`` saves a query when already loaded."""
    if member.revoked_at is not None or not member.is_active:
        return "suspended"
    if member.accepted_at:
        return "active"
    inv = latest_invitation
    if inv is None:
        inv = Invitation.objects.filter(membership=member).order_by("-created_at").first()
    return "invited" if inv is not None and inv.is_usable else "expired"


def member_rows(organisation) -> list[dict]:
    """The Members table: each membership with its state and the actions that apply to it."""
    rows = []
    for m in members(organisation).prefetch_related("invitations"):
        invitations = sorted(m.invitations.all(), key=lambda inv: inv.created_at, reverse=True)
        state = member_state(m, invitations[0] if invitations else None)
        rows.append(
            {
                "member": m,
                "state": state,
                "state_label": STATE_LABELS[state],
                "pending": not m.accepted_at and state in ("invited", "expired"),
                "can_preview": state == "active",
                "can_suspend": state == "active",
                "can_restore": state == "suspended",
                "can_resend": not m.accepted_at and state != "suspended",
                "can_cancel": not m.accepted_at,
                "can_remove": bool(m.accepted_at),
            }
        )
    return rows


def customer_accounts() -> list[dict]:
    """Client portal accounts across organisations (no staff role, at least one membership), for the
    SuperAdmin list in Settings. Erased accounts have no membership, so they never appear."""
    from django.contrib.auth import get_user_model

    from apps.accounts.roles import ROLES

    User = get_user_model()
    users = (
        User.objects.filter(portal_memberships__isnull=False, is_superuser=False)
        .exclude(groups__name__in=ROLES)
        .distinct()
        .order_by("email")
        .prefetch_related("portal_memberships__organisation", "portal_memberships__invitations")
    )
    rows = []
    for user in users:
        memberships = []
        for m in sorted(user.portal_memberships.all(), key=lambda m: m.organisation.name):
            invitations = sorted(m.invitations.all(), key=lambda inv: inv.created_at, reverse=True)
            state = member_state(m, invitations[0] if invitations else None)
            memberships.append({"member": m, "state": state, "state_label": STATE_LABELS[state]})
        states = {row["state"] for row in memberships}
        if "active" in states:
            overall = "active"
        elif states & {"invited", "expired"}:
            overall = "invited" if "invited" in states else "expired"
        else:
            overall = "suspended"
        rows.append(
            {
                "user": user,
                "memberships": memberships,
                "state": overall,
                "state_label": STATE_LABELS[overall],
                "can_suspend": bool(states - {"suspended"}),
                "can_restore": "suspended" in states,
            }
        )
    return rows


def challenge_for_opportunity(opportunity):
    return Challenge.objects.select_related("organisation").filter(opportunity=opportunity).first()


def challenge_deliverables(challenge):
    return Deliverable.objects.filter(project__challenge=challenge)


def challenge_filter(user_id=None):
    return Q()
