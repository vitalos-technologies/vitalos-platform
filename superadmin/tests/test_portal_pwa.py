"""The installable client portal (ADR-056, Phase 1): manifest, service worker, offline page, head tags, the mobile
tab bar, install guidance and host isolation.

The service worker's privacy rule is tested at the source: it may cache public static files and the offline page,
and nothing from the workspace.
"""

import json
import re
from pathlib import Path

import pytest
from django.conf import settings as django_settings
from django.contrib.staticfiles import finders
from django.test import Client, RequestFactory
from django.urls import NoReverseMatch, reverse

from apps.portal import pwa
from apps.portal import selectors as portal_selectors
from apps.portal.views import pwa as pwa_views
from tests.portal_helpers import build_world, client_for

BASE_DIR = Path(__file__).resolve().parent.parent
PORTAL_HOST = "portal.example.test"
# Path segments of the customer workspace. None may appear in what the worker caches.
WORKSPACE_SEGMENTS = (
    "challenges/",
    "projects/",
    "files/",
    "questions/",
    "notifications/",
    "deliverables/",
    "versions/",
    "milestones/",
    "changes/",
    "updates/",
    "activity/",
    "search/",
    "assistant/",
    "account/",
    "export",
    "download",
    "sign-in/",
    "invitation/",
    "reset/",
)
HASHED = re.compile(r"\.[0-9a-f]{12}\.[A-Za-z0-9]+$")  # the same rule as the worker's HASHED


@pytest.fixture
def world(db, mailoutbox):
    built = build_world()
    mailoutbox.clear()
    return built


@pytest.fixture
def portal_host(settings):
    settings.PORTAL_HOST = PORTAL_HOST
    settings.ALLOWED_HOSTS = ["testserver", "localhost", PORTAL_HOST]
    return PORTAL_HOST


def on_host(client: Client, host: str) -> Client:
    client.defaults["HTTP_HOST"] = host
    return client


def personal_strings(world) -> list[str]:
    strings = [world.org_a.name, world.org_b.name, "Northwind", "Contoso"]
    for member in (world.viewer, world.contrib, world.approver, world.signatory, world.b_approver):
        strings += [member.user.email, member.user.full_name]
    return [s for s in strings if s]


def static_file_exists(url: str) -> bool:
    assert url.startswith(django_settings.STATIC_URL), url
    return finders.find(url[len(django_settings.STATIC_URL) :]) is not None


def precache_from(source: str) -> list[str]:
    match = re.search(r"const PRECACHE = (\[.*?\]);", source, re.S)
    assert match, "PRECACHE list not found in sw.js"
    return json.loads(match.group(1))


def js_constant(source: str, name: str) -> str:
    match = re.search(rf"const {name} = (\"[^\"]*\");", source)
    assert match, name
    return json.loads(match.group(1))


# --- Manifest ---------------------------------------------------------------------------------------------------


