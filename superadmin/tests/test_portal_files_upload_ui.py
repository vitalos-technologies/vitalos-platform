"""Files page "Upload a file" (button, dialog, server-side validation shown inline) and the Account settings shell
(section menu, preferences inside it). Synthetic organisations only (tests/portal_helpers.py)."""

import re

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.portal import files as portal_files
from apps.portal import services
from apps.portal.models import File, FileVersion, NotificationPreference, Role
from tests.portal_helpers import (
    build_world,
    client_for,
    make_member,
    pdf_bytes,
    upload,
)

HX = {"HTTP_HX_REQUEST": "true"}
UPLOAD = "/portal/files/upload/"


@pytest.fixture
def world(db):
    return build_world()


def page(client, path="/portal/files/") -> str:
    response = client.get(path)
    assert response.status_code == 200, path
    return response.content.decode()


def dialog(html: str) -> str:
    match = re.search(r'<dialog id="upload-dialog".*?</dialog>', html, re.S)
    assert match, "upload dialog missing"
    return match.group(0)


def select(html: str, name: str) -> str:
    match = re.search(rf'<select[^>]*name="{name}".*?</select>', html, re.S)
    assert match, f"{name} select missing"
    return match.group(0)


# --- The button: enabled, or disabled with the reason --------------------------------------------------------


@pytest.mark.parametrize("who", ["contrib", "approver", "signatory"])
def test_button_is_enabled_for_members_who_can_contribute(world, who):
    html = page(client_for(getattr(world, who).user))
    top = re.search(r'<div class="upload-action upload-action--top">.*?</div>', html, re.S).group(0)
    assert 'href="/portal/files/?upload=1" data-dialog-open="upload-dialog" aria-haspopup="dialog"' in top
    assert "Upload a file</a>" in top and "disabled" not in top and "upload-reason" not in top
    assert 'data-testid="upload-dialog"' in html and 'data-testid="upload-form"' in html


def test_viewer_sees_the_button_disabled_with_the_reason(world):
    html = page(client_for(world.viewer.user))
    top = re.search(r'<div class="upload-action upload-action--top">.*?</div>', html, re.S).group(0)
    assert '<button type="button" class="btn" disabled aria-describedby="upload-reason-top"' in top
    assert (
        '<p class="upload-action__reason" id="upload-reason-top" data-testid="upload-reason-top">'
        "Your role can view files but not upload them.</p>"
    ) in top
    assert "<dialog" not in html and 'name="file"' not in html  # no form at all
    assert "Shared report" in html  # viewers still see the files


def test_no_shared_challenge_disables_the_button_with_the_reason(world):
    org = services.create_organisation(name="Fabrikam Synthetic Ltd", actor=world.staff, synthetic=True)
    member = make_member(org, "contrib@fabrikam.example.test", Role.CONTRIBUTOR, "Fran Fabrikam")
    html = page(client_for(member.user))
    reason = "You can upload once Vitalos shares a challenge with you."
    assert 'disabled aria-describedby="upload-reason-top"' in html
    assert f'id="upload-reason-top" data-testid="upload-reason-top">{reason}</p>' in html
    # The empty state explains it in its own words instead of repeating a second disabled button.
    assert html.count(reason) == 1 and 'data-testid="upload-button-empty"' not in html
    assert "Files appear here once a challenge has been shared with you." in html
    assert "<dialog" not in html


def test_empty_state_offers_the_same_action_when_nothing_is_uploaded_yet(world):
    File.objects.all().delete()
    html = page(client_for(world.contrib.user))
    empty = re.search(
        r'<div class="empty empty--action" data-testid="files-empty">.*?</div>\s*</div>', html, re.S
    )
    assert empty and 'data-testid="upload-button-empty"' in empty.group(0)
    assert 'href="/portal/files/?upload=1"' in empty.group(0)


def test_staff_preview_is_read_only(world):
    staff = client_for(world.staff)
    base = f"/client-portal/preview/{world.contrib.pk}/as/"
    html = page(staff, base + "files/")
    assert (
        'id="upload-reason-top" data-testid="upload-reason-top">'
        "Preview as customer is read-only, so uploading is turned off here.</p>"
    ) in html
    assert "<dialog" not in html and 'name="file"' not in html
    before = FileVersion.objects.count()
    assert (
        staff.post(base + "files/upload/", {"challenge": world.ch_a.pk, "file": upload()}).status_code == 403
    )
    assert FileVersion.objects.count() == before
    # A previewed viewer shows the viewer's own reason, as the customer sees it.
    html = page(staff, f"/client-portal/preview/{world.viewer.pk}/as/files/")
    assert "Your role can view files but not upload them." in html


