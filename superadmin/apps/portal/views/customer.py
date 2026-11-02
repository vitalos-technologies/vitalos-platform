"""Customer workspace views. Each view resolves the member with ``portal_view`` and reads ONLY through
``selectors`` (organisation and publication scoping), so a record outside the member's organisation or not yet
published is a 404, whatever the URL. Writes go through ``services`` and report refusals as messages."""

from __future__ import annotations

import csv

from django.contrib import messages
from django.db.models import Prefetch
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_htmx.http import HttpResponseClientRedirect

from apps.audit.services import record

from .. import ai, selectors, services
from .. import files as portal_files
from .. import notifications as portal_notifications
from .. import push as portal_push
from ..access import portal_path, portal_view
from ..forms import (
    AcceptContractForm,
    AnswerForm,
    ChangeRequestForm,
    CommentForm,
    FileUploadForm,
    MessageForm,
    PreferencesForm,
    RequiredCommentForm,
    UploadForm,
)
from ..models import (
    JOURNEY_ORDER,
    FileVersion,
    InformationRequest,
    Journey,
)

NAV = {
    "home": "home",
    "challenges": "challenges",
    "challenge": "challenges",
    "project": "challenges",
    "milestone": "challenges",
    "deliverable": "challenges",
    "questions": "questions",
    "question": "questions",
    "files": "files",
    "file": "files",
    "notifications": "notifications",
    "notification_preferences": "account",
    "account": "account",
    "account_security": "account",
    "account_device": "account",
    "account_install": "account",
    "otp_setup": "account",
}


def _ai_items(*specs):
    """Assistant buttons: (activity, hidden field name, hidden field value)."""
    return [(activity, ai.ACTIVITIES[activity], field, value) for activity, field, value in specs]


def show(request, ctx, template, context=None, status=200):
    unread = 0 if ctx.preview else selectors.notifications(ctx.user).filter(read_at__isnull=True).count()
    base = {
        "ctx": ctx,
        "member": ctx.member,
        "organisation": ctx.organisation,
        "preview": ctx.preview,
        "unread": unread,
        "replay_available": ai.replay_available(),
        "nav": NAV.get(getattr(request.resolver_match, "url_name", ""), ""),
    }
    return render(request, template, {**base, **(context or {})}, status=status)


def go(request, name, **kwargs):
    return HttpResponseRedirect(portal_path(request, name, kwargs))


def _refuse(request, exc: services.PortalError):
    messages.error(request, str(exc))


def _journey(challenge):
    current = JOURNEY_ORDER.index(challenge.journey_stage)
    return [
        {"label": label, "state": "done" if i < current else "current" if i == current else "todo"}
        for i, (_value, label) in enumerate(Journey.choices)
    ]


def _display_messages(member, challenge, **scope):
    out = []
    for thread in selectors.threads(member, challenge).filter(**scope):
        out.extend(selectors.messages(member, thread).prefetch_related("files__versions"))
    out.sort(key=lambda m: (m.created_at, m.pk))
    return out


# --- Dashboard -------------------------------------------------------------------------------------------------------------


@portal_view()
@require_GET
def dashboard(request, ctx):
    m = ctx.member
    challenges = list(selectors.challenges(m))
    projects = list(selectors.projects(m))
    updates = list(selectors.updates(m)[:1])
    svc = []
    for s in selectors.services(m):
        report = selectors.latest_report(s)
        svc.append({"service": s, "report": report, "fresh": selectors.report_freshness(report)})
    return show(
        request,
        ctx,
        "portal/dashboard.html",
        {
            "challenges": challenges,
            "projects": projects,
            "latest_update": updates[0] if updates else None,
            "next_milestone": selectors.next_milestone(m),
            "actions": selectors.actions_required(m),
            "blockers": selectors.blockers(m),
            "recent_versions": selectors.recent_deliverable_versions(m),
            "services": svc,
            "events": selectors.events(m)[:8],
            "since": m.previous_visit_at,
            "assistant_items": _ai_items(
                *[("summarise_project", "project", p.pk) for p in projects[:1]],
                ("what_changed", "", ""),
                ("what_needed", "", ""),
                ("unanswered", "", ""),
            ),
            "today": timezone.localdate(),
        },
    )


