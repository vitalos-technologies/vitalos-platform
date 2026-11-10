"""Relay inbox: conversation list, thread, context panel and the actions on a conversation.

HTMX targets: ``relay-list`` (tabs, search and realtime refresh), ``relay-thread`` (opening a conversation
or acting on it) and ``relay-messages`` (new messages appended by relay.js). Every page also works as a
plain full-page request.
"""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .. import presenters, selectors, services
from ..client import RelayError, get_client
from ..forms import NoteForm, ReplyForm
from ..models import RelayNotification
from .common import error_response, htmx_target, is_htmx, relay_view, render_page, toast

CHANGED = "relay-inbox-changed"
MAX_QUERY = 100


def _list_state(request) -> dict:
    tab = request.GET.get("tab", "needs")
    if tab not in presenters.TAB_KEYS:
        tab = "needs"
    return {
        "tab": tab,
        "query": request.GET.get("q", "").strip()[:MAX_QUERY],
        "tabs": [(key, label, None) for key, label in presenters.TABS],
    }


def _list_context(request, selected_id: str = "") -> dict:
    state = _list_state(request)
    data = get_client(request.user).inbox(tab=state["tab"], q=state["query"]) or {}
    services.remember_realtime(data.get("realtime"))
    counts = data.get("counts") or {}
    now = timezone.now()
    querystring = request.GET.copy()
    querystring.pop("ref", None)
    querystring.pop("n", None)
    return {
        **state,
        "rows": [presenters.row(item, now) for item in data.get("items") or []],
        "tabs": [(key, label, counts.get(key)) for key, label in presenters.TABS],
        "counts": counts,
        "selected_id": selected_id,
        "querystring": querystring.urlencode(),
    }


def _thread_context(request, conversation_id: str, data: dict | None = None) -> dict:
    data = data or get_client(request.user).conversation(conversation_id) or {}
    conversation = data.get("conversation") or {}
    thread = presenters.thread(conversation, data.get("messages") or [], request.user)
    alerts = selectors.alert_summary(conversation_id)
    relay_settings = services.relay_settings(request.user)
    first = (request.user.full_name or request.user.email).split()[0]
    return {
        "thread": thread,
        "visitor_typing": bool(data.get("visitorTyping")),
        "context": presenters.context(conversation, alerts, relay_settings),
        "reply_form": ReplyForm(
            initial={"client_message_id": services.new_client_message_id(), "email_if_away": True}
        ),
        "note_form": NoteForm(),
        "assignees": selectors.relay_users(),
        "admin_first_name": first,
        "mode": "reply",
    }


def _mark_read(request, conversation_id: str) -> None:
    """Opening a conversation reads its Relay alerts for this admin."""
    RelayNotification.objects.filter(
        recipient=request.user, conversation_id=conversation_id, read_at__isnull=True
    ).update(read_at=timezone.now())


def _thread_response(request, conversation_id: str, message: str = "", data: dict | None = None, **extra):
    context = {**_thread_context(request, conversation_id, data), **extra}
    response = render(request, "relay/_thread.html", context)
    return toast(response, message, **{CHANGED: True, "relay-badge-refresh": True})


# --- Pages ---------------------------------------------------------------------------------------


@relay_view()
@require_GET
def index(request):
    return HttpResponseRedirect(reverse("relay:inbox"))


@relay_view()
@require_GET
def inbox(request):
    try:
        context = _list_context(request)
    except RelayError as error:
        if htmx_target(request) == "relay-list":
            return error_response(request, error)
        return render_page(
            request, "relay/inbox.html", {"relay_error": error.user_message, **_list_state(request)}, "inbox"
        )
    if htmx_target(request) == "relay-list":
        return render(request, "relay/_list.html", context)
    return render_page(request, "relay/inbox.html", context, "inbox")


@relay_view()
@require_GET
def thread(request, conversation_id):
    conversation_id = str(conversation_id)
    try:
        if htmx_target(request) == "relay-thread":
            response = _thread_response(request, conversation_id)
            _mark_read(request, conversation_id)
            return response
        context = {**_list_context(request, conversation_id), **_thread_context(request, conversation_id)}
    except RelayError as error:
        if is_htmx(request) or error.code != "not_found":
            return error_response(request, error)
        return render_page(
            request,
            "relay/inbox.html",
            {"relay_error": "That conversation no longer exists.", **_list_state(request)},
            "inbox",
            status=404,
        )
    _mark_read(request, conversation_id)
    return render_page(request, "relay/inbox.html", context, "inbox")


@relay_view()
@require_GET
def messages_after(request, conversation_id):
    """New messages since ``after`` (appended by relay.js), with the conversation's current status."""
    after = request.GET.get("after", "")[:40]
    try:
        data = get_client(request.user).messages(str(conversation_id), after=after) or {}
    except RelayError as error:
        return error_response(request, error)
    entries = [presenters.message(item) for item in data.get("messages") or []]
    context = {
        "messages": entries,
        "status": data.get("status") or "",
        "assigned_id": (data.get("assigned") or {}).get("id", ""),
        "visitor_typing": bool(data.get("visitorTyping")),
    }
    return render(request, "relay/_messages.html", context)