def test_upload_query_opens_the_dialog_without_javascript(world):
    html = page(client_for(world.contrib.user), "/portal/files/?upload=1")
    assert (
        '<dialog id="upload-dialog" class="upload-dialog" aria-labelledby="upload-title" open data-modal-on-load'
        in html
    )
    assert 'data-page-url="/portal/files/"' in html
    assert " open " not in dialog(page(client_for(world.contrib.user)))[:120]
    assert "<dialog" not in page(client_for(world.viewer.user), "/portal/files/?upload=1")


# --- The dialog: choices, limits and the privacy line ---------------------------------------------------------


def test_challenge_select_lists_only_this_organisations_shared_challenges(world):
    from apps.aidata import services as aidata_services

    opp = aidata_services.create_opportunity(
        {
            "title": "Not shared yet",
            "organisation": "Synthetic",
            "problem_summary": "p",
            "desired_outcome": "o",
        },
        world.staff,
    )
    services.link_challenge(
        opportunity=opp, organisation=world.org_a, actor=world.staff, title="Unshared draft"
    )
    challenge = select(page(client_for(world.contrib.user)), "challenge")
    assert f'<option value="{world.ch_a.pk}" selected>Invoice matching</option>' in challenge  # the only one
    assert "Support triage" not in challenge and str(world.ch_b.pk) not in challenge  # org B
    assert "Unshared draft" not in challenge
    other = select(page(client_for(world.b_approver.user)), "challenge")
    assert "Support triage" in other and "Invoice matching" not in other


def test_project_select_lists_published_projects_grouped_by_challenge(world):
    services.save_project(world.ch_a, actor=world.staff, name="Draft project not published", status="active")
    project = select(page(client_for(world.contrib.user)), "project")
    assert '<option value="">No specific project</option>' in project
    assert f'<optgroup label="Invoice matching" data-challenge="{world.ch_a.pk}">' in project
    assert f'<option value="{world.project_a.pk}">Invoice matching pilot</option>' in project
    assert "Triage pilot" not in project and "Draft project not published" not in project
    assert 'data-filter-by="up-challenge"' in project


def test_dialog_states_types_size_and_privacy_from_the_file_rules(world):
    html = dialog(page(client_for(world.contrib.user)))
    summary = portal_files.accepted_summary()
    assert summary == (
        "PDF, PNG, JPEG, GIF, WebP, Word (.docx), Excel (.xlsx), PowerPoint (.pptx), plain text (.txt) or CSV"
    )
    assert f"{summary}. Up to 10 MB, one file at a time. {portal_files.LEGACY_NOTE}" in html
    accept = portal_files.accept_attribute()
    assert f'accept="{accept}"' in html and ".doc," not in accept + "," and ".xls," not in accept + ","
    assert set(accept.split(",")) >= {".pdf", ".jpg", ".jpeg", ".docx", ".xlsx", ".pptx", ".csv", ".txt"}
    assert (
        "Only people in Northwind Synthetic Ltd who use this portal, and the Vitalos team, can see files you "
        "upload here. Files are checked by content before they are kept"
    ) in html
    # Every extension the page offers passes the real check with a valid file of that type.
    assert all(ext in portal_files._TYPE_LABELS for ext in portal_files.accepted_extensions())


def test_every_upload_form_control_has_a_label(world):
    html = dialog(page(client_for(world.contrib.user)))
    for control in ("up-file", "up-challenge", "up-project", "up-title"):
        assert f'<label for="{control}">' in html and f'id="{control}"' in html, control


# --- Uploading ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["contrib", "approver"])
def test_upload_succeeds_redirects_to_the_file_and_lists_it(world, who):
    client = client_for(getattr(world, who).user)
    response = client.post(
        UPLOAD,
        {
            "challenge": world.ch_a.pk,
            "project": world.project_a.pk,
            "title": f"Ledger sample from {who}",
            "file": upload("ledger.pdf"),
        },
    )
    file = File.objects.get(title=f"Ledger sample from {who}")
    assert response.status_code == 302 and response["Location"] == f"/portal/files/{file.pk}/"
    assert (
        file.uploaded_by_customer and file.visibility == "customer" and file.project_id == world.project_a.pk
    )
    assert file.versions.get().upload_status == FileVersion.Status.STORED
    detail = client.get(response["Location"]).content.decode()
    assert (
        f'<div class="toast toast--success"><span>File uploaded: Ledger sample from {who}.</span>' in detail
    )
    listing = page(client)
    assert f'href="/portal/files/{file.pk}/">Ledger sample from {who}</a>' in listing