@portal_view()
@require_GET
def activity(request, ctx):
    return show(request, ctx, "portal/activity.html", {"events": selectors.events(ctx.member)[:100]})


# --- Challenges ------------------------------------------------------------------------------------------------------------


@portal_view()
@require_GET
def challenges(request, ctx):
    return show(request, ctx, "portal/challenges.html", {"challenges": selectors.challenges(ctx.member)})


@portal_view()
@require_GET
def challenge(request, ctx, pk):
    m = ctx.member
    ch = selectors.get_challenge(m, pk)
    return show(
        request,
        ctx,
        "portal/challenge.html",
        {
            "challenge": ch,
            "journey": _journey(ch),
            "agreed": selectors.agreed_brief(m, ch),
            "pending": selectors.pending_brief(m, ch),
            "briefs": selectors.briefs(m, ch).prefetch_related("reviews"),
            "messages_list": _display_messages(m, ch, milestone=None, deliverable=None),
            "message_form": MessageForm(),
            "files": selectors.files(m, ch).prefetch_related("versions"),
            "questions": selectors.information_requests(m, ch),
            "projects": selectors.projects(m).filter(challenge=ch),
            "updates": selectors.updates(m, challenge=ch)[:5],
            "review_form": CommentForm(),
            "changes_form": RequiredCommentForm(),
            "assistant_items": _ai_items(
                ("clarify_challenge", "challenge", ch.pk), ("unanswered", "challenge", ch.pk)
            ),
            "upload_form": UploadForm(initial={"challenge": ch.pk}),
        },
    )


@portal_view(min_role="can_comment", write=True)
@require_POST
def challenge_discuss(request, ctx, pk):
    ch = selectors.get_challenge(ctx.member, pk)
    form = MessageForm(request.POST, request.FILES)
    milestone = deliverable = None
    if request.POST.get("milestone"):
        milestone = selectors.get_milestone(ctx.member, request.POST["milestone"])
        if milestone.project.challenge_id != ch.pk:
            raise Http404
    if request.POST.get("deliverable"):
        deliverable = selectors.get_deliverable(ctx.member, request.POST["deliverable"])
        if deliverable.project.challenge_id != ch.pk:
            raise Http404
    if form.is_valid():
        try:
            services.post_customer_message(
                ctx.member,
                ch,
                body=form.cleaned_data["body"],
                milestone=milestone,
                deliverable=deliverable,
                upload=form.cleaned_data.get("attachment"),
                request=request,
            )
            messages.success(request, "Your message was sent.")
        except services.PortalError as exc:
            _refuse(request, exc)
    else:
        messages.error(request, "Write a message first (up to 4,000 characters).")
    if deliverable:
        return go(request, "deliverable", pk=deliverable.pk)
    if milestone:
        return go(request, "milestone", pk=milestone.pk)
    return HttpResponseRedirect(portal_path(request, "challenge", {"pk": ch.pk}) + "#discussion")


@portal_view(min_role="can_comment", write=True)
@require_POST
def brief_review(request, ctx, pk, brief_pk):
    ch = selectors.get_challenge(ctx.member, pk)
    brief = selectors.get_brief(ctx.member, brief_pk)
    if brief.challenge_id != ch.pk:
        raise Http404
    accept = request.POST.get("decision") == "accept"
    try:
        services.review_brief(
            ctx.member, brief, accept=accept, comment=request.POST.get("comment", ""), request=request
        )
        messages.success(
            request,
            "Thank you. The brief is now agreed."
            if accept
            else "Your requested changes were sent to Vitalos.",
        )
    except services.PortalError as exc:
        _refuse(request, exc)
    return go(request, "challenge", pk=ch.pk)


# --- Projects --------------------------------------------------------------------------------------------------------------


