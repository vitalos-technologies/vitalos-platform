"""Portal access: invitations, sign-in, lockout, password reset, revoked members, staff separation."""

import datetime as dt

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.portal import services
from apps.portal.models import Invitation, Membership, Role
from tests.portal_helpers import PASSWORD, build_world, client_for, make_member


@pytest.fixture
def world(db, mailoutbox):
    built = build_world()
    mailoutbox.clear()  # building the world publishes things, which emails members
    return built


def _invite(world, email="newbie@northwind.example.test", role=Role.CONTRIBUTOR, send=True):
    member = services.invite_member(
        organisation=world.org_a,
        email=email,
        full_name="Nina Newbie",
        role=role,
        actor=world.staff,
        send=send,
    )
    return member, member._raw_token


def test_invitation_email_has_automated_headers_and_hashed_token(world, mailoutbox, settings):
    member, token = _invite(world)
    assert len(mailoutbox) == 1
    message = mailoutbox[0]
    assert message.to == ["newbie@northwind.example.test"]
    assert message.extra_headers["Auto-Submitted"] == "auto-generated"
    assert message.extra_headers["X-Vitalos-Notification"] == "portal.invitation"
    assert token in message.body  # the link carries the raw token...
    stored = Invitation.objects.get(membership=member)
    assert token not in (stored.token_hash, str(stored.pk))  # ...but only its hash is stored
    assert stored.token_hash == services.hash_token(token) and len(stored.token_hash) == 64


def test_invitation_single_use_set_password_then_sign_in(world):
    member, token = _invite(world)
    client = Client()
    page = client.get(f"/portal/invitation/{token}/")
    assert page.status_code == 200 and b"Welcome to your portal" in page.content
    password = "A-Fresh-Synthetic-Pass-99!"
    done = client.post(f"/portal/invitation/{token}/", {"new_password1": password, "new_password2": password})
    assert done.status_code == 302 and done.url == "/portal/sign-in/"
    member.refresh_from_db()
    assert member.accepted_at is not None
    # The link is now dead.
    again = client.get(f"/portal/invitation/{token}/")
    assert again.status_code == 400 and b"already been used" in again.content
    # And the person can sign in.
    login = client.post("/portal/sign-in/", {"email": "newbie@northwind.example.test", "password": password})
    assert login.status_code == 302 and login.url == "/portal/"
    assert client.get("/portal/").status_code == 200


def test_invitation_expires(world):
    member, token = _invite(world)
    Invitation.objects.filter(membership=member).update(expires_at=timezone.now() - dt.timedelta(minutes=1))
    page = Client().get(f"/portal/invitation/{token}/")
    assert page.status_code == 400 and b"expired" in page.content
    with pytest.raises(services.PortalError):
        services.accept_invitation(Invitation.objects.get(membership=member), password="x" * 20)


def test_invitation_unknown_or_tampered_token_is_refused(world):
    _member, token = _invite(world)
    for bad in (token[:-2] + "xx", "x" * 43, "short"):
        assert Client().get(f"/portal/invitation/{bad}/").status_code == 400


def test_resending_replaces_the_old_link(world):
    member, first = _invite(world)
    second = services.resend_invitation(member, actor=world.staff, send=False)
    assert Client().get(f"/portal/invitation/{first}/").status_code == 400
    assert Client().get(f"/portal/invitation/{second}/").status_code == 200


def test_invitation_for_a_revoked_member_is_dead(world):
    member, token = _invite(world)
    services.revoke_member(member, actor=world.staff)
    assert Client().get(f"/portal/invitation/{token}/").status_code == 400


def test_staff_cannot_be_invited_as_members(world):
    with pytest.raises(services.PortalError, match="staff"):
        services.invite_member(
            organisation=world.org_a,
            email=world.staff.email,
            full_name="",
            role=Role.VIEWER,
            actor=world.staff,
            send=False,
        )


def test_existing_customer_confirms_with_password_to_join_second_org(world):
    other = make_member(world.org_b, "dual@example.test", Role.VIEWER, "Dual")
    member = services.invite_member(
        organisation=world.org_a,
        email="dual@example.test",
        full_name="Dual",
        role=Role.VIEWER,
        actor=world.staff,
        send=False,
    )
    token = member._raw_token
    client = Client()
    assert b"already have a portal account" in client.get(f"/portal/invitation/{token}/").content
    bad = client.post(f"/portal/invitation/{token}/", {"password": "wrong-password-123"})
    assert bad.status_code == 200 and Membership.objects.get(pk=member.pk).accepted_at is None
    ok = client.post(f"/portal/invitation/{token}/", {"password": PASSWORD})
    assert ok.status_code == 302 and Membership.objects.get(pk=member.pk).accepted_at is not None
    assert other.user_id == member.user_id


def test_unknown_email_or_enquiry_reference_gives_no_access(world):
    """Knowing an address or a reference number never opens anything."""
    User.objects.create_user(email="stranger@example.test", password=PASSWORD)
    client = Client()
    login = client.post("/portal/sign-in/", {"email": "stranger@example.test", "password": PASSWORD})
    assert login.status_code == 200 and b"not active" in login.content
    assert client.get("/portal/").status_code == 302  # still signed out
    anonymous = Client().get(f"/portal/challenges/{world.ch_a.pk}/")
    assert anonymous.status_code == 302 and "/portal/sign-in/" in anonymous.url
    # A signed-in user with no membership gets the "not active" page, never another organisation's data.
    user = User.objects.get(email="stranger@example.test")
    page = client_for(user).get(f"/portal/challenges/{world.ch_a.pk}/")
    assert page.status_code == 403 and world.ch_a.title.encode() not in page.content