def test_htmx_upload_redirects_the_browser_to_the_file(world):
    response = client_for(world.contrib.user).post(
        UPLOAD, {"challenge": world.ch_a.pk, "file": upload("hx.pdf")}, **HX
    )
    file = File.objects.get(title="hx.pdf")
    assert response.status_code == 200 and response["HX-Redirect"] == f"/portal/files/{file.pk}/"


def test_viewer_upload_is_refused(world):
    response = client_for(world.viewer.user).post(UPLOAD, {"challenge": world.ch_a.pk, "file": upload()})
    assert response.status_code == 403 and not File.objects.filter(title="notes.pdf").exists()


def test_another_organisations_challenge_or_project_is_a_404(world):
    client = client_for(world.contrib.user)
    before = FileVersion.objects.count()
    assert client.post(UPLOAD, {"challenge": world.ch_b.pk, "file": upload()}).status_code == 404
    assert (
        client.post(
            UPLOAD, {"challenge": world.ch_a.pk, "project": world.project_b.pk, "file": upload()}
        ).status_code
        == 404
    )
    assert client.post(UPLOAD, {"challenge": world.ch_b.pk, "file": upload()}, **HX).status_code == 404
    assert FileVersion.objects.count() == before


def test_a_project_from_another_challenge_is_refused_inline(world):
    from apps.aidata import services as aidata_services

    opp = aidata_services.create_opportunity(
        {"title": "Second", "organisation": "Synthetic", "problem_summary": "p", "desired_outcome": "o"},
        world.staff,
    )
    second = services.link_challenge(
        opportunity=opp, organisation=world.org_a, actor=world.staff, title="Second"
    )
    services.share_challenge(second, actor=world.staff)
    response = client_for(world.contrib.user).post(
        UPLOAD, {"challenge": second.pk, "project": world.project_a.pk, "file": upload("mixed.pdf")}
    )
    html = response.content.decode()
    assert response.status_code == 200 and "That project belongs to another challenge." in html
    assert not File.objects.filter(title="mixed.pdf").exists()
    with pytest.raises(services.PortalError, match="another challenge"):
        services.upload_customer_file(world.contrib, second, upload("svc.pdf"), project=world.project_a)


def test_upload_needs_csrf_and_post(world):
    client = Client(enforce_csrf_checks=True)
    client.force_login(world.contrib.user)
    assert client.post(UPLOAD, {"challenge": world.ch_a.pk, "file": upload("csrf.pdf")}).status_code == 403
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page(client)).group(1)
    ok = client.post(
        UPLOAD, {"challenge": world.ch_a.pk, "file": upload("csrf.pdf"), "csrfmiddlewaretoken": token}
    )
    assert ok.status_code == 302 and File.objects.filter(title="csrf.pdf").exists()
    assert client_for(world.contrib.user).get(UPLOAD).status_code == 405


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (lambda: upload("run.exe", b"MZ\x90", "application/octet-stream"), "This file type is not accepted"),
        (lambda: upload("big.pdf", pdf_bytes(b"0" * (10 * 1024 * 1024 + 1))), "Larger than 10 MB"),
        (
            lambda: upload("old.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 64, "application/msword"),
            "Older Word and Excel files",
        ),
        (lambda: upload("fake.pdf", b"not a pdf at all"), "File contents do not match the declared type"),
    ],
)
def test_type_and_size_errors_render_inline_in_the_open_dialog(world, data, message):
    before = FileVersion.objects.count()
    response = client_for(world.contrib.user).post(UPLOAD, {"challenge": world.ch_a.pk, "file": data()})
    html = response.content.decode()
    assert response.status_code == 200
    box = dialog(html)
    assert " open data-modal-on-load" in box and 'data-testid="upload-errors"' in box
    assert 'aria-describedby="up-file-help up-file-error" aria-invalid="true"' in box
    assert re.search(rf'<p class="error" id="up-file-error">{re.escape(message)}', box)
    assert FileVersion.objects.count() == before
    assert AuditEvent.objects.filter(action="portal.file_rejected").exists()


