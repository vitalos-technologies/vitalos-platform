"""Super Admin › Account & security in the Settings layout: one URL per section (Profile, Password, Two-step sign-in),
a menu of real links with aria-current, and every form posting, validating, messaging and auditing as before.
Synthetic users only."""

import re

import pytest
from django.contrib.auth import SESSION_KEY
from django.test import Client
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.models import AuditEvent

SECTIONS = {
    "profile": "/account/",
    "password": "/account/password/",
    "two_step": "/account/two-step/",
}
PANELS = {
    "profile": 'data-testid="account-profile"',
    "password": 'data-testid="account-password"',
    "two_step": 'data-testid="account-two-step"',
}
SETUP = "/account/2fa/setup/"


def menu(body: str) -> str:
    start = body.index('<nav aria-label="Account sections"')
    return body[start : body.index("</nav>", start)]


def current(body: str) -> list[str]:
    return re.findall(r'<a [^>]*aria-current="page"[^>]*data-settings-section="([a-z_]+)"', menu(body))


def messages_of(response) -> list[str]:
    return [str(m) for m in response.context["messages"]] if response.context else []


@pytest.fixture
def users(viewer, lead, superadmin):
    return {"Viewer": viewer, "ServiceLead": lead, "SuperAdmin": superadmin}


# --- Each section is its own page ---------------------------------------------------------------------------------


def test_every_section_renders_alone_with_its_menu_item_current(users, client_for):
    for role, user in users.items():
        client = client_for(user)
        for key, path in SECTIONS.items():
            response = client.get(path)
            assert response.status_code == 200, (role, path)
            body = response.content.decode()
            assert current(body) == [key], (role, path)
            nav = menu(body)
            for other in SECTIONS.values():
                assert f'href="{other}"' in nav, (role, path, other)
            assert 'role="tab' not in body and "aria-selected" not in nav  # links, not ARIA tabs
            # The Settings layout (shared partial), with only this section in the panel.
            assert 'class="settings-layout mt-4"' in body and 'data-testid="settings-panel"' in body
            assert 'class="settings-menu"' in nav and 'class="settings-link"' in nav
            for other, panel in PANELS.items():
                assert (panel in body) == (other == key), (role, path, other)
            assert '<h1 class="text-2xl font-semibold">Account &amp; security</h1>' in body
            assert user.email in body


def test_sections_need_a_signed_in_user(db):
    for path in (*SECTIONS.values(), SETUP):
        response = Client().get(path)
        assert response.status_code == 302 and response.url.startswith("/login/?next="), path


def test_settings_keeps_its_own_menu_on_the_shared_layout(superadmin, client_for, seeded):
    body = client_for(superadmin).get("/settings/tokens/").content.decode()
    assert '<nav aria-label="Settings sections" class="settings-menu" data-testid="settings-menu">' in body
    assert 'id="settings-region" class="settings-layout mt-4" hx-get="/settings/tokens/"' in body
    assert 'aria-label="Account sections"' not in body


def test_user_menu_and_palette_still_open_account(superadmin, client_for, seeded):
    client = client_for(superadmin)
    body = client.get("/").content.decode()
    assert 'href="/account/">Account &amp; security</a>' in body
    palette = client.get("/palette/?q=account", HTTP_HX_REQUEST="true").content.decode()
    assert 'href="/account/"' in palette


# --- Every form posts, validates, messages and audits as before ----------------------------------------------------


def test_profile_saves_from_its_section(viewer, client_for):
    client = client_for(viewer)
    body = client.get("/account/").content.decode()
    form = re.search(r'<form method="post" action="/account/".*?</form>', body, re.S).group(0)
    assert 'name="action" value="profile"' in form
    assert 'name="csrfmiddlewaretoken"' in form
    response = client.post("/account/", {"action": "profile", "full_name": "Vera Viewer"}, follow=True)
    assert response.redirect_chain == [("/account/", 302)]
    assert "Profile updated." in messages_of(response)
    viewer.refresh_from_db()
    assert viewer.full_name == "Vera Viewer"
    too_long = client.post("/account/", {"action": "profile", "full_name": "x" * 151})
    assert too_long.status_code == 200 and current(too_long.content.decode()) == ["profile"]
    assert "field-error" in too_long.content.decode()