def test_manifest_is_public_valid_and_scoped_to_the_portal_root(world):
    response = Client().get("/portal/manifest.webmanifest")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/manifest+json"
    assert response["Cache-Control"] == "no-cache"
    data = json.loads(response.content)
    root = reverse("portal:home")
    assert root == "/portal/"
    assert data["start_url"] == data["scope"] == data["id"] == root
    assert data["name"] == "Vitalos Client Portal" and data["short_name"] == "Vitalos"
    assert data["display"] == "standalone" and data["orientation"] == "any"
    assert data["description"] and data["lang"] == "en-GB"
    assert data["background_color"] == pwa.BACKGROUND_COLOR and data["theme_color"] == pwa.THEME_COLOR
    icons = {(icon["sizes"], icon["purpose"]): icon for icon in data["icons"]}
    assert set(icons) == {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")}
    for icon in data["icons"]:
        assert icon["type"] == "image/png" and static_file_exists(icon["src"]), icon
    shortcuts = {s["name"]: s["url"] for s in data["shortcuts"]}
    assert shortcuts == {"Questions": "/portal/questions/", "Notifications": "/portal/notifications/"}
    for shortcut in data["shortcuts"]:
        assert all(static_file_exists(icon["src"]) for icon in shortcut["icons"])


def test_manifest_carries_no_personal_data(world):
    anonymous = Client().get("/portal/manifest.webmanifest").content
    signed_in = client_for(world.approver.user).get("/portal/manifest.webmanifest").content
    assert anonymous == signed_in
    text = signed_in.decode()
    for value in personal_strings(world):
        assert value not in text, value


def test_manifest_colours_follow_the_portal_tokens():
    css = (BASE_DIR / "static/portal/portal.css").read_text()

    def token(name):
        return re.search(rf"--{name}:\s*(#[0-9a-f]{{6}});", css).group(1)

    assert pwa.THEME_COLOR == token("aid-ink-950")  # the header, light
    assert pwa.THEME_COLOR_DARK == token("aid-ink-900")  # the header, dark
    assert pwa.BACKGROUND_COLOR == token("aid-grey-50")  # --aid-bg, light
    assert "--aid-header-bg: var(--aid-ink-950)" in css and "--aid-header-bg: var(--aid-ink-900)" in css


def test_generated_icons_are_committed_at_their_exact_sizes():
    for name, size in (
        ("icon-192.png", 192),
        ("icon-512.png", 512),
        ("maskable-512.png", 512),
        ("apple-touch-icon-180.png", 180),
    ):
        data = (BASE_DIR / "static/portal/icons" / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", name
        width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        assert (width, height) == (size, size), name


# --- Service worker ---------------------------------------------------------------------------------------------


def test_service_worker_is_served_at_the_portal_root_with_no_cache(world):
    assert reverse("portal:service_worker") == "/portal/sw.js"
    response = Client().get("/portal/sw.js")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/javascript")
    assert response["Cache-Control"] == "no-cache"
    source = response.content.decode()
    assert "PRIVACY RULE" in source and "signing out needs no cache purge" in source


def test_service_worker_precaches_only_public_static_files_and_the_offline_page(world):
    source = Client().get("/portal/sw.js").content.decode()
    precache = precache_from(source)
    assert precache == pwa.precache_urls()
    assert js_constant(source, "OFFLINE_URL") == reverse("portal:offline") == "/portal/offline/"
    assert js_constant(source, "STATIC_PREFIX") == django_settings.STATIC_URL
    expected = {
        "portal/portal.css",
        "portal/portal.js",
        "django_htmx/htmx-2.min.js",
        "fonts/inter.woff2",
        "brand/vitalos-wordmark-reversed.png",
        "portal/icons/icon-192.png",
        "portal/icons/icon-512.png",
        "portal/icons/maskable-512.png",
        "portal/icons/apple-touch-icon-180.png",
    }
    assert expected <= {url[len(django_settings.STATIC_URL) :] for url in precache}
    for url in precache:
        assert url.startswith(django_settings.STATIC_URL), url
        assert static_file_exists(url), url
        assert not any(segment in url for segment in WORKSPACE_SEGMENTS), url
    # The worker caches exactly two kinds of thing: the precache list and the offline page.
    assert source.count("cache.addAll(") == 1 and "PRECACHE.concat([OFFLINE_URL])" in source
    assert source.count("cache.put(") == 1  # inside keep(), used only by staticFile()


def test_service_worker_never_stores_navigations_partials_or_posts(world):
    source = Client().get("/portal/sw.js").content.decode()
    assert 'if (request.method !== "GET") return;' in source
    assert "if (url.origin !== self.location.origin) return;" in source
    navigate = source.split("async function navigate", 1)[1].split("\n}\n", 1)[0]
    assert "put(" not in navigate and "keep(" not in navigate and "addAll(" not in navigate
    assert "cache.match(OFFLINE_URL" in navigate
    # Only the static prefix reaches the static handler; everything else falls through untouched.
    assert (
        "if (url.pathname.startsWith(STATIC_PREFIX)) event.respondWith(staticFile(request, url));" in source
    )
    assert source.count("event.respondWith(") == 2
    assert "keep(" in source.split("async function staticFile", 1)[1]
    # Old caches are removed when a new version activates.
    assert "caches.delete(name)" in source and "name !== CACHE" in source


def test_service_worker_is_the_same_for_everyone(world):
    anonymous = Client().get("/portal/sw.js").content
    signed_in = client_for(world.approver.user).get("/portal/sw.js").content
    assert anonymous == signed_in
    for value in personal_strings(world):
        assert value.encode() not in signed_in


def test_cache_version_changes_with_the_precached_files():
    urls = pwa.precache_urls()
    version = pwa.cache_version(urls, "/offline/")
    assert re.fullmatch(r"[0-9a-f]{12}", version)
    assert pwa.cache_version([*urls[:-1], "/static/portal/portal.0123456789ab.css"], "/offline/") != version
    assert pwa.cache_version(urls, "/portal/offline/") != version


def test_production_storage_gives_hashed_immutable_urls(world, settings, tmp_path):
    """With the manifest storage production uses, every precached file and icon has a content-hashed name, so the
    worker's cache-first rule applies to all of them and a deploy changes the cache version."""
    from django.core.management import call_command

    settings.STATIC_ROOT = tmp_path
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"},
    }
    call_command("collectstatic", "--noinput", verbosity=0)
    source = Client().get("/portal/sw.js").content.decode()
    precache = precache_from(source)
    assert precache and all(HASHED.search(url) for url in precache), precache
    data = json.loads(Client().get("/portal/manifest.webmanifest").content)
    assert all(HASHED.search(icon["src"]) for icon in data["icons"])
    page = client_for(world.approver.user).get("/portal/").content.decode()
    assert f'href="{precache[0]}"' in page  # the page links the same hashed stylesheet the worker cached


# --- Offline page -----------------------------------------------------------------------------------------------


def test_offline_page_is_public_noindex_and_identical_for_everyone(world):
    response = Client().get("/portal/offline/")
    assert response.status_code == 200
    body = response.content.decode()
    assert '<meta name="robots" content="noindex, nofollow">' in body
    assert "You're offline" in body and "nothing is stored on this device" in body
    assert ">Try again<" in body and 'href="/portal/"' in body
    signed_in = client_for(world.approver.user).get("/portal/offline/").content.decode()
    assert signed_in == body
    for value in personal_strings(world):
        assert value not in signed_in, value
    assert "csrfmiddlewaretoken" not in body and 'rel="manifest"' not in body


def test_offline_view_needs_no_database_or_session(db, django_assert_num_queries):
    request = RequestFactory().get("/portal/offline/")  # no session, no user: no context processor can run
    with django_assert_num_queries(0):
        response = pwa_views.offline(request)
    assert response.status_code == 200 and b"You're offline" in response.content


# --- Head tags and registration ---------------------------------------------------------------------------------


def test_member_pages_link_the_manifest_and_register_the_worker(world):
    page = client_for(world.approver.user).get("/portal/").content.decode()
    assert '<link rel="manifest" href="/portal/manifest.webmanifest">' in page
    assert '<meta name="theme-color" content="#0a0c0f" media="(prefers-color-scheme: light)">' in page
    assert '<meta name="theme-color" content="#111418" media="(prefers-color-scheme: dark)">' in page
    assert 'rel="apple-touch-icon"' in page and "apple-touch-icon-180.png" in page
    assert '<meta name="apple-mobile-web-app-capable" content="yes">' in page
    assert '<meta name="mobile-web-app-capable" content="yes">' in page
    assert '<meta name="apple-mobile-web-app-title" content="Vitalos">' in page
    assert "viewport-fit=cover" in page
    assert 'data-sw="/portal/sw.js" data-sw-scope="/portal/"' in page


def test_sign_in_page_is_installable_too():
    page = Client().get("/portal/sign-in/").content.decode()
    assert '<link rel="manifest" href="/portal/manifest.webmanifest">' in page
    assert 'name="theme-color"' in page and 'data-sw="/portal/sw.js"' in page


def test_staff_preview_has_no_manifest_and_registers_no_worker(world):
    staff = client_for(world.staff)
    base = f"/client-portal/preview/{world.approver.pk}/as/"
    for path in ("", "questions/", "account/"):
        page = staff.get(base + path)
        assert page.status_code == 200, path
        body = page.content.decode()
        assert 'rel="manifest"' not in body and "data-sw=" not in body, path
        assert 'name="theme-color"' not in body and "viewport-fit=cover" not in body, path
        assert 'data-testid="install-card"' not in body, path
    for path in ("manifest.webmanifest", "sw.js", "offline/"):
        assert staff.get(base + path).status_code == 404, path
    with pytest.raises(NoReverseMatch):
        reverse("portal_preview:manifest", kwargs={"preview_member": world.approver.pk})


def test_pwa_skip_flag_and_the_500_page_carry_no_worker(db, rf):
    from django.template.loader import render_to_string

    request = rf.get("/portal/missing/")
    request.portal_surface = True
    html = render_to_string("portal/errors/404.html", {}, request=request)
    assert 'data-sw="/portal/sw.js"' in html and 'rel="manifest"' in html  # the customer surface has them
    html = render_to_string("portal/errors/404.html", {"pwa_skip": True}, request=request)
    assert "data-sw=" not in html and 'rel="manifest"' not in html
    html = render_to_string("portal/errors/500.html", {})  # rendered without a request
    assert "data-sw=" not in html and 'rel="manifest"' not in html


# --- Mobile tab bar ---------------------------------------------------------------------------------------------


def tabbar(html: str) -> str:
    match = re.search(
        r'<nav class="tabbar" aria-label="Primary" data-testid="tabbar">(.*?)</nav>', html, re.S
    )
    assert match, "tab bar missing"
    return match.group(1)


def test_tab_bar_marks_the_active_section_and_shows_unread(world):
    client = client_for(world.approver.user)
    unread = portal_selectors.notifications(world.approver.user).filter(read_at__isnull=True).count()
    assert unread > 0  # the synthetic world notifies the approver about shared work
    bar = tabbar(client.get("/portal/questions/").content.decode())
    assert f'data-testid="tab-unread">{unread}</span>' in bar
    assert f'<span class="sr-only">, {unread} unread</span>' in bar
    for label in ("Home", "Challenges", "Questions", "Notifications", "More"):
        assert f'<span class="tabbar__label">{label}' in bar
    assert bar.count('aria-hidden="true" focusable="false"') == 5  # decorative icons
    assert 'popovertarget="portal-nav"' in bar
    for path, active in (
        ("/portal/", "/portal/"),
        ("/portal/challenges/", "/portal/challenges/"),
        (f"/portal/challenges/{world.ch_a.pk}/", "/portal/challenges/"),
        ("/portal/questions/", "/portal/questions/"),
        ("/portal/notifications/", "/portal/notifications/"),
    ):
        bar = tabbar(client.get(path).content.decode())
        assert bar.count('aria-current="page"') == 1, path
        assert f'<a class="tabbar__item" href="{active}" aria-current="page"' in bar, path


def test_more_tab_is_active_for_files_and_account_and_the_badge_clears(world):
    client = client_for(world.approver.user)
    for path in ("/portal/files/", "/portal/account/"):
        bar = tabbar(client.get(path).content.decode())
        assert 'aria-current="page"' not in bar, path
        assert 'class="tabbar__item is-active" popovertarget="portal-nav"' in bar, path
    client.post("/portal/notifications/read-all/")
    bar = tabbar(client.get("/portal/").content.decode())
    assert "tab-unread" not in bar and "unread</span>" not in bar


def test_more_menu_still_holds_files_search_account_and_sign_out(world):
    page = client_for(world.approver.user).get("/portal/").content.decode()
    menu = re.search(
        r'<nav class="portal-nav" id="portal-nav" popover aria-label="Main">(.*?)</nav>', page, re.S
    )
    assert menu
    body = menu.group(1)
    for needle in ('href="/portal/files/"', 'role="search"', 'href="/portal/account/"', "Sign out"):
        assert needle in body, needle
    # The tab destinations are marked so the mobile sheet can leave them out (desktop shows them as today).
    assert body.count("data-tab") == 4


# --- Install guidance -------------------------------------------------------------------------------------------


def test_account_page_offers_install_guidance_without_a_popup(world):
    page = client_for(world.approver.user).get("/portal/account/install/").content.decode()
    card = re.search(r'<section class="card install".*?</section>', page, re.S).group(0)
    assert "Install the app" in card
    assert "tap Share, then Add to Home Screen" in card  # the manual steps are in the server HTML
    assert (
        '<p data-install-state="prompt" hidden><button type="button" class="btn" data-install-button>' in card
    )
    assert '<p data-install-state="installed" hidden>' in card and "Installed on this device." in card
    assert "<dialog" not in card and "popover" not in card


# --- Host isolation ---------------------------------------------------------------------------------------------


def test_portal_host_serves_the_pwa_routes_at_its_root(world, portal_host):
    client = on_host(Client(), portal_host)
    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200 and manifest["Content-Type"] == "application/manifest+json"
    data = json.loads(manifest.content)
    assert data["start_url"] == data["scope"] == data["id"] == "/"
    assert {s["url"] for s in data["shortcuts"]} == {"/questions/", "/notifications/"}
    worker = client.get("/sw.js")
    assert worker.status_code == 200 and worker["Content-Type"].startswith("application/javascript")
    source = worker.content.decode()
    assert js_constant(source, "OFFLINE_URL") == "/offline/"
    assert not any(segment in url for url in precache_from(source) for segment in WORKSPACE_SEGMENTS)
    assert client.get("/offline/").status_code == 200
    page = on_host(client_for(world.approver.user), portal_host).get("/").content.decode()
    assert '<link rel="manifest" href="/manifest.webmanifest">' in page
    assert 'data-sw="/sw.js" data-sw-scope="/"' in page
    sign_in = client.get("/sign-in/").content.decode()
    assert '<link rel="manifest" href="/manifest.webmanifest">' in sign_in


def test_admin_host_does_not_serve_the_pwa_routes(world, portal_host):
    for client in (Client(), client_for(world.staff)):
        for path in (
            "/manifest.webmanifest",
            "/sw.js",
            "/offline/",
            "/portal/manifest.webmanifest",
            "/portal/sw.js",
            "/portal/offline/",
        ):
            assert client.get(path).status_code == 404, path


def test_portal_host_still_refuses_admin_routes(world, portal_host):
    client = on_host(Client(), portal_host)
    for path in ("/login/", "/client-portal/", "/django-admin/", "/api/v1/projects/", "/ai-data/pipeline/"):
        assert client.get(path).status_code == 404, path


def test_pwa_routes_are_404_while_the_portal_is_disabled(world, portal_host, settings):
    settings.PORTAL_ENABLED = False
    client = on_host(Client(), portal_host)
    for path in ("/manifest.webmanifest", "/sw.js", "/offline/"):
        assert client.get(path).status_code == 404, path