def test_htmx_error_returns_only_the_form_with_its_errors(world):
    response = client_for(world.contrib.user).post(
        UPLOAD,
        {"challenge": world.ch_a.pk, "file": upload("run.exe", b"MZ", "application/octet-stream")},
        **HX,
    )
    html = response.content.decode()
    assert response.status_code == 200 and "<html" not in html and "<dialog" not in html
    assert html.lstrip().startswith('<form id="upload-form"') and "This file type is not accepted" in html
    assert f'<option value="{world.ch_a.pk}" selected>' in html  # the choice is kept


def test_missing_file_challenge_and_more_than_one_file(world):
    client = client_for(world.contrib.user)
    html = client.post(UPLOAD, {"title": "No file"}).content.decode()
    assert "Choose a file to upload." in html and "Choose the challenge this file is for." in html
    assert 'value="No file"' in html  # the typed title is kept
    two = client.post(UPLOAD, {"challenge": world.ch_a.pk, "file": [upload("a.pdf"), upload("b.pdf")]})
    assert "Upload one file at a time." in two.content.decode()
    assert not File.objects.filter(title__in=["a.pdf", "b.pdf"]).exists()


def test_without_storage_the_page_says_so_and_the_upload_is_recorded_honestly(world, settings):
    settings.PORTAL_FILES_STORAGE_ENABLED = False
    client = client_for(world.contrib.user)
    html = page(client)
    notice = "File storage is not set up yet. You can still record a file, but its contents will not be kept"
    assert html.count(notice) == 2  # the page and the dialog
    response = client.post(UPLOAD, {"challenge": world.ch_a.pk, "file": upload("nostore.pdf")}, follow=True)
    assert "file storage is not set up yet, so its contents were not kept" in response.content.decode()
    version = FileVersion.objects.get(original_name="nostore.pdf")
    assert version.upload_status == FileVersion.Status.UNAVAILABLE and not version.storage_key


def test_staff_still_see_customer_uploads(world):
    client_for(world.contrib.user).post(
        UPLOAD, {"challenge": world.ch_a.pk, "title": "Customer evidence pack", "file": upload("pack.pdf")}
    )
    staff = client_for(world.staff)
    assert (
        "Customer evidence pack" in staff.get(f"/client-portal/challenges/{world.ch_a.pk}/").content.decode()
    )
    activity = re.search(
        r'data-testid="customer-activity">(.*?)</ul>', staff.get("/client-portal/").content.decode(), re.S
    ).group(1)
    assert "Colin Contributor uploaded pack.pdf" in activity
    assert AuditEvent.objects.filter(action="portal.file_uploaded").exists()


def test_new_version_from_the_file_page_still_works_and_refusals_return_there(world):
    client = client_for(world.contrib.user)
    first = services.upload_customer_file(world.contrib, world.ch_a, upload("mine.pdf"))
    ok = client.post(
        UPLOAD, {"challenge": world.ch_a.pk, "file_id": first.file_id, "file": upload("mine2.pdf")}
    )
    assert ok.status_code == 302 and ok["Location"] == f"/portal/files/{first.file_id}/"
    assert first.file.versions.count() == 2
    bad = client.post(
        UPLOAD,
        {
            "challenge": world.ch_a.pk,
            "file_id": first.file_id,
            "file": upload("x.exe", b"MZ", "application/x"),
        },
    )
    assert bad.status_code == 302 and bad["Location"] == f"/portal/files/{first.file_id}/"
    assert first.file.versions.count() == 2


# --- Account settings shell -------------------------------------------------------------------------------------
# One page per section: every menu item is a real URL and only the selected section is on the page.


def settings_nav(html: str) -> str:
    match = re.search(r'<nav class="settings__nav".*?</nav>', html, re.S)
    assert match, "settings menu missing"
    return match.group(0)


SECTIONS = {
    "Profile": "/portal/account/",
    "Sign-in &amp; security": "/portal/account/security/",
    "Notifications on this device": "/portal/account/device/",
    "Notification preferences": "/portal/notifications/preferences/",
    "Install the app": "/portal/account/install/",
}
# What marks each section's content.
SECTION_CARDS = {
    "/portal/account/": 'data-testid="settings-profile"',
    "/portal/account/security/": 'data-testid="settings-security"',
    "/portal/account/device/": 'data-testid="push-card"',
    "/portal/notifications/preferences/": 'data-testid="settings-preferences"',
    "/portal/account/install/": 'data-testid="install-card"',
}
TWO_STEP = "/portal/account/security/two-step/"


