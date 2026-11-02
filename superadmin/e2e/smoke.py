"""End-to-end smoke test for a running Super Admin (local or https://admin.vitalos.co.uk).

Usage (credentials come only from the environment and are never printed):

    SMOKE_BASE_URL=https://admin.vitalos.co.uk \
    SMOKE_EMAIL=<bootstrap admin email> \
    SMOKE_PASSWORD=... \
    python e2e/smoke.py --screenshots docs/screenshots

If the account has no authenticator yet, the test enrols a temporary TOTP device, and removes it at
the end (the real owner enrols their own on first sign-in). If a device already exists, pass its
base32 secret in SMOKE_TOTP_SECRET. Records the test creates are named "Smoke test …" and archived
(not deleted) at the end so their history remains visible.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import struct
import sys
import time
import traceback
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import Page, expect, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

SLUGS = ["consulting", "engineering", "ai-data", "experience", "managed-services", "labs"]
TABS = {
    "overview": "Overview",
    "structure": "Structure",
    "team": "Team",
    "projects": "Projects",
    "kpis": "KPIs",
}


def totp(secret: str, at: float | None = None) -> str:
    """RFC 6238 TOTP (SHA-1, 30 s, 6 digits) without third-party dependencies."""
    padded = secret.upper() + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded)
    counter = int((at or time.time()) // 30)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 1_000_000:06d}"


class SmokeSkipped(Exception):
    pass


class Smoke:
    def __init__(self, page: Page, base: str, shots: Path | None, skip_if_enrolled: bool = False):
        self.page = page
        self.skip_if_enrolled = skip_if_enrolled
        self.base = base.rstrip("/") + "/"
        self.shots = shots
        self.results: list[dict] = []
        self.enrolled_secret: str | None = None
        self.stamp = time.strftime("%Y%m%d-%H%M%S")

    def url(self, path: str) -> str:
        return urljoin(self.base, path.lstrip("/"))

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append({"check": name, "ok": bool(ok), "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}", flush=True)
        if not ok:
            raise AssertionError(name)

    def shot(self, name: str, full_page: bool = True) -> None:
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(self.shots / f"{name}.png"), full_page=full_page)

    def wait_htmx(self) -> None:
        self.page.wait_for_load_state("networkidle")

    # --- steps -----------------------------------------------------------------------------------

    def login(self, email: str, password: str) -> None:
        response = self.page.goto(self.url("/login/"))
        self.check("login page returns 200", response is not None and response.status == 200)
        self.shot("01-login")
        self.page.get_by_label("Email").fill(email)
        self.page.get_by_label("Password").fill(password)
        self.page.get_by_role("button", name="Sign in").click()
        self.page.wait_for_load_state("networkidle")
        if "/account/2fa/setup/" in self.page.url:
            secret = self.page.get_by_test_id("totp-secret").inner_text().strip()
            self.shot("02-totp-enrolment")
            self.page.get_by_label("6-digit code").fill(totp(secret))  # submits itself on the sixth digit
            self.page.wait_for_url(lambda url: "/account/2fa/setup/" not in url)
            self.enrolled_secret = secret
        elif "/login/verify/" in self.page.url:
            secret = os.environ.get("SMOKE_TOTP_SECRET", "")
            if not secret and self.skip_if_enrolled:
                raise SmokeSkipped("the account already has an authenticator enrolled")
            self.check("TOTP secret supplied for an enrolled account", bool(secret))
            if os.environ.get("SMOKE_WAIT_FRESH_TOTP"):
                time.sleep(31 - time.time() % 30)  # a code is accepted once; wait for the next window
            self.page.get_by_label("6-digit code").fill(totp(secret))  # submits itself on the sixth digit
            self.page.wait_for_url(lambda url: "/login/verify/" not in url)
        self.page.wait_for_load_state("networkidle")
        self.check(
            "signed in and on the homepage", self.page.url.rstrip("/") == self.base.rstrip("/"), self.page.url
        )

    def homepage(self) -> None:
        cards = self.page.get_by_test_id("service-line-card")
        expect(cards).to_have_count(6)
        names = [cards.nth(i).locator("h3").inner_text() for i in range(6)]
        expected = [
            "Vitalos Consulting",
            "Vitalos Engineering",
            "Vitalos AI & Data",
            "Vitalos Experience",
            "Vitalos Managed Services",
            "Vitalos Labs",
        ]
        self.check("homepage shows the six service lines in order", names == expected, ", ".join(names))
        self.shot("03-homepage")

    def dashboards(self) -> None:
        for index, slug in enumerate(SLUGS):
            response = self.page.goto(self.url(f"/s/{slug}/"))
            ok = response is not None and response.status == 200
            self.check(f"dashboard /s/{slug}/ opens", ok)
            for tab, label in list(TABS.items())[1:]:
                self.page.get_by_role("tab", name=label, exact=True).click()
                self.wait_htmx()
                expect(self.page.locator(f"#tab-{tab}[aria-selected=true]")).to_be_visible()
            if index == 0:
                self.page.goto(self.url(f"/s/{slug}/"))
                self.shot("04-dashboard-overview")
        self.check("every dashboard tab loads over HTMX", True, f"{len(SLUGS)} lines × {len(TABS)} tabs")

    def _modal_submit(self, fields: dict[str, str], button: str) -> None:
        modal = self.page.locator("#modal [role=dialog]")
        expect(modal).to_be_visible()
        for label, value in fields.items():
            field = modal.get_by_label(re.compile(rf"^{re.escape(label)}\b"))
            if field.evaluate("el => el.tagName") == "SELECT":
                field.select_option(label=value)
            else:
                field.fill(value)
        modal.get_by_role("button", name=button).click()
        expect(self.page.locator("#modal [role=dialog]")).to_have_count(0)
        self.wait_htmx()

    def create_structure(self, slug: str = "consulting") -> dict[str, str]:
        names = {
            "practice": f"Smoke test practice {self.stamp}",
            "solution": f"Smoke test solution {self.stamp}",
            "offer": f"Smoke test offer {self.stamp}",
        }
        self.page.goto(self.url(f"/s/{slug}/?tab=structure"))
        self.page.get_by_role("button", name="Add practice").click()
        self._modal_submit(
            {"Name": names["practice"], "Summary": "Synthetic record created by the smoke test."},
            "Add practice",
        )
        practice = self.page.locator("li[id^=practice-]", has_text=names["practice"])
        expect(practice).to_be_visible()
        practice.get_by_role(
            "button", name=re.compile(f"Add solution to {re.escape(names['practice'])}")
        ).click()
        self._modal_submit({"Name": names["solution"]}, "Add solution")
        solution = self.page.locator("li[id^=solution-]", has_text=names["solution"])
        expect(solution).to_be_visible()
        solution.get_by_role(
            "button", name=re.compile(f"Add offer to {re.escape(names['solution'])}")
        ).click()
        self._modal_submit({"Name": names["offer"]}, "Add offer")
        expect(self.page.locator("li[id^=offer-]", has_text=names["offer"])).to_be_visible()
        # Inline edit: change the practice status through its edit modal.
        practice.get_by_role("button", name=f"Edit {names['practice']}").click()
        self._modal_submit({"Status": "Active"}, "Save")
        expect(
            self.page.locator("li[id^=practice-]", has_text=names["practice"]).get_by_text("Active").first
        ).to_be_visible()
        self.check("created and edited a Practice → Solution → Offer", True, slug)
        self.shot("05-structure")
        return names

    def create_project(self, slug: str = "consulting") -> str:
        name = f"Smoke test project {self.stamp}"
        self.page.goto(self.url(f"/s/{slug}/?tab=projects"))
        self.page.get_by_role("button", name="Add project").click()
        self._modal_submit({"Name": name, "Client": "Synthetic smoke test", "Value": "1000"}, "Add project")
        row = self.page.locator("tr[id^=project-]", has_text=name)
        expect(row).to_be_visible()
        row.get_by_label(f"Status of {name}").select_option("active")
        self.wait_htmx()
        expect(
            self.page.locator("tr[id^=project-]", has_text=name).get_by_label(f"Status of {name}")
        ).to_have_value("active")
        self.check("created a Project and changed its status inline", True, name)
        self.shot("06-projects")
        return name

    def create_kpi(self, slug: str = "consulting") -> str:
        name = f"Smoke test KPI {self.stamp}"
        self.page.goto(self.url(f"/s/{slug}/?tab=kpis"))
        self.page.get_by_role("button", name="Add KPI").click()
        self._modal_submit({"Name": name, "Unit": "%", "Target": "50"}, "Add KPI")
        section = self.page.locator("section[id^=kpi-]", has_text=name)
        expect(section).to_be_visible()
        section.get_by_label("Date").fill(date.today().isoformat())
        section.get_by_label(re.compile("^Value")).fill("40")
        section.get_by_role("button", name="Record value").click()
        self.wait_htmx()
        section = self.page.locator("section[id^=kpi-]", has_text=name)
        expect(section.get_by_text("Off target")).to_be_visible()
        self.check("created a KPI and recorded a value (target breach flagged)", True, name)
        self.shot("07-kpis")
        return name

    def search(self) -> None:
        box = self.page.get_by_label("Search the architecture")
        box.fill("Smoke test")
        dropdown = self.page.get_by_test_id("search-dropdown")
        expect(dropdown).to_be_visible()
        expect(dropdown.get_by_text(f"Smoke test practice {self.stamp}")).to_be_visible()
        self.check("live search finds the new records", True)
        self.shot("08-search", full_page=False)
        box.fill("")

    def activity_and_history(self, names: dict[str, str]) -> None:
        self.page.goto(self.url("/activity/"))
        feed = self.page.get_by_test_id("activity-feed")
        for label in (names["practice"], names["solution"], names["offer"]):
            expect(feed.get_by_text(label).first).to_be_visible()
        self.check("activity feed shows the new records", True)
        self.shot("09-activity")
        self.page.goto(
            self.url("/django-admin/architecture/practice/?q=" + names["practice"].replace(" ", "+"))
        )
        self.page.get_by_role("link", name=names["practice"]).first.click()
        self.page.get_by_role("link", name="History").click()
        rows = self.page.locator("#change-history tbody tr")
        count = rows.count()
        self.check("history rows recorded for the practice", count >= 2, f"{count} rows")
        self.shot("10-history")

    def tour(self) -> None:
        for path, name in [
            ("/architecture/", "11-architecture"),
            ("/notifications/", "12-notifications"),
            ("/settings/company/", "13-settings-company"),
            ("/settings/users/", "14-settings-users"),
            ("/settings/data/", "15-settings-data"),
            ("/api/docs/", "16-api-docs"),
            ("/products/", "16b-product-pipeline"),
        ]:
            response = self.page.goto(self.url(path))
            self.check(f"{path} returns 200", response is not None and response.status == 200)
            if path == "/api/docs/":
                expect(self.page.locator(".swagger-ui").first).to_be_visible()
                self.page.wait_for_timeout(1500)
            self.shot(name)
        self.page.goto(self.url("/"))
        expect(self.page.get_by_test_id("bell")).to_be_visible()

    def use_template(self) -> None:
        """Mail > Email templates > Use: fill a detail, see the live preview, the fallback note and Send."""
        self.page.goto(self.url("/mail/templates/?q=proposal-sent"))
        link = self.page.get_by_test_id("use-template").first
        if link.count() == 0:
            self.check("email template Use page (no templates seeded, skipped)", True)
            return
        link.click()
        self.page.wait_for_load_state("networkidle")
        expect(self.page.get_by_role("heading", name="Use template")).to_be_visible()
        self.check("Use template page opens from the list", "/use/" in self.page.url)
        expect(self.page.get_by_test_id("preview-frame")).to_be_visible()
        self.page.get_by_label("Recipient email").fill("smoke.test@example.test")
        self.page.get_by_label("Recipient's first name").fill("Smoke")
        self.wait_htmx()
        expect(self.page.get_by_test_id("empty-variables")).to_be_visible()
        self.check("Use template preview re-renders and lists the empty optional details", True)
        expect(self.page.get_by_test_id("download-eml")).to_be_enabled()
        expect(self.page.get_by_test_id("send-email")).to_be_enabled()  # not clicked: the smoke sends no mail
        self.shot("17-use-template")

    def confirm_if_asked(self) -> None:
        """Answer yes in the admin's confirmation dialog (partials/confirm_dialog.html) when it opens."""
        dialog = self.page.get_by_test_id("confirm-dialog")
        try:
            dialog.wait_for(state="visible", timeout=3000)
        except PlaywrightTimeoutError:
            return
        dialog.get_by_test_id("confirm-ok").click()
        expect(dialog).to_be_hidden()

    def cleanup(self, names: dict[str, str], project: str, kpi: str, password: str) -> None:
        def archive_in(tab: str, locator_css: str, label: str) -> None:
            self.page.goto(self.url(f"/s/consulting/?tab={tab}"))
            item = self.page.locator(locator_css, has_text=label).first
            item.get_by_role("button", name=f"Archive {label}").first.click()
            self.confirm_if_asked()
            self.wait_htmx()

        archive_in("projects", "tr[id^=project-]", project)
        archive_in("kpis", "section[id^=kpi-]", kpi)
        archive_in("structure", "li[id^=offer-]", names["offer"])
        archive_in("structure", "li[id^=solution-]", names["solution"])
        archive_in("structure", "li[id^=practice-]", names["practice"])
        self.page.goto(self.url("/s/consulting/?tab=structure"))
        expect(self.page.get_by_text(names["practice"])).to_have_count(0)
        self.check("smoke records archived (history kept)", True)
        if self.enrolled_secret:
            self.page.goto(self.url("/account/two-step/"))
            self.page.get_by_text("Replace authenticator").click()
            self.page.get_by_label("Current password").fill(password)
            self.page.get_by_role("button", name="Remove authenticator and sign out").click()
            self.page.wait_for_load_state("networkidle")
            self.check("temporary smoke-test authenticator removed", "/login/" in self.page.url)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshots", type=Path, default=None)
    parser.add_argument(
        "--keep", action="store_true", help="Do not archive smoke records or remove the TOTP device."
    )
    parser.add_argument("--headed", action="store_true")
    parser.add_argument(
        "--skip-if-enrolled",
        action="store_true",
        help="Exit successfully (skipped) when the account already has a TOTP device and no secret is given.",
    )
    args = parser.parse_args()
    base = os.environ.get("SMOKE_BASE_URL", "http://localhost:8000")
    email = os.environ["SMOKE_EMAIL"]
    password = os.environ["SMOKE_PASSWORD"]
    executable = os.environ.get("SMOKE_CHROMIUM")
    with sync_playwright() as playwright:
        launch = {"headless": not args.headed}
        if executable:
            launch["executable_path"] = executable
        browser = playwright.chromium.launch(**launch)
        context = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light")
        # Synthetic records are hidden from the admin UI; this session opts back in to verify them.
        context.add_cookies([{"name": "vitalos_show_synthetic", "value": "1", "url": base}])
        page = context.new_page()
        console_errors: list[str] = []
        page.on(
            "console",
            lambda msg: console_errors.append(f"{page.url}: {msg.text}") if msg.type == "error" else None,
        )
        smoke = Smoke(page, base, args.screenshots, skip_if_enrolled=args.skip_if_enrolled)
        try:
            smoke.login(email, password)
            smoke.homepage()
            smoke.dashboards()
            names = smoke.create_structure()
            project = smoke.create_project()
            kpi = smoke.create_kpi()
            smoke.search()
            smoke.activity_and_history(names)
            smoke.tour()
            smoke.use_template()
            csp = [error for error in console_errors if "Content Security Policy" in error]
            smoke.check("no CSP violations in the browser console", not csp, "; ".join(csp)[:300])
            if not args.keep:
                smoke.cleanup(names, project, kpi, password)
        except SmokeSkipped as reason:
            print(f"SKIPPED: {reason}. Run with SMOKE_TOTP_SECRET to test an enrolled account.")
            return 0
        except Exception as exc:  # noqa: BLE001 - report and exit non-zero
            traceback.print_exc()
            try:
                smoke.shot("zz-failure", full_page=False)
            except Exception as shot_error:  # noqa: BLE001 - best effort
                print(f"Could not capture failure screenshot: {shot_error}", file=sys.stderr)
            print(f"Smoke test failed at {page.url}: {exc}", file=sys.stderr)
            return 1
        finally:
            summary = {"base_url": base, "checks": smoke.results}
            if args.screenshots:
                args.screenshots.mkdir(parents=True, exist_ok=True)
                (args.screenshots / "smoke-results.json").write_text(json.dumps(summary, indent=2))
            browser.close()
    print(f"All {len(smoke.results)} smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