@portal_view()
@require_GET
def project(request, ctx, pk):
    m = ctx.member
    p = selectors.get_project(m, pk)
    delivs = []
    for d in selectors.deliverables(m, p):
        v = selectors.latest_version(m, d)
        delivs.append({"deliverable": d, "version": v, "state": selectors.version_state(v) if v else ""})
    svc = []
    for s in selectors.services(m).filter(project=p):
        report = selectors.latest_report(s)
        svc.append({"service": s, "report": report, "fresh": selectors.report_freshness(report)})
    needs = [a for a in selectors.actions_required(m) if a["context"] in (p.name, p.challenge.title)]
    items = selectors.items(m, p)
    return show(
        request,
        ctx,
        "portal/project.html",
        {
            "project": p,
            "challenge": p.challenge,
            "milestones": selectors.milestones(m, p),
            "responsibilities": items.filter(kind="responsibility"),
            "dependencies": items.filter(kind="dependency"),
            "blockers": items.filter(kind="blocker", is_done=False),
            "deliverables": delivs,
            "updates": selectors.updates(m, project=p)[:5],
            "changes": selectors.change_requests(m, p),
            "needs": needs,
            "services": svc,
            "assistant_items": _ai_items(
                ("summarise_project", "project", p.pk),
                ("what_needed", "", ""),
                ("unanswered", "challenge", p.challenge_id),
            ),
            "today": timezone.localdate(),
        },
    )


def _safe_cell(value) -> str:
    text = str(value if value is not None else "")
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@portal_view()
@require_GET
def project_export(request, ctx, pk):
    """CSV of the project's milestones and deliverable decisions: customer-visible fields only."""
    m = ctx.member
    p = selectors.get_project(m, pk)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="project-{p.pk}-summary.csv"'
    response["X-Content-Type-Options"] = "nosniff"
    writer = csv.writer(response)
    writer.writerow(["Type", "Name", "Status or decision", "Date", "By"])
    for ms in selectors.milestones(m, p):
        writer.writerow(
            ["Milestone", _safe_cell(ms.title), ms.get_status_display(), ms.target_date or "", ""]
        )
    for d in selectors.deliverables(m, p):
        for v in selectors.versions(m, d).order_by("number"):
            rows = selectors.decisions(v)
            if not rows:
                writer.writerow(
                    [
                        "Deliverable version",
                        _safe_cell(f"{d.title} v{v.number}"),
                        "Awaiting decision",
                        v.shared_at.date(),
                        "",
                    ]
                )
            for a in rows:
                writer.writerow(
                    [
                        "Deliverable version",
                        _safe_cell(f"{d.title} v{v.number}"),
                        a.get_decision_display(),
                        a.created_at.date(),
                        _safe_cell(a.user_name or a.user_email),
                    ]
                )
    return response


@portal_view()
@require_GET
def milestone(request, ctx, pk):
    m = ctx.member
    ms = selectors.get_milestone(m, pk)
    ch = ms.project.challenge
    return show(
        request,
        ctx,
        "portal/milestone.html",
        {
            "milestone": ms,
            "project": ms.project,
            "challenge": ch,
            "messages_list": _display_messages(m, ch, milestone=ms),
            "message_form": MessageForm(),
            "deliverables": selectors.deliverables(m, ms.project).filter(milestone=ms),
        },
    )


# --- Deliverables ----------------------------------------------------------------------------------------------------------