def menu_links(nav: str) -> list[tuple[str, str]]:
    found = re.findall(r'<a class="settings__link" href="([^"]+)"[^>]*>.*?<span>(.*?)</span></a>', nav, re.S)
    return [(label, href) for href, label in found]


def current_item(nav: str) -> list[str]:
    return re.findall(r'aria-current="page">.*?<span>(.*?)</span>', nav, re.S)


def test_every_settings_section_is_its_own_page(world):
    client = client_for(world.approver.user)
    for label, path in SECTIONS.items():
        html = page(client, path)
        nav = settings_nav(html)
        assert 'aria-label="Account settings"' in nav and 'role="tab' not in nav  # links, not ARIA tabs
        assert menu_links(nav) == list(SECTIONS.items()), path
        assert "#" not in nav  # no anchors: each section has its own URL
        assert current_item(nav) == [label], path
        content = html.split('<div class="settings__content">', 1)[1]
        for other, card in SECTION_CARDS.items():
            assert (card in content) == (other == path), (path, other)
        assert "<h1>Your account</h1>" in html
        # The top menu marks Account and the mobile tab bar marks More, as before.
        assert re.search(r'<a href="/portal/account/" aria-current="page">Account</a>', html), path
        assert 'class="tabbar__item is-active" popovertarget="portal-nav"' in html, path


@pytest.mark.parametrize(
    ("path", "current"),
    [
        ("/portal/account/", "Profile"),
        ("/portal/account/security/", "Sign-in &amp; security"),
        (TWO_STEP, "Sign-in &amp; security"),
        ("/portal/account/device/", "Notifications on this device"),
        ("/portal/notifications/preferences/", "Notification preferences"),
        ("/portal/account/install/", "Install the app"),
    ],
)
def test_the_active_settings_item_carries_aria_current(world, path, current):
    nav = settings_nav(page(client_for(world.approver.user), path))
    assert nav.count('aria-current="page"') == 1
    assert current_item(nav) == [current]


def test_account_sections_need_a_signed_in_member(world):
    staff = client_for(world.staff)
    for path in (*SECTIONS.values(), TWO_STEP):
        response = Client().get(path)
        assert response.status_code == 302 and "/portal/sign-in/" in response["Location"], path
        assert staff.get(path).status_code == 403, path  # staff use Preview as customer


def test_section_pages_are_get_only_and_every_form_carries_csrf(world):
    client = client_for(world.approver.user)
    for path in (
        "/portal/account/",
        "/portal/account/security/",
        "/portal/account/device/",
        "/portal/account/install/",
    ):
        assert client.post(path).status_code == 405, path
    for path in (*SECTIONS.values(), TWO_STEP):
        html = page(client, path)
        forms = re.findall(r'<form[^>]*method="post".*?</form>', html, re.S)
        assert forms, path
        for form in forms:
            assert 'name="csrfmiddlewaretoken"' in form, (path, form[:80])
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(world.approver.user)
    assert strict.post(TWO_STEP, {"token": "123456"}).status_code == 403
    assert strict.post("/portal/notifications/preferences/", {"email_updates": "on"}).status_code == 403


def test_preferences_inside_the_shell_still_save(world):
    client = client_for(world.approver.user)
    html = page(client, "/portal/notifications/preferences/")
    assert 'data-testid="preferences-form"' in html and 'class="settings"' in html
    assert re.search(r'<a href="/portal/account/" aria-current="page">Account</a>', html)  # top menu
    response = client.post(
        "/portal/notifications/preferences/", {"email_questions": "on", "push_updates": "on"}
    )
    assert response.status_code == 302 and response["Location"] == "/portal/notifications/preferences/"
    pref = NotificationPreference.objects.get(user=world.approver.user)
    assert pref.email_questions and pref.push_updates and not pref.email_updates
    assert "Your notification preferences were saved." in page(client, "/portal/notifications/preferences/")