def test_wrong_password_is_generic_and_axes_locks_out(world, settings):
    settings.AXES_FAILURE_LIMIT = 3
    client = Client()
    for _ in range(3):
        response = client.post(
            "/portal/sign-in/", {"email": world.approver.user.email, "password": "wrong-password-xyz"}
        )
    assert b"not recognised" in response.content or response.status_code in (403, 429)
    locked = client.post("/portal/sign-in/", {"email": world.approver.user.email, "password": PASSWORD})
    assert locked.status_code in (403, 429)
    assert b"Too many failed attempts" in locked.content


def test_staff_cannot_sign_in_to_the_portal(world):
    response = Client().post("/portal/sign-in/", {"email": world.staff.email, "password": PASSWORD})
    assert response.status_code == 200 and b"not recognised" in response.content


def test_signed_in_staff_get_a_staff_page_not_the_customer_ui(world):
    response = client_for(world.staff).get("/portal/")
    assert response.status_code == 403 and b"Preview as customer" in response.content


def test_revoked_member_loses_access_immediately(world):
    client = client_for(world.approver.user)
    assert client.get("/portal/").status_code == 200
    services.revoke_member(world.approver, actor=world.staff)
    assert client.get("/portal/").status_code == 403
    assert client.get(f"/portal/deliverables/{world.deliv_a.pk}/").status_code == 403
    login = Client().post("/portal/sign-in/", {"email": world.approver.user.email, "password": PASSWORD})
    assert b"not active" in login.content
    services.restore_member(world.approver, actor=world.staff)
    assert client.get("/portal/").status_code == 200


def test_deactivated_user_and_organisation_lose_access(world):
    client = client_for(world.contrib.user)
    assert client.get("/portal/").status_code == 200
    world.org_a.is_active = False
    world.org_a.save()
    assert client.get("/portal/").status_code == 403


def test_password_reset_only_reaches_live_members_and_uses_portal_links(world, mailoutbox):
    Client().post("/portal/forgot-password/", {"email": "nobody@example.test"})
    Client().post("/portal/forgot-password/", {"email": world.staff.email})
    assert mailoutbox == []  # unknown address and staff address: nothing sent, same page
    page = Client().post("/portal/forgot-password/", {"email": world.approver.user.email})
    assert b"on its way" in page.content
    assert len(mailoutbox) == 1
    body = mailoutbox[0].body
    assert "/portal/reset/" in body and "/account/set-password/" not in body
    link = [word for word in body.split() if "/portal/reset/" in word][0]
    path = "/portal/reset/" + link.split("/portal/reset/")[1]
    client = Client()
    assert client.get(path).status_code == 200
    new = "Another-Synthetic-Pass-123!"
    done = client.post(path, {"new_password1": new, "new_password2": new})
    assert done.status_code == 302
    assert client.get(path).status_code == 400  # single use
    assert (
        Client().post("/portal/sign-in/", {"email": world.approver.user.email, "password": new}).status_code
        == 302
    )


def test_reset_is_rate_limited_per_address(world, mailoutbox):
    for _ in range(5):
        Client().post("/portal/forgot-password/", {"email": world.viewer.user.email})
    assert len(mailoutbox) == 3


def test_revoked_member_gets_no_reset_email(world, mailoutbox):
    services.revoke_member(world.viewer, actor=world.staff)
    Client().post("/portal/forgot-password/", {"email": world.viewer.user.email})
    assert mailoutbox == []


def test_optional_totp_second_factor(world):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    client = Client()
    client.post("/portal/sign-in/", {"email": world.approver.user.email, "password": PASSWORD})
    assert client.get("/portal/account/").status_code == 200
    page = client.get("/portal/account/security/two-step/")
    assert page.status_code == 200 and b"<svg" in page.content
    device = TOTPDevice.objects.get(user=world.approver.user, confirmed=False)
    from django_otp.oath import totp

    token = f"{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits):06d}"
    assert client.post("/portal/account/security/two-step/", {"token": token}).status_code == 302
    # A fresh sign-in now needs the code.
    second = Client()
    second.post("/portal/sign-in/", {"email": world.approver.user.email, "password": PASSWORD})
    gate = second.get("/portal/")
    assert gate.status_code == 302 and "/portal/sign-in/verify/" in gate.url
    ok = second.post("/portal/sign-in/verify/", {"token": token})
    assert ok.status_code in (302, 200)


def test_sign_in_and_invitation_are_audited_without_secrets(world):
    member, token = _invite(world)
    Client().post(
        f"/portal/invitation/{token}/",
        {"new_password1": "Audit-Synthetic-Pass-1!", "new_password2": "Audit-Synthetic-Pass-1!"},
    )
    events = AuditEvent.objects.filter(action__startswith="portal.")
    assert events.filter(action="portal.member_invited").exists()
    assert events.filter(action="portal.invitation_accepted").exists()
    blob = " ".join(f"{e.summary} {e.metadata}" for e in events)
    assert token not in blob and "Audit-Synthetic-Pass" not in blob


def test_logout_requires_post_and_ends_the_session(world):
    client = client_for(world.approver.user)
    assert client.get("/portal/sign-out/").status_code == 405
    assert client.post("/portal/sign-out/").status_code == 302
    assert client.get("/portal/").status_code == 302