@portal_view()
@require_GET
def deliverable(request, ctx, pk):
    m = ctx.member
    d = selectors.get_deliverable(m, pk)
    all_versions = list(selectors.versions(m, d))
    chosen = None
    wanted = request.GET.get("v", "")
    if wanted.isascii() and wanted.isdigit():
        chosen = next((v for v in all_versions if v.number == int(wanted)), None)
    version = chosen or (all_versions[0] if all_versions else None)
    state = selectors.version_state(version) if version else ""
    decisions = selectors.decisions(version) if version else []
    ch = d.project.challenge
    rows = [
        {"version": v, "state": selectors.version_state(v), "decisions": selectors.decisions(v)}
        for v in all_versions
    ]
    is_latest = bool(version and all_versions and version.pk == all_versions[0].pk)
    can_decide = bool(
        version and is_latest and version.requires_approval and state in ("pending", "changes_requested")
    )
    statement = ""
    if version and version.is_contractual:
        statement = services.ACCEPTANCE_STATEMENT.format(
            organisation=ctx.organisation.name, title=d.title, number=version.number
        )
    return show(
        request,
        ctx,
        "portal/deliverable.html",
        {
            "deliverable": d,
            "project": d.project,
            "challenge": ch,
            "version": version,
            "state": state,
            "decisions": decisions,
            "version_rows": rows,
            "is_latest": is_latest,
            "can_decide": can_decide,
            "approve_form": CommentForm(),
            "changes_form": RequiredCommentForm(),
            "accept_form": AcceptContractForm(),
            "contract_statement": statement,
            "contract_done": bool(version and selectors.contract_accepted(version)),
            "messages_list": _display_messages(m, ch, deliverable=d),
            "message_form": MessageForm(),
            "file": version.file_version
            if version
            and version.file_version_id
            and version.file_version.customer_visible
            and version.file_version.file.visibility == "customer"
            else None,
            "assistant_items": _ai_items(("explain_deliverable", "deliverable", d.pk)),
        },
    )


def _decision_view(request, ctx, pk, action):
    version = selectors.get_version(ctx.member, pk)
    d = version.deliverable
    try:
        if action == "approve":
            services.approve_version(
                ctx.member, version, comment=request.POST.get("comment", ""), request=request
            )
            messages.success(
                request, f"You approved {d.title}, version {version.number}. The decision is recorded below."
            )
        elif action == "changes":
            services.request_version_changes(
                ctx.member, version, comment=request.POST.get("comment", ""), request=request
            )
            messages.success(
                request,
                "Your requested changes were recorded and sent to Vitalos. A new version will follow.",
            )
        else:
            services.accept_contract(
                ctx.member, version, confirmed=request.POST.get("confirm") == "on", request=request
            )
            messages.success(request, f"Contractual acceptance of version {version.number} is recorded.")
    except services.PortalError as exc:
        _refuse(request, exc)
    return HttpResponseRedirect(
        portal_path(request, "deliverable", {"pk": d.pk}) + f"?v={version.number}#decision"
    )


@portal_view(min_role="can_approve", write=True)
@require_POST
def version_approve(request, ctx, pk):
    return _decision_view(request, ctx, pk, "approve")


@portal_view(min_role="can_approve", write=True)
@require_POST
def version_changes(request, ctx, pk):
    return _decision_view(request, ctx, pk, "changes")


@portal_view(min_role="can_accept_contract", write=True)
@require_POST
def version_accept(request, ctx, pk):
    return _decision_view(request, ctx, pk, "accept")


# --- Questions, updates, changes -----------------------------------------------------------------------------------------------


@portal_view()
@require_GET
def questions(request, ctx):
    qs = selectors.information_requests(ctx.member)
    return show(
        request,
        ctx,
        "portal/questions.html",
        {
            "open_questions": qs.filter(status=InformationRequest.Status.OPEN),
            "done_questions": qs.exclude(status=InformationRequest.Status.OPEN),
            "today": timezone.localdate(),
            "assistant_items": _ai_items(("unanswered", "", ""), ("what_needed", "", "")),
        },
    )


@portal_view()
@require_http_methods(["GET", "POST"])
def question(request, ctx, pk):
    q = selectors.get_information_request(ctx.member, pk)
    form = AnswerForm(request.POST or None)
    if request.method == "POST":
        if ctx.preview:
            raise Http404
        if not ctx.member.can_comment:
            messages.error(request, "Your role is read-only. Ask a contributor to answer.")
        elif form.is_valid():
            try:
                services.answer_question(ctx.member, q, body=form.cleaned_data["body"], request=request)
                messages.success(request, "Thank you. Your answer was sent to Vitalos.")
                return go(request, "question", pk=q.pk)
            except services.PortalError as exc:
                _refuse(request, exc)
    return show(
        request,
        ctx,
        "portal/question.html",
        {
            "q": q,
            "responses": q.responses.select_related("user"),
            "form": form,
            "today": timezone.localdate(),
        },
    )


@portal_view()
@require_GET
def update(request, ctx, pk):
    u = selectors.get_update(ctx.member, pk)
    return show(request, ctx, "portal/update.html", {"update": u, "challenge": u.challenge})