def test_push_and_install_cards_keep_their_hooks_on_their_own_pages(world):
    client = client_for(world.approver.user)
    device = page(client, "/portal/account/device/")
    install = page(client, "/portal/account/install/")
    assert re.search(r'<section class="card push" id="device" data-push aria-labelledby="push-title"', device)
    assert re.search(
        r'<section class="card install" id="install" data-install aria-labelledby="install-title"', install
    )
    # Without push keys the card shows its "unavailable" state (test_portal_push covers the keyed states).
    for hook in ('data-push-state="unavailable"', 'data-testid="push-card"', "data-push "):
        assert hook in device and hook not in install, hook
    for hook in (
        'data-install-state="manual"',
        "data-install-button",
        'data-testid="install-card"',
        "data-install ",
    ):
        assert hook in install and hook not in device, hook
    for path in ("/portal/account/", "/portal/account/security/", "/portal/notifications/preferences/"):
        html = page(client, path)
        assert 'data-testid="push-card"' not in html and "data-install" not in html, path
    for html in (device, install):
        assert "<script" not in html.split("<main", 1)[1]  # CSP: no inline script in the page body


def test_security_section_leads_to_two_step_set_up_and_back(world):
    from django_otp.oath import totp
    from django_otp.plugins.otp_totp.models import TOTPDevice

    client = client_for(world.approver.user)
    security = page(client, "/portal/account/security/")
    row = re.search(r'data-testid="settings-security".*?</section>', security, re.S).group(0)
    assert '<span class="badge">Off</span>' in row and f'href="{TWO_STEP}">Turn on</a>' in row
    assert "Forgot your password?" in row
    setup = page(client, TWO_STEP)
    assert 'class="qr"' in setup and 'href="/portal/account/security/">Cancel</a>' in setup
    device = TOTPDevice.objects.get(user=world.approver.user, confirmed=False)
    token = f"{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits):06d}"
    response = client.post(TWO_STEP, {"token": token})
    assert response.status_code == 302 and response["Location"] == "/portal/account/security/"
    assert AuditEvent.objects.filter(action="portal.mfa_enrolled", actor=world.approver.user).exists()
    after = page(client, "/portal/account/security/")
    assert "Two-step sign-in is on." in after and '<span class="badge badge--ok">On</span>' in after
    assert f'href="{TWO_STEP}"' not in after
    # Set up again once it is on: back to the section.
    again = client.get(TWO_STEP)
    assert again.status_code == 302 and again["Location"] == "/portal/account/security/"


def test_preview_hides_push_and_install_in_the_shell(world):
    staff = client_for(world.staff)
    base = f"/client-portal/preview/{world.approver.pk}/as/"
    html = page(staff, base + "account/")
    nav = settings_nav(html)
    assert "Notifications on this device" not in nav and "Install the app" not in nav
    assert [href for _label, href in menu_links(nav)] == [
        base + "account/",
        base + "account/security/",
        base + "notifications/preferences/",
    ]
    for path in ("account/", "account/security/", "notifications/preferences/"):
        html = page(staff, base + path)
        assert 'data-testid="push-card"' not in html and 'data-testid="install-card"' not in html, path
        assert "data-push" not in html and "data-install" not in html, path
    assert "two-step/" not in page(staff, base + "account/security/")  # no Turn on in preview
    # The device, install and set-up URLs exist in preview but lead back to the shell, as set-up did before.
    for path, target in (
        ("account/device/", "account/"),
        ("account/install/", "account/"),
        ("account/security/two-step/", "account/security/"),
    ):
        response = staff.get(base + path)
        assert response.status_code == 302 and response["Location"] == base + target, path
    prefs = page(staff, base + "notifications/preferences/")
    assert "Preview is read-only." in prefs and 'data-testid="preferences-form"' not in prefs


def test_account_sections_on_the_portal_host(world, settings):
    host = "portal.example.test"
    settings.PORTAL_HOST = host
    settings.ALLOWED_HOSTS = ["testserver", host]
    client = client_for(world.approver.user)
    client.defaults["HTTP_HOST"] = host
    for path in ("/account/", "/account/security/", "/account/device/", "/account/install/"):
        nav = settings_nav(page(client, path))
        assert [href for _label, href in menu_links(nav)] == [
            "/account/",
            "/account/security/",
            "/account/device/",
            "/notifications/preferences/",
            "/account/install/",
        ], path
    assert client.get("/account/security/two-step/").status_code == 200
    # The Super Admin's own account sections never answer on the portal host, and the reverse.
    for path in ("/account/password/", "/account/two-step/", "/account/2fa/setup/"):
        assert client.get(path).status_code == 404, path
    assert client_for(world.approver.user).get("/portal/account/device/").status_code == 404
