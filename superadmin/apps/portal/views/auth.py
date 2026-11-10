"""Customer access: sign-in, second factor, sign-out, forgotten password, invitation. Customer-styled pages."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from django_otp import login as otp_login

from apps.accounts import otp
from apps.accounts.roles import has_any_role
from apps.audit.services import record

from .. import passwords, push, selectors, services
from ..access import portal_view
from ..forms import (
    ConfirmExistingPasswordForm,
    ForgotForm,
    OTPForm,
    PortalLoginForm,
    PortalSetPasswordForm,
)

logger = logging.getLogger(__name__)


def _next(request) -> str:
    candidate = request.POST.get("next") or request.GET.get("next") or ""
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return reverse("portal:home")


def _page(request, template, context=None, status=200):
    response = render(request, template, context or {}, status=status)
    response["Cache-Control"] = "no-store"
    return response


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def login_view(request):
    user = request.user
    if user.is_authenticated and not has_any_role(user) and selectors.get_membership(user):
        if otp.confirmed_devices(user).exists() and not user.is_verified():
            return HttpResponseRedirect(
                f"{reverse('portal:otp_verify')}?{urlencode({'next': _next(request)})}"
            )
        return HttpResponseRedirect(_next(request))
    form = PortalLoginForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        candidate = form.user
        if selectors.get_membership(candidate) is None:
            form.add_error(
                None,
                "Your portal access is not active. If you expected to have access, ask your Vitalos contact.",
            )
        else:
            auth_login(request, candidate)
            record(
                "portal.sign_in",
                request=request,
                actor=candidate,
                entity=candidate,
                summary="Signed in to the portal",
            )
            if otp.confirmed_devices(candidate).exists():
                return HttpResponseRedirect(
                    f"{reverse('portal:otp_verify')}?{urlencode({'next': _next(request)})}"
                )
            return HttpResponseRedirect(_next(request))
    return _page(request, "portal/auth/login.html", {"form": form, "next": request.GET.get("next", "")})


@never_cache
@require_http_methods(["GET", "POST"])
def otp_verify(request):
    user = request.user
    if not user.is_authenticated or has_any_role(user):
        return redirect("portal:login")
    if user.is_verified() or not otp.confirmed_devices(user).exists():
        return HttpResponseRedirect(_next(request))
    form = OTPForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        device = otp.verify(user, form.cleaned_data["token"])
        if device is not None:
            otp_login(request, device)
            return HttpResponseRedirect(_next(request))
        form.add_error("token", "That code is not valid. Check your device's clock and try again.")
    return _page(request, "portal/auth/otp_verify.html", {"form": form, "next": request.GET.get("next", "")})


@require_POST
def logout_view(request):
    user = request.user
    if user.is_authenticated:
        record(
            "portal.sign_out", request=request, actor=user, entity=user, summary="Signed out of the portal"
        )
        # Shared devices: signing out turns notifications off for this browser (portal.js sends its endpoint).
        try:
            push.forget_device(user, request.POST.get("push_endpoint", ""), request=request)
        except Exception:  # noqa: BLE001 - signing out must always work
            logger.exception("portal push: could not forget the device on sign-out")
    auth_logout(request)
    messages.info(request, "You have signed out.")
    return redirect("portal:login")


@never_cache
@require_http_methods(["GET", "POST"])
def forgot_password(request):
    form = ForgotForm(request.POST or None)
    sent = False
    if request.method == "POST" and form.is_valid():
        try:
            passwords.request_reset(form.cleaned_data["email"], request)
        except Exception:  # noqa: BLE001 - the answer must not depend on whether mail could be sent
            logger.exception("portal password reset email failed")
        sent = True
    return _page(request, "portal/auth/forgot.html", {"form": form, "sent": sent})


@never_cache
@require_http_methods(["GET", "POST"])
def reset_password(request, uidb64, token):
    from apps.accounts.tokens import set_password_token

    user = passwords.user_from_uid(uidb64)
    if user is None or not set_password_token.check_token(user, token):
        return _page(request, "portal/auth/link_invalid.html", {"what": "reset"}, status=400)
    form = PortalSetPasswordForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()  # changes the hash, which invalidates the link
        record("portal.password_set", request=request, actor=user, entity=user, summary="Password reset")
        messages.success(request, "Your password is set. Sign in to continue.")
        return redirect("portal:login")
    return _page(
        request, "portal/auth/set_password.html", {"form": form, "email": user.email, "mode": "reset"}
    )


@never_cache
@require_http_methods(["GET", "POST"])
def invitation(request, token):
    inv = services.lookup_invitation(token)
    if inv is None or not inv.is_usable or not inv.membership.is_active or inv.membership.revoked_at:
        state = inv.state if inv else "unknown"
        return _page(
            request, "portal/auth/link_invalid.html", {"what": "invitation", "state": state}, status=400
        )
    member = inv.membership
    user = member.user
    existing = user.has_usable_password()
    if existing:
        form = ConfirmExistingPasswordForm(request.POST or None)
    else:
        form = PortalSetPasswordForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            if existing:
                from django.contrib.auth import authenticate

                if authenticate(request, email=user.email, password=form.cleaned_data["password"]) is None:
                    form.add_error("password", "That password is not correct.")
                    raise services.PortalError("")
                services.accept_invitation(inv, password=None, request=request)
            else:
                services.accept_invitation(inv, password=form.cleaned_data["new_password1"], request=request)
        except services.PortalError as exc:
            if str(exc):
                form.add_error(None, str(exc))
        else:
            messages.success(request, "Your portal access is ready. Sign in to continue.")
            return redirect("portal:login")
    return _page(
        request,
        "portal/auth/set_password.html",
        {
            "form": form,
            "email": user.email,
            "mode": "invite",
            "organisation": member.organisation,
            "existing": existing,
            "role": member.get_role_display(),
        },
    )


@portal_view()
@require_http_methods(["GET", "POST"])
def otp_setup(request, ctx):
    user = ctx.user
    if ctx.preview:
        return redirect("portal_preview:account_security", preview_member=ctx.member.pk)
    if otp.confirmed_devices(user).exists():
        return redirect("portal:account_security")
    device = otp.pending_device(user)
    form = OTPForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        token = "".join(ch for ch in form.cleaned_data["token"] if ch.isdigit())
        if device.verify_token(token):
            device.confirmed = True
            device.save(update_fields=["confirmed"])
            otp_login(request, device)
            record(
                "portal.mfa_enrolled",
                request=request,
                actor=user,
                entity=user,
                summary="Authenticator enrolled",
            )
            messages.success(request, "Two-step sign-in is on.")
            return redirect("portal:account_security")
        form.add_error("token", "That code did not match. Scan the QR code again and enter the current code.")
    from .customer import show

    return show(
        request,
        ctx,
        "portal/auth/otp_setup.html",
        {
            "form": form,
            "qr_svg": otp.qr_svg(device),
            "secret": otp.base32_secret(device),
            "settings_section": "security",
        },
    )