@portal_view()
@require_http_methods(["GET", "POST"])
def change_new(request, ctx, pk):
    p = selectors.get_project(ctx.member, pk)
    form = ChangeRequestForm(request.POST or None, initial=request.GET.dict())
    if request.method == "POST":
        if not ctx.member.can_comment:
            messages.error(request, "Your role is read-only.")
        elif form.is_valid():
            try:
                change = services.request_change(
                    ctx.member,
                    p,
                    title=form.cleaned_data["title"],
                    description=form.cleaned_data["description"],
                    affects=form.cleaned_data["affects"],
                    request=request,
                )
                messages.success(
                    request,
                    "Your change request was sent. Nothing changes until Vitalos has reviewed it and replied.",
                )
                return go(request, "change", pk=change.pk)
            except services.PortalError as exc:
                _refuse(request, exc)
    return show(request, ctx, "portal/change_new.html", {"project": p, "form": form})


@portal_view()
@require_GET
def change(request, ctx, pk):
    c = selectors.get_change_request(ctx.member, pk)
    return show(
        request,
        ctx,
        "portal/change.html",
        {"change": c, "project": c.project, "trail": c.trail.filter(customer_visible=True)},
    )


# --- Files -------------------------------------------------------------------------------------------------------------------


def _upload_context(ctx, challenges, projects, form=None, *, open_dialog=False) -> dict:
    """Everything the "Upload a file" button and dialog need. Business rules come from ``services``; the type and
    size wording from ``files``, so what the page promises is what the checks accept."""
    refusal = services.customer_upload_refusal(
        ctx.member, preview=ctx.preview, has_challenge=bool(challenges)
    )
    if form is None and not refusal:
        initial = {"challenge": challenges[0].pk} if len(challenges) == 1 else {}
        form = FileUploadForm(challenges=challenges, projects=projects, initial=initial)
    groups: dict = {}
    for p in projects:
        groups.setdefault(p.challenge_id, {"challenge": p.challenge, "projects": []})["projects"].append(p)
    return {
        "upload_refusal": refusal,
        "upload_form": None if refusal else form,
        "upload_open": open_dialog and not refusal,
        "upload_challenges": challenges,
        "upload_project_groups": list(groups.values()),
        "upload_selected_challenge": str(form["challenge"].value() or "") if form else "",
        "upload_selected_project": str(form["project"].value() or "") if form else "",
        "upload_accepted": portal_files.accepted_summary(),
        "upload_accept": portal_files.accept_attribute(),
        "upload_legacy_note": portal_files.LEGACY_NOTE,
        "max_mb": portal_files.MAX_BYTES // (1024 * 1024),
        "storage_enabled": portal_files.storage_enabled(),
    }


def _files_page(request, ctx, form=None, *, open_dialog=False):
    m = ctx.member
    challenges = list(selectors.challenges(m))
    projects = list(selectors.projects(m))
    groups = []
    for ch in challenges:
        fs = list(
            selectors.files(m, ch)
            .prefetch_related(
                Prefetch(
                    "versions",
                    queryset=FileVersion.objects.filter(customer_visible=True),
                    to_attr="shown_versions",
                )
            )
            .select_related("project")
        )
        groups.append({"challenge": ch, "files": fs})
    context = {"groups": groups, "has_files": any(g["files"] for g in groups)}
    context.update(_upload_context(ctx, challenges, projects, form, open_dialog=open_dialog))
    return show(request, ctx, "portal/files.html", context)


@portal_view()
@require_GET
def files(request, ctx):
    # ?upload=1 opens the dialog from the server, so the button also works as a plain link without JavaScript.
    return _files_page(request, ctx, open_dialog=request.GET.get("upload") == "1")


