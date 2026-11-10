"""Relay insights (stat tiles and tables) and settings (SuperAdmin; every change audited)."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from .. import preferences, selectors, services
from ..client import RelayError, get_client
from ..forms import SettingsForm
from .common import relay_view, render_page

PERIODS = (7, 30, 90)


def _percent(value) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "–"


def _duration(seconds) -> str:
    if not isinstance(seconds, int | float):
        return "–"
    minutes, rest = divmod(int(seconds), 60)
    if minutes >= 60:
        return f"{minutes // 60} h {minutes % 60} min"
    return f"{minutes} min {rest} s" if minutes else f"{rest} s"


@relay_view()
@require_GET
def insights(request):
    days = int(request.GET.get("days", "30")) if request.GET.get("days", "30") in ("7", "30", "90") else 30
    context = {"days": days, "periods": PERIODS}
    try:
        data = get_client(request.user).insights(days) or {}
    except RelayError as error:
        context["relay_error"] = error.user_message
        return render_page(request, "relay/insights.html", context, "insights")
    helpful, not_helpful = data.get("helpful") or 0, data.get("notHelpful") or 0
    context.update(
        {
            "tiles": [
                ("Conversations", f"{data.get('conversations', 0):,}"),
                ("Answered by the AI", f"{data.get('aiResolved', 0):,}"),
                ("Hand-off rate", _percent(data.get("handoffRate"))),
                ("Helpful / not helpful", f"{helpful} / {not_helpful}"),
                ("Median time to first person reply", _duration(data.get("medianFirstReplySeconds"))),
                ("Waiting now", f"{data.get('waitingNow', 0):,}"),
            ],
            "top_questions": data.get("topQuestions") or [],
            "top_gaps": data.get("topGaps") or [],
            "usage": [
                ("Tokens in", f"{data.get('tokensIn', 0):,}"),
                ("Tokens out", f"{data.get('tokensOut', 0):,}"),
                ("Cached input tokens", f"{data.get('cacheHitTokens', 0):,}"),
                (
                    "Estimated cost (USD)",
                    f"${data['estCostUsd']:.2f}" if isinstance(data.get("estCostUsd"), int | float) else "–",
                ),
            ],
        }
    )
    return render_page(request, "relay/insights.html", context, "insights")


def _recipients() -> list[dict]:
    users = list(selectors.relay_users())
    prefs = preferences.for_users(users)
    rows = []
    for user in users:
        grid = prefs[user.pk].grid
        rows.append(
            {
                "user": user,
                "in_app": [
                    row.key for row in preferences.GRID if row.in_app_available and grid[row.key]["in_app"]
                ],
                "email": [row.key for row in preferences.GRID if grid[row.key]["email"]],
                "superadmin": selectors.can_manage(user),
            }
        )
    return rows


@relay_view(manage=True)
@require_http_methods(["GET", "POST"])
def relay_settings(request):
    context = {
        "recipients": _recipients(),
        "in_app_total": sum(1 for row in preferences.GRID if row.in_app_available),
        "email_total": len(preferences.GRID),
        "production": settings.APP_ENVIRONMENT == "production",
        "email_log": [],
    }
    client = get_client(request.user)
    try:
        current = (client.get_settings() or {}).get("settings") or {}
    except RelayError as error:
        context["relay_error"] = error.user_message
        return render_page(request, "relay/settings.html", context, "settings")
    form = SettingsForm(request.POST or None, initial=SettingsForm.initial_from(current))
    if request.method == "POST" and form.is_valid():
        try:
            services.save_settings(request.user, current, form.api_changes(), request=request)
        except RelayError as error:
            form.add_error(None, error.user_message)
        else:
            messages.success(request, "Site assistant settings saved.")
            return HttpResponseRedirect(reverse("relay:settings"))
    try:
        context["email_log"] = (client.email_log() or {}).get("emails") or []
    except RelayError:
        context["email_log_error"] = True
    context["form"] = form
    return render_page(request, "relay/settings.html", context, "settings")