def test_password_changes_from_its_section_and_errors_stay_there(viewer, client_for):
    viewer.set_password("Old-Synthetic-7!")
    viewer.save()
    client = client_for(viewer)
    body = client.get("/account/password/").content.decode()
    form = re.search(r'<form[^>]*action="/account/password/".*?</form>', body, re.S).group(0)
    assert 'name="action" value="password"' in form and 'name="csrfmiddlewaretoken"' in form
    wrong = client.post(
        "/account/password/",
        {
            "action": "password",
            "old_password": "not-the-password",
            "new_password1": "Fresh-Synthetic-9!",
            "new_password2": "Fresh-Synthetic-9!",
        },
    )
    assert wrong.status_code == 200 and current(wrong.content.decode()) == ["password"]
    assert "field-error" in wrong.content.decode()
    response = client.post(
        "/account/password/",
        {
            "action": "password",
            "old_password": "Old-Synthetic-7!",
            "new_password1": "Fresh-Synthetic-9!",
            "new_password2": "Fresh-Synthetic-9!",
        },
        follow=True,
    )
    assert response.redirect_chain == [("/account/password/", 302)]
    assert "Password changed." in messages_of(response)
    viewer.refresh_from_db()
    assert viewer.check_password("Fresh-Synthetic-9!")
    assert client.session.get(SESSION_KEY) == str(viewer.pk)  # still signed in
    assert AuditEvent.objects.filter(action="auth.password_changed", actor=viewer).count() == 1


def test_old_account_url_still_accepts_every_form(viewer, client_for):
    """Forms opened before the split posted every action to /account/; that target keeps working."""
    viewer.set_password("Old-Synthetic-7!")
    viewer.save()
    client = client_for(viewer)
    response = client.post(
        "/account/",
        {
            "action": "password",
            "old_password": "Old-Synthetic-7!",
            "new_password1": "Fresh-Synthetic-9!",
            "new_password2": "Fresh-Synthetic-9!",
        },
    )
    assert response.status_code == 302 and response.url == "/account/password/"
    bad = client.post("/account/", {"action": "reset_2fa", "password": "wrong"})
    assert bad.status_code == 200 and current(bad.content.decode()) == ["two_step"]
    assert "Incorrect password." in bad.content.decode()
    assert TOTPDevice.objects.filter(user=viewer, confirmed=True).exists()
    nothing = client.post("/account/two-step/", {})
    assert nothing.status_code == 200 and current(nothing.content.decode()) == ["two_step"]


def test_two_step_section_replaces_the_authenticator_and_signs_out(viewer, client_for):
    viewer.set_password("Old-Synthetic-7!")
    viewer.save()
    client = client_for(viewer)
    body = client.get("/account/two-step/").content.decode()
    assert "An authenticator app is enrolled and required for your role." in body
    assert "Replace authenticator (signs you out)" in body
    form = re.search(r'<form[^>]*action="/account/two-step/".*?</form>', body, re.S).group(0)
    assert 'name="action" value="reset_2fa"' in form and 'name="csrfmiddlewaretoken"' in form
    wrong = client.post("/account/two-step/", {"action": "reset_2fa", "password": "nope"})
    assert wrong.status_code == 200 and "Incorrect password." in wrong.content.decode()
    response = client.post(
        "/account/two-step/", {"action": "reset_2fa", "password": "Old-Synthetic-7!"}, follow=True
    )
    assert response.redirect_chain[0] == ("/login/", 302)
    assert "Your authenticator was removed. Sign in again to enrol a new one." in messages_of(response)
    assert not TOTPDevice.objects.filter(user=viewer).exists()
    assert SESSION_KEY not in client.session
    assert AuditEvent.objects.filter(action="auth.mfa_reset", actor=viewer).count() == 1


def test_set_up_from_the_two_step_section_opens_in_the_shell(viewer, client_for):
    client = client_for(viewer, verified=False)  # a Viewer with no authenticator may browse without one
    body = client.get("/account/two-step/").content.decode()
    assert "No authenticator app is enrolled." in body
    assert f'href="{SETUP}?next=/account/two-step/"' in body
    setup = client.get(f"{SETUP}?next=/account/two-step/")
    page = setup.content.decode()
    assert setup.status_code == 200 and current(page) == ["two_step"]
    assert 'data-testid="account-otp-setup"' in page and 'data-testid="totp-secret"' in page
    assert 'name="next" value="/account/two-step/"' in page and "js/otp.js" in page
    assert 'href="/account/two-step/" class="btn btn-secondary">Cancel</a>' in page
    device = TOTPDevice.objects.get(user=viewer, confirmed=False)
    token = f"{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits):06d}"
    response = client.post(f"{SETUP}?next=/account/two-step/", {"token": token, "next": "/account/two-step/"})
    assert response.status_code == 302 and response.url == "/account/two-step/"
    after = client.get("/account/two-step/")
    assert "Two-factor authentication is on." in messages_of(after)
    assert "An authenticator app is enrolled and required for your role." in after.content.decode()
    assert AuditEvent.objects.filter(action="auth.mfa_enrolled", actor=viewer).count() == 1


def test_required_enrolment_at_sign_in_keeps_the_sign_in_card(superadmin):
    client = Client()
    client.force_login(superadmin)  # SuperAdmin, no authenticator yet: the role requires one
    response = client.get("/account/password/")
    assert response.status_code == 302 and response.url.startswith(f"{SETUP}?next=")
    setup = client.get(response.url).content.decode()
    assert "Set up two-factor authentication" in setup and 'data-testid="totp-secret"' in setup
    assert 'aria-label="Account sections"' not in setup and "global-search" not in setup