@portal_view(min_role="can_comment", write=True)
@require_POST
def file_upload(request, ctx):
    """The "Upload a file" dialog (a new file), or a new version from a file's page (``file_id``)."""
    if request.POST.get("file_id"):
        return _file_version_upload(request, ctx)
    m = ctx.member
    # Ids from another organisation, or not shared or published, are a 404, exactly like a record that does not exist.
    challenge = (
        selectors.get_challenge(m, request.POST["challenge"]) if request.POST.get("challenge") else None
    )
    project = selectors.get_project(m, request.POST["project"]) if request.POST.get("project") else None
    challenges = list(selectors.challenges(m))
    projects = list(selectors.projects(m))
    form = FileUploadForm(request.POST, request.FILES, challenges=challenges, projects=projects)
    if form.is_valid():
        try:
            version = services.upload_customer_file(
                m,
                challenge,
                form.cleaned_data["file"],
                project=project,
                title=form.cleaned_data["title"],
                request=request,
            )
        except services.PortalError as exc:
            form.add_error("file", str(exc))
        else:
            _upload_message(request, version)
            target = portal_path(request, "file", {"pk": version.file_id})
            if request.htmx:
                return HttpResponseClientRedirect(target)
            return HttpResponseRedirect(target)
    if request.htmx:
        # The dialog swaps in the form with its errors; the chosen file has to be picked again.
        context = _upload_context(ctx, challenges, projects, form, open_dialog=True)
        return show(request, ctx, "portal/_upload_form.html", context)
    return _files_page(request, ctx, form, open_dialog=True)


def _upload_message(request, version) -> None:
    if version.upload_status == FileVersion.Status.UNAVAILABLE:
        messages.warning(
            request,
            "Vitalos has recorded your file, but file storage is not set up yet, so its contents were not kept.",
        )
    else:
        messages.success(request, f"File uploaded: {version.file.title}.")


def _file_version_upload(request, ctx):
    """A new version from a file's page. A customer adds versions only to a file a customer uploaded (M3)."""
    existing = selectors.get_file(ctx.member, request.POST["file_id"])
    form = UploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Choose a file to upload.")
        return go(request, "file", pk=existing.pk)
    try:
        version = services.upload_customer_file(
            ctx.member,
            selectors.get_challenge(ctx.member, form.cleaned_data["challenge"]),
            form.cleaned_data["file"],
            file=existing,
            request=request,
        )
    except services.PortalError as exc:
        _refuse(request, exc)
        return go(request, "file", pk=existing.pk)
    _upload_message(request, version)
    return go(request, "file", pk=version.file_id)


@portal_view()
@require_GET
def file(request, ctx, pk):
    f = selectors.get_file(ctx.member, pk)
    return show(
        request,
        ctx,
        "portal/file.html",
        {
            "file": f,
            "versions": selectors.file_versions(ctx.member, f),
            "challenge": f.challenge,
            "upload_form": UploadForm(initial={"challenge": f.challenge_id, "file_id": f.pk}),
        },
    )


@portal_view()
@require_GET
def file_download(request, ctx, pk):
    """Authorised download: visibility is re-checked on every request; always an attachment, never inline."""
    version = selectors.get_file_version(ctx.member, pk)
    if version.upload_status != FileVersion.Status.STORED or not version.storage_key:
        raise Http404
    try:
        handle = portal_files.open_file(version.storage_key)
    except (FileNotFoundError, OSError) as exc:
        raise Http404 from exc
    record(
        "portal.file_downloaded",
        request=request,
        actor=request.user,
        entity=version.file,
        summary=f"{version.original_name} v{version.number}"[:250],
    )
    response = FileResponse(
        handle,
        as_attachment=True,
        filename=version.original_name,
        content_type=version.content_type or "application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Cache-Control"] = "private, no-store"
    return response


# --- Search, notifications, account, assistant ----------------------------------------------------------------------------------


@portal_view()
@require_GET
def search(request, ctx):
    q = request.GET.get("q", "")
    results = selectors.search(ctx.member, q)
    return show(
        request,
        ctx,
        "portal/search.html",
        {"q": q, "results": {k: v for k, v in results.items() if v}, "searched": len(q.strip()) >= 2},
    )


@portal_view()
@require_GET
def notifications_list(request, ctx):
    qs = selectors.notifications(ctx.user)[:100] if not ctx.preview else []
    return show(request, ctx, "portal/notifications.html", {"notifications": qs})


