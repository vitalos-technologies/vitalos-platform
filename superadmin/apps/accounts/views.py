from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, password_validation, update_session_auth_hash
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode
from django.views.decorators.http import require_http_methods, require_POST
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.services import record
from apps.core.forms import StyledFormMixin
from apps.core.htmx import changed_response, close_modal_response

from . import lifecycle, otp, selectors, services
from .forms import (
    ApiTokenForm,
    ConfirmPasswordForm,
    ForgotPasswordForm,
    LoginForm,
    OTPTokenForm,
    ProfileForm,
    UserCreateForm,
    UserEditForm,
)
from .models import ApiToken
from .roles import SUPERADMIN, is_superadmin, primary_role, role_required
from .tokens import set_password_token


class StyledPasswordChangeForm(StyledFormMixin, PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The same rules as one line of field help, instead of the validators' HTML list (which broke out of it).
        self.fields["new_password1"].help_text = " ".join(
            password_validation.password_validators_help_texts()
        )


class StyledSetPasswordForm(StyledFormMixin, SetPasswordForm):
    pass


LAST_EMAIL_COOKIE = "vsa_last_email"


def _next_url(request, default=None) -> str:
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return default or reverse(settings.LOGIN_REDIRECT_URL)


def _second_factor_redirect(request, user):
    name = "accounts:otp_verify" if otp.confirmed_devices(user).exists() else "accounts:otp_setup"
    return HttpResponseRedirect(f"{reverse(name)}?{urlencode({'next': _next_url(request)})}")


@require_http_methods(["GET", "HEAD", "POST"])
def login_view(request):
    user = request.user
    if user.is_authenticated:
        if otp.otp_required(user) and not user.is_verified():
            return _second_factor_redirect(request, user)
        return HttpResponseRedirect(_next_url(request))
    remembered = request.COOKIES.get(LAST_EMAIL_COOKIE, "")
    initial = {"email": settings.DEFAULT_SIGNIN_EMAIL or remembered}
    form = LoginForm(request, data=request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        auth_login(request, form.user)
        if otp.otp_required(form.user):
            response = _second_factor_redirect(request, form.user)
        else:
            response = HttpResponseRedirect(_next_url(request))
        # Remember the last email on this browser (first-party, HttpOnly) to save retyping it.
        response.set_cookie(
            LAST_EMAIL_COOKIE,
            form.user.email,
            max_age=90 * 24 * 60 * 60,
            secure=request.is_secure(),
            httponly=True,
            samesite="Lax",
        )
        return response
    context = {
        "form": form,
        "next": _next_url(request, default=""),
        "can_reset": settings.PASSWORD_RESET_ENABLED,
    }
    return render(request, "accounts/login.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def otp_verify(request):
    user = request.user
    if user.is_verified() or not otp.confirmed_devices(user).exists():
        return HttpResponseRedirect(_next_url(request))
    form = OTPTokenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        device = otp.verify(user, form.cleaned_data["token"])
        if device is not None:
            otp_login(request, device)
            return HttpResponseRedirect(_next_url(request))
        form.add_error("token", "That code is not valid. Check your device's clock and try again.")
    return render(request, "accounts/otp_verify.html", {"form": form, "next": _next_url(request, default="")})


@login_required
@require_http_methods(["GET", "POST"])
def otp_setup(request):
    user = request.user
    if otp.confirmed_devices(user).exists():
        return HttpResponseRedirect(_next_url(request))
    device = otp.pending_device(user)
    form = OTPTokenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        token = "".join(ch for ch in form.cleaned_data["token"] if ch.isdigit())
        if device.verify_token(token):
            device.confirmed = True
            device.save(update_fields=["confirmed"])
            otp_login(request, device)
            record("auth.mfa_enrolled", request=request, entity=user, summary="Authenticator app enrolled")
            messages.success(request, "Two-factor authentication is on.")
            return HttpResponseRedirect(_next_url(request))
        form.add_error("token", "That code did not match. Scan the QR code again and enter the current code.")
    required = otp.otp_required(user)
    context = {
        "form": form,
        "qr_svg": otp.qr_svg(device),
        "secret": otp.base32_secret(device),
        "required": required,
        "next": _next_url(request, default=""),
    }
    if required and not user.is_verified():
        # The sign-in step: the role requires a second factor, so nothing else opens until it is set up.
        return render(request, "accounts/otp_setup.html", context)
    # Chosen from Account & security: set-up opens in that shell, under Two-step sign-in.
    context.update(section="two_step", role=primary_role(user))
    return render(request, "accounts/account_otp_setup.html", context)


@require_POST
def logout_view(request):
    auth_logout(request)
    messages.info(request, "You have signed out.")
    return redirect("accounts:login")


def _user_from_uid(uidb64):
    try:
        pk = int(force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError):
        return None
    return get_user_model().objects.filter(pk=pk, is_active=True).first()


def _no_store(response):
    response["Cache-Control"] = "no-store"
    return response


@require_http_methods(["GET", "POST"])
def set_password(request, uidb64, token):
    """Single-use, 30-minute link from `issue_setup_link` or the forgot-password email."""
    user = _user_from_uid(uidb64)
    if user is None or not set_password_token.check_token(user, token):
        context = {"invalid": True, "can_reset": settings.PASSWORD_RESET_ENABLED}
        return _no_store(render(request, "accounts/set_password.html", context, status=400))
    form = StyledSetPasswordForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()  # Changes the password hash, which invalidates this link.
        record(
            "auth.password_set", request=request, actor=user, entity=user, summary="Password set from link"
        )
        if request.user.is_authenticated:
            auth_logout(request)
        messages.success(request, "Your password is set. Sign in to continue.")
        return redirect("accounts:login")
    return _no_store(render(request, "accounts/set_password.html", {"form": form, "email": user.email}))


@require_http_methods(["GET", "POST"])
def forgot_password(request):
    """Always answers the same way, so it never reveals which emails have accounts."""
    if not settings.PASSWORD_RESET_ENABLED:
        raise Http404
    form = ForgotPasswordForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        services.request_password_reset(form.cleaned_data["email"].lower(), request)
        messages.info(
            request,
            "If that address belongs to an account, a link to set a new password is on its way. "
            "It works once and expires in 30 minutes.",
        )
        return redirect("accounts:login")
    return render(request, "accounts/forgot_password.html", {"form": form})


# Account & security: one URL per section (the Settings layout), sections "profile", "password" and "two_step", each
# rendered from accounts/account_<section>.html. Each section's form posts to its own URL with the same ``action``
# values as before, and every section URL still accepts every action, so a form posted to /account/ behaves exactly as
# it always has. A form that does not validate comes back in its own section.


def _section_of(action, default):
    if action == "reset_2fa":
        return "two_step"
    return action if action in ("profile", "password") else default


def _account_section(request, section):
    user = request.user
    action = request.POST.get("action") if request.method == "POST" else None
    section = _section_of(action, section)
    profile_form = ProfileForm(request.POST if action == "profile" else None, instance=user)
    password_form = StyledPasswordChangeForm(user, request.POST if action == "password" else None)
    reset_form = ConfirmPasswordForm(user, request.POST if action == "reset_2fa" else None)
    if action == "profile" and profile_form.is_valid():
        profile_form.save()
        messages.success(request, "Profile updated.")
        return redirect("accounts:account")
    if action == "password" and password_form.is_valid():
        password_form.save()
        update_session_auth_hash(request, password_form.user)
        record("auth.password_changed", request=request, entity=user, summary="Password changed")
        messages.success(request, "Password changed.")
        return redirect("accounts:account_password")
    if action == "reset_2fa" and reset_form.is_valid():
        TOTPDevice.objects.filter(user=user).delete()
        record("auth.mfa_reset", request=request, entity=user, summary="Authenticator removed")
        auth_logout(request)
        messages.info(request, "Your authenticator was removed. Sign in again to enrol a new one.")
        return redirect("accounts:login")
    context = {
        "section": section,
        "profile_form": profile_form,
        "password_form": password_form,
        "reset_form": reset_form,
        "has_device": otp.confirmed_devices(user).exists(),
        "otp_required": otp.otp_required(user),
        "role": primary_role(user),
    }
    return render(request, f"accounts/account_{section}.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def account(request):
    return _account_section(request, "profile")


@login_required
@require_http_methods(["GET", "POST"])
def account_password(request):
    return _account_section(request, "password")


@login_required
@require_http_methods(["GET", "POST"])
def account_two_step(request):
    return _account_section(request, "two_step")


# --- Settings: users & roles -------------------------------------------------------------------


def settings_index(request):
    if not request.user.is_authenticated:
        return redirect(f"{reverse('accounts:login')}?next=/settings/")
    target = "architecture:settings_company" if is_superadmin(request.user) else "accounts:settings_tokens"
    return redirect(target)


@role_required(SUPERADMIN)
def settings_users(request):
    rows = selectors.staff_rows(request.user)
    context = {
        "rows": rows,
        "tab": "users",
        "users_view": "staff",
        "staff_count": len(rows),
        "customer_count": selectors.customer_count(),
        "refusal": _refusal(request),
    }
    return render(request, "settings/users.html", context)


def _refusal(request) -> dict | None:
    """After a refused Suspend or Delete (``?refused=<id>&action=``): why, recomputed now, and whether
    suspending is the way forward."""
    action = request.GET.get("action", "")
    pk = request.GET.get("refused", "")
    if action not in ("suspend", "delete") or not pk.isdigit():
        return None
    target = selectors.staff_accounts().filter(pk=int(pk)).first()
    if target is None:
        return None
    reasons = lifecycle.refusal(target, request.user, action)
    if not reasons:
        return None
    return {
        "target": target,
        "action": action,
        "reasons": reasons,
        "offer_suspend": action == "delete"
        and target.is_active
        and lifecycle.can_suspend(target, request.user),
    }


STAFF_ACTIONS = ("suspend", "reactivate", "reset_2fa", "send_link", "delete")


@role_required(SUPERADMIN)
@require_POST
def user_action(request, pk, action):
    """Row actions on a staff account. Every rule lives in ``lifecycle``; a refused Suspend or Delete comes back
    to the list with the reasons and, for Delete, the offer to suspend instead."""
    if action not in STAFF_ACTIONS:
        raise Http404
    target = get_object_or_404(selectors.staff_accounts(), pk=pk)
    name = target.get_full_name()
    users_url = reverse("accounts:settings_users")
    try:
        if action == "suspend":
            changed = lifecycle.suspend_user(target, request.user, request=request)
            message = (
                f"{name} is suspended. Their sessions and API tokens stopped working."
                if changed
                else f"{name} was already suspended."
            )
        elif action == "reactivate":
            lifecycle.reactivate_user(target, request.user, request=request)
            message = f"{name} can sign in again. Earlier API tokens stay revoked."
        elif action == "reset_2fa":
            lifecycle.reset_two_step(target, request.user, request=request)
            message = (
                f"Two-step sign-in reset for {name}. They set up a new authenticator at their next sign-in."
            )
        elif action == "send_link":
            lifecycle.send_password_link(target, request.user, request=request)
            message = f"A set-password link was emailed to {target.email}. It works once, for 30 minutes."
        else:
            lifecycle.delete_user(target, request.user, request=request)
            message = f"{name}'s account was deleted. The audit trail keeps its history."
    except ValidationError as exc:
        if action in ("suspend", "delete"):
            return HttpResponseRedirect(f"{users_url}?{urlencode({'refused': target.pk, 'action': action})}")
        messages.error(request, " ".join(exc.messages))
        return HttpResponseRedirect(users_url)
    messages.success(request, message)
    return HttpResponseRedirect(users_url)


@role_required(SUPERADMIN)
@require_http_methods(["GET", "POST"])
def user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            services.create_user(
                email=data["email"],
                full_name=data["full_name"],
                role=data["role"],
                password=data["password"],
                actor=request.user,
                request=request,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return close_modal_response(
                request,
                reverse("accounts:settings_users"),
                f"User {data['email']} created with the {data['role']} role.",
            )
    return render(
        request,
        "partials/form_modal.html",
        {
            "form": form,
            "title": "Add user",
            "action": reverse("accounts:user_create"),
            "submit": "Create user",
        },
    )


@role_required(SUPERADMIN)
@require_http_methods(["GET", "POST"])
def user_edit(request, pk):
    target = get_object_or_404(selectors.staff_accounts(), pk=pk)  # customers are managed as portal users
    initial = {
        "full_name": target.full_name,
        "role": primary_role(target) or "",
        "is_active": target.is_active,
    }
    form = UserEditForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            with transaction.atomic():
                services.set_role(target, data["role"] or None, request.user, request=request)
                services.set_active(target, data["is_active"], request.user, request=request)
                if target.full_name != data["full_name"]:
                    target.full_name = data["full_name"]
                    target.save(update_fields=["full_name"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return close_modal_response(
                request, reverse("accounts:settings_users"), f"{target.email} updated."
            )
    return render(
        request,
        "partials/form_modal.html",
        {
            "form": form,
            "title": f"Edit {target.email}",
            "action": reverse("accounts:user_edit", args=[target.pk]),
            "submit": "Save",
        },
    )


# --- Settings: API tokens ----------------------------------------------------------------------


@role_required()
@require_http_methods(["GET", "POST"])
def settings_tokens(request):
    user = request.user
    form = ApiTokenForm(request.POST or None)
    new_token = None
    if request.method == "POST" and form.is_valid():
        days = form.cleaned_data["expires_in_days"]
        expires_at = timezone.now() + timedelta(days=days) if days else None
        token, new_token = ApiToken.issue(user, form.cleaned_data["name"], expires_at=expires_at)
        form = ApiTokenForm()
    tokens = ApiToken.objects.select_related("user")
    if not is_superadmin(user):
        tokens = tokens.filter(user=user)
    context = {"form": form, "tokens": tokens, "new_token": new_token, "tab": "tokens"}
    response = render(request, "settings/tokens.html", context)
    if new_token:
        response["Cache-Control"] = "no-store"
    return response


@role_required()
@require_POST
def token_revoke(request, pk):
    token = get_object_or_404(ApiToken, pk=pk)
    if token.user_id != request.user.pk and not is_superadmin(request.user):
        raise PermissionDenied
    if token.revoked_at is None:
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at"])
    return changed_response(request, reverse("accounts:settings_tokens"), f"Token “{token.name}” revoked.")