@relay_view()
@require_GET
def context_panel(request, conversation_id):
    try:
        context = _thread_context(request, str(conversation_id))
    except RelayError as error:
        return error_response(request, error)
    return render(request, "relay/_context.html", context)


# --- Actions -------------------------------------------------------------------------------------


def _act(request, conversation_id, apply, message: str):
    conversation_id = str(conversation_id)
    try:
        apply(conversation_id)
        if not is_htmx(request):
            return HttpResponseRedirect(reverse("relay:thread", args=[conversation_id]))
        return _thread_response(request, conversation_id, message)
    except RelayError as error:
        return error_response(request, error)


@relay_view()
@require_POST
def join(request, conversation_id):
    return _act(
        request,
        conversation_id,
        lambda cid: services.join(request.user, cid, request=request),
        "You joined. The AI is paused for this conversation.",
    )


@relay_view()
@require_POST
def assign(request, conversation_id):
    value = request.POST.get("assignee", "")
    assignee = selectors.relay_users().filter(pk=value).first() if value.isdigit() else None
    if assignee is None:
        response = HttpResponse(status=200)
        response["HX-Reswap"] = "none"
        return toast(response, "That person cannot be assigned site assistant conversations.")
    label = assignee.full_name or assignee.email
    return _act(
        request,
        conversation_id,
        lambda cid: services.assign(request.user, cid, assignee, request=request),
        f"Assigned to {label}.",
    )


@relay_view()
@require_POST
def hand_back(request, conversation_id):
    return _act(
        request,
        conversation_id,
        lambda cid: services.hand_back(request.user, cid, request=request),
        "Handed back to the AI.",
    )


@relay_view()
@require_POST
def close(request, conversation_id):
    return _act(
        request,
        conversation_id,
        lambda cid: services.close(request.user, cid, request=request),
        "Conversation closed.",
    )


@relay_view()
@require_POST
def reply(request, conversation_id):
    conversation_id = str(conversation_id)
    form = ReplyForm(request.POST)
    if not form.is_valid():
        response = HttpResponse(status=200)
        response["HX-Reswap"] = "none"
        return toast(response, "Write a reply of up to 4,000 characters.")
    try:
        data = services.reply(
            request.user,
            conversation_id,
            form.cleaned_data["text"],
            str(form.cleaned_data["client_message_id"]),
            form.cleaned_data["email_if_away"],
            request=request,
        )
    except RelayError as error:
        return error_response(request, error)
    if not is_htmx(request):
        return HttpResponseRedirect(reverse("relay:thread", args=[conversation_id]))
    message = "Reply sent and emailed." if (data or {}).get("emailed") else "Reply sent."
    return _thread_response(request, conversation_id, message)


@relay_view()
@require_POST
def note(request, conversation_id):
    conversation_id = str(conversation_id)
    form = NoteForm(request.POST)
    if not form.is_valid():
        response = HttpResponse(status=200)
        response["HX-Reswap"] = "none"
        return toast(response, "Write a note of up to 4,000 characters.")
    try:
        services.note(request.user, conversation_id, form.cleaned_data["text"], request=request)
    except RelayError as error:
        return error_response(request, error)
    if not is_htmx(request):
        return HttpResponseRedirect(reverse("relay:thread", args=[conversation_id]))
    return _thread_response(request, conversation_id, "Note added. Visitors never see notes.", mode="note")


@relay_view()
@require_POST
def typing(request, conversation_id):
    try:
        services.typing(request.user, str(conversation_id))
    except RelayError:
        pass  # A lost typing ping is harmless.
    return HttpResponse(status=204)


@relay_view()
@require_POST
def delete(request, conversation_id):
    if request.POST.get("confirm") != "delete":
        response = HttpResponse(status=200)
        response["HX-Reswap"] = "none"
        return toast(response, "Confirm the deletion first.")
    try:
        services.delete(request.user, str(conversation_id), request=request)
    except RelayError as error:
        return error_response(request, error)
    target = reverse("relay:inbox")
    messages.success(request, "Conversation deleted.")
    if is_htmx(request):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = target
        return response
    return HttpResponseRedirect(target)


@relay_view()
@require_POST
def save_to_knowledge(request, conversation_id):
    message_id = request.POST.get("message_id", "")
    try:
        document_id = services.save_to_knowledge(
            request.user, str(conversation_id), message_id, request=request
        )
    except (RelayError, ValueError) as error:
        if isinstance(error, ValueError):
            error = RelayError("invalid", 400)
        return error_response(request, error)
    url = reverse("relay:knowledge_edit", args=[document_id]) if document_id else reverse("relay:knowledge")
    if is_htmx(request):
        response = HttpResponse(status=204)
        return toast(
            response, "Saved as a draft team answer. Review it in Knowledge.", **{"relay-saved": {"url": url}}
        )
    return HttpResponseRedirect(url)


@relay_view()
@require_GET
def transcript(request, conversation_id):
    try:
        text = services.transcript(request.user, str(conversation_id), request=request)
    except RelayError as error:
        return JsonResponse({"error": error.user_message}, status=502)
    response = JsonResponse({"text": text})
    response["Cache-Control"] = "no-store"
    return response