@portal_view(write=True)
@require_POST
def notifications_read_all(request, ctx):
    portal_notifications.mark_all_read(ctx.user)
    return go(request, "notifications")


@portal_view()
@require_GET
def notification_open(request, ctx, pk):
    if ctx.preview:
        raise Http404
    note = portal_notifications.mark_read(ctx.user, pk)
    if note is None:
        raise Http404
    try:
        target = reverse(f"portal:{note.url_name}", kwargs=note.url_kwargs)
    except Exception:  # noqa: BLE001 - a stale target just goes home
        target = reverse("portal:home")
    return HttpResponseRedirect(target)


@portal_view()
@require_http_methods(["GET", "POST"])
def notification_preferences(request, ctx):
    if ctx.preview:
        pref = None
        form = PreferencesForm()
    else:
        pref = portal_notifications.preferences(ctx.user)
        form = PreferencesForm(
            request.POST or None, initial={f: getattr(pref, f) for f in PreferencesForm.base_fields}
        )
        if request.method == "POST" and form.is_valid():
            for name, value in form.cleaned_data.items():
                setattr(pref, name, value)
            pref.save()
            messages.success(request, "Your notification preferences were saved.")
            return go(request, "notification_preferences")
    devices = 0 if ctx.preview else portal_push.devices(ctx.user).count()
    return show(
        request,
        ctx,
        "portal/preferences.html",
        {
            "form": form,
            "pref": pref,
            "push_devices": devices,
            "push_available": portal_push.enabled(),
            "settings_section": "preferences",
        },
    )


# --- Your account: one page per section in the settings shell (settings_base.html) ---------------------------------
# settings_section marks the menu item (aria-current). Notifications on this device and Install the app belong to the
# member's own browser, so staff preview has neither (their menu items are hidden and their URLs go to Profile).


@portal_view()
@require_GET
def account(request, ctx):
    return show(request, ctx, "portal/account.html", {"settings_section": "profile"})


@portal_view()
@require_GET
def account_security(request, ctx):
    from apps.accounts.otp import confirmed_devices

    return show(
        request,
        ctx,
        "portal/account_security.html",
        {
            "mfa": confirmed_devices(ctx.user).exists() if not ctx.preview else False,
            "settings_section": "security",
        },
    )


@portal_view()
@require_GET
def account_device(request, ctx):
    if ctx.preview:
        return go(request, "account")
    return show(
        request,
        ctx,
        "portal/account_device.html",
        {
            # Push notifications (ADR-056, Phase 2): the member's own devices.
            "push": portal_push.page_context(ctx.user),
            "settings_section": "device",
        },
    )


@portal_view()
@require_GET
def account_install(request, ctx):
    if ctx.preview:
        return go(request, "account")
    return show(request, ctx, "portal/account_install.html", {"settings_section": "install"})


@portal_view(write=True)
@require_POST
def assistant(request, ctx, activity):
    if activity not in ai.ACTIVITIES:
        raise Http404
    m = ctx.member
    scope: dict = {}
    text = (request.POST.get("text") or "")[:1500]
    if activity == "summarise_project":
        scope["project"] = selectors.get_project(m, request.POST.get("project") or 0)
    elif activity == "explain_deliverable":
        scope["deliverable"] = selectors.get_deliverable(m, request.POST.get("deliverable") or 0)
    elif activity == "clarify_challenge":
        scope["challenge"] = selectors.get_challenge(m, request.POST.get("challenge") or 0)
    elif activity == "unanswered" and request.POST.get("challenge"):
        scope["challenge"] = selectors.get_challenge(m, request.POST["challenge"])
    result = ai.answer(activity, m, text=text, use_replay=request.POST.get("replay") == "1", **scope)
    record(
        "portal.ai_answered",
        request=request,
        actor=request.user,
        entity=m,
        summary=f"{activity} ({result.mode}), {len(result.sources)} records",
    )
    context = {"answer": result, "activity_label": ai.ACTIVITIES[activity], "activity": activity}
    template = (
        "portal/_assistant_answer.html" if request.headers.get("HX-Request") else "portal/assistant.html"
    )
    return show(request, ctx, template, context)
