"""The signed-in admin's Relay: bell menu, toast pulse, sidebar badge, availability and preferences.

The pulse and badge read only this database (RelayNotification, RelayInboxState); the badge refreshes
from the website at most once a minute when no webhook has updated it.
"""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.roles import role_required

from .. import preferences, presenters, selectors, services
from ..client import RelayError
from ..models import EMAIL, IN_APP, RelayNotification
from .common import SESSION_AVAILABLE, is_htmx, relay_view, render_page, toast

TOAST_TYPES = ("handoff_requested", "visitor_replied", "reminder", "no_answer", "token_cap", "faq_attention")


def _age(moment) -> str:
    return presenters.long_age(moment)


@relay_view()
@require_GET
def notifications(request):
    rows = [{"n": n, "age": _age(n.created_at)} for n in selectors.recent_notifications(request.user)]
    return render(request, "relay/_bell_menu.html", {"rows": rows})


@relay_view()
@require_POST
def open_notification(request, pk):
    notification = RelayNotification.objects.filter(recipient=request.user, pk=pk).first()
    if notification is not None and notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])
    target = notification.url if notification else ""
    if not target or not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = reverse("relay:inbox")
    return HttpResponseRedirect(target)


@relay_view()
@require_POST
def read_all(request):
    count = RelayNotification.objects.filter(recipient=request.user, read_at__isnull=True).update(
        read_at=timezone.now()
    )
    if is_htmx(request):
        rows = [{"n": n, "age": _age(n.created_at)} for n in selectors.recent_notifications(request.user)]
        response = render(request, "relay/_bell_menu.html", {"rows": rows})
        return toast(
            response,
            f"{count} notification{'s' if count != 1 else ''} marked as read.",
            **{"relay-badge-refresh": True},
        )
    return HttpResponseRedirect(reverse("relay:inbox"))


@relay_view()
@require_GET
def bell(request):
    return render(request, "relay/_bell_count.html", {"relay_unread": selectors.unread_count(request.user)})


@role_required()
@require_GET
def badge(request):
    """Sidebar badge (polled every 30 seconds). Empty for anyone who cannot use Relay."""
    if not selectors.nav_visible(request.user):
        return HttpResponse("")
    return render(request, "relay/_badge.html", {"count": services.badge_count(request.user)})


@role_required()
@require_GET
def pulse(request):
    """New unread Relay alerts since ``since`` for the toast poller on every page (local rows only)."""
    if not selectors.nav_visible(request.user):
        return JsonResponse({"enabled": False})
    since = request.GET.get("since", "")
    since = int(since) if since.isdigit() else selectors.latest_notification_id(request.user)
    items = selectors.pulse_items(request.user, since) if request.GET.get("since", "").isdigit() else []
    pref = preferences.get(request.user)
    payload = {
        "enabled": True,
        "cursor": max([since, *[n.pk for n in items]]),
        "unread": selectors.unread_count(request.user),
        "sound": pref.sound,
        "browser": pref.browser,
        "items": [
            {
                "id": n.pk,
                "type": n.type,
                "title": n.title,
                "body": n.body,
                "quote": (n.meta or {}).get("quote", ""),
                "meta": " · ".join(
                    part
                    for part in (
                        (n.meta or {}).get("tag", ""),
                        ((n.meta or {}).get("page", "") or "").upper(),
                        "NOW",
                    )
                    if part
                ),
                "url": n.url
                if n.url.startswith("/") and not n.url.startswith("//")
                else reverse("relay:inbox"),
            }
            for n in items
            if n.type in TOAST_TYPES
        ],
    }
    response = JsonResponse(payload)
    response["Cache-Control"] = "no-store"
    return response


@relay_view()
@require_POST
def availability(request):
    """The Available switch (``available`` = 1 or 0) and the 60-second heartbeat (``heartbeat=1``)."""
    heartbeat = request.POST.get("heartbeat") == "1"
    current = bool(request.session.get(SESSION_AVAILABLE, False))
    available = current if heartbeat else request.POST.get("available") == "1"
    try:
        services.set_availability(
            request.user, available, request=request, heartbeat=heartbeat or available == current
        )
    except RelayError as error:
        if heartbeat:
            return HttpResponse(status=204)
        response = render(request, "relay/_availability.html", {"relay_available": current})
        return toast(response, error.user_message)
    request.session[SESSION_AVAILABLE] = available
    if heartbeat:
        return HttpResponse(status=204)
    response = render(request, "relay/_availability.html", {"relay_available": available})
    return toast(
        response,
        "You are available for the site assistant."
        if available
        else "You are not available for the site assistant.",
    )


@relay_view()
@require_http_methods(["GET", "POST"])
def prefs(request):
    current = preferences.get(request.user)
    relay_settings = services.relay_settings(request.user) or {}
    minutes = relay_settings.get("reminderMinutes") or 10
    if request.method == "POST":
        toggle = request.POST.get("toggle")
        grid, sound, browser = current.grid, current.sound, current.browser
        if toggle == "sound":
            sound = not current.sound
        elif toggle == "browser":
            browser = request.POST.get("browser_value") == "1"
        else:
            grid = {
                row.key: {
                    IN_APP: row.in_app_available and request.POST.get(f"{row.key}-in_app") == "on",
                    EMAIL: request.POST.get(f"{row.key}-email") == "on",
                }
                for row in preferences.GRID
            }
        preferences.save(request.user, grid, sound=sound, browser=browser, request=request)
        messages.success(request, "Notification preferences saved.")
        return HttpResponseRedirect(reverse("relay:prefs"))
    rows = [
        {
            "row": row,
            "label": row.label.format(minutes=minutes),
            "in_app": current.grid[row.key][IN_APP],
            "email": current.grid[row.key][EMAIL],
        }
        for row in preferences.GRID
    ]
    return render_page(request, "relay/prefs.html", {"rows": rows, "pref": current}, "prefs")
