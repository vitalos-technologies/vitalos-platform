"""Push notification routes (ADR-056, Phase 2). Customer surface only: they live in ``push_patterns``, which staff
preview and the admin host never mount. Business rules are in ``apps/portal/push.py``.

* ``push/subscribe/``, ``push/unsubscribe/`` and ``push/test/``: a signed-in member, CSRF, POST only, per-member
  hourly limits. A member only ever reaches their own devices; any other id or endpoint is a 404.
* ``push/renew/``: called by the service worker when the browser rotates a subscription. A worker has no session
  or CSRF token, so the request proves itself with the old subscription's endpoint and authentication secret
  (known only to that browser and this server) and the answer is the same whether or not it matched.
"""

from __future__ import annotations

import json

from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .. import push
from ..access import portal_path, portal_view

MAX_BODY_BYTES = 8192
UNAVAILABLE = "Notifications on this device aren't available yet."


def _wants_json(request) -> bool:
    return (request.content_type or "").startswith("application/json")


def _json_body(request) -> dict | None:
    if len(request.body) > MAX_BODY_BYTES:
        return None
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _answer(request, *, ok: bool, message: str, status: int = 200, **extra):
    """JSON for the device page script; a message and a redirect back to Notifications on this device for a plain
    form."""
    if _wants_json(request):
        return JsonResponse({"ok": ok, "message": message, **extra}, status=status)
    (messages.success if ok else messages.error)(request, message)
    return HttpResponseRedirect(portal_path(request, "account_device"))


def _no_store(response):
    response["Cache-Control"] = "private, no-store"
    return response


@portal_view(write=True)
@require_POST
def subscribe(request, ctx):
    if not push.enabled():
        return _no_store(_answer(request, ok=False, message=UNAVAILABLE, status=503))
    data = _json_body(request)
    if data is None:
        return _no_store(
            _answer(request, ok=False, message="The browser sent an incomplete subscription.", status=400)
        )
    if push.over_limit(ctx.user, "portal.push_subscribed"):
        return _no_store(
            _answer(
                request, ok=False, message="Too many changes in the last hour. Try again later.", status=429
            )
        )
    try:
        parsed = push.parse_subscription(data)
        sub, created = push.subscribe(
            ctx.member, parsed, user_agent=request.headers.get("User-Agent", ""), request=request
        )
    except push.PushError as exc:
        return _no_store(_answer(request, ok=False, message=str(exc), status=400))
    if request.GET.get("sync") != "1":  # a quiet re-registration after the browser rotated it shows nothing
        messages.success(request, "Notifications are on for this device.")
    return _no_store(
        JsonResponse(
            {"ok": True, "message": "Notifications are on for this device.", "label": sub.label},
            status=201 if created else 200,
        )
    )


@portal_view(write=True)
@require_POST
def unsubscribe(request, ctx):
    if _wants_json(request):
        data = _json_body(request) or {}
        sub = push.find_device(ctx.user, endpoint=data.get("endpoint"))
    else:
        sub = push.find_device(ctx.user, pk=request.POST.get("subscription"))
    if sub is None:
        raise Http404
    if push.over_limit(ctx.user, "portal.push_removed"):
        return _no_store(
            _answer(
                request, ok=False, message="Too many changes in the last hour. Try again later.", status=429
            )
        )
    push.remove(sub, request=request)
    message = "Notifications are off for that device."
    if _wants_json(request):
        messages.success(request, "Notifications are off for this device.")
        return _no_store(JsonResponse({"ok": True, "message": "Notifications are off for this device."}))
    return _no_store(_answer(request, ok=True, message=message))


@portal_view(write=True)
@require_POST
def send_test(request, ctx):
    if _wants_json(request):
        data = _json_body(request) or {}
        sub = push.find_device(ctx.user, endpoint=data.get("endpoint"))
    else:
        sub = push.find_device(ctx.user, pk=request.POST.get("subscription"))
    if sub is None or sub.disabled_at is not None:
        raise Http404
    if not push.enabled():
        return _no_store(_answer(request, ok=False, message=UNAVAILABLE, status=503))
    if push.over_limit(ctx.user, "portal.push_test"):
        limit = push.RATE_LIMITS_PER_HOUR["portal.push_test"]
        return _no_store(
            _answer(
                request,
                ok=False,
                message=f"You can send {limit} test notifications an hour. Try again later.",
                status=429,
            )
        )
    ok, message = push.send_test(sub, request=request)
    return _no_store(_answer(request, ok=ok, message=message, status=200 if ok else 502))


@csrf_exempt  # the service worker has no CSRF token: the old subscription's secret authenticates the request
@require_POST
def renew(request):
    data = _json_body(request) or {}
    try:
        parsed = push.parse_subscription(data.get("subscription"))
    except push.PushError:
        parsed = None
    if parsed is not None:
        push.renew(data.get("old_endpoint"), data.get("old_auth"), parsed, request=request)
    # The same answer whatever happened, so the route reveals nothing about which endpoints exist.
    return _no_store(HttpResponse(status=204))
