"""Accessibility check: axe-core (WCAG 2.2 AA tags) over the Super Admin pages, light and dark themes.

Fails (exit 1) on any serious or critical violation. Used by CI against the production image and
runnable locally against `manage.py runserver`.

    python e2e/a11y.py --base http://localhost:8000 --axe path/to/axe.min.js \
        --session <session key of a signed-in, second-factor-verified user> \
        [--inbound-secret <INBOUND_WEBHOOK_SECRET>]   # first posts sample mail so the inbox has data

Relay pages are checked when Relay is configured; run the server with RELAY_CLIENT=fake (sample data,
never in production) to include them. Where Relay is off they answer 404 and are skipped, not failed.

The page CSP blocks injected scripts, so the browser context bypasses CSP for axe only.
"""

import argparse
import hashlib
import hmac
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES = [
    "/login/",
    "/",
    "/enquiries/",
    "/enquiries/VIT-0001/",
    "/mail/templates/",
    "/mail/templates/1/",
    "/mail/templates/1/versions/",
    "/mail/templates/1/use/",
    "/activity/",
    "/audit/",
    "/service-lines/",
    "/s/consulting/",
    "/team/",
    "/architecture/",
    "/settings/email/",
    "/settings/notifications/",
    "/settings/users/",
    "/help/",
    "/system/health/",
    "/notifications/",
    "/notifications/attention/",
    "/insights/posts/",
    "/insights/authors/",
    "/insights/topics/",
    "/insights/settings/",
    "/careers/roles/",
    "/careers/applications/",
    "/careers/settings/",
    "/content/sync/",
    "/products/",
    "/products/askbridge/",
    "/settings/content/",
    "/account/",
    "/account/password/",
    "/account/two-step/",
]
# Relay (apps/relay). Ids are the fixed sample conversation and team answer in apps/relay/fake.py.
RELAY_PAGES = [
    "/relay/inbox/",
    "/relay/inbox/4f2a9c1e-5b7d-4e8a-9c3f-1a2b3c4d5e01/",
    "/relay/knowledge/",
    "/relay/knowledge/?view=confirm",
    "/relay/knowledge/9d0c1b2a-3e4f-4a5b-8c6d-7e8f9a0b1c11/",
    "/relay/knowledge/new/",
    "/relay/insights/",
    "/relay/settings/",
    "/relay/me/prefs/",
]
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "eml"


def post_sample_mail(base: str, secret: str) -> None:
    """Send fixture mail through the signed inbound endpoint (the same path as the Email Worker)."""
    for name in ("plain.eml", "html.eml"):
        body = (FIXTURES / name).read_bytes()
        stamp = str(int(time.time()))
        signature = hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
        request = urllib.request.Request(  # noqa: S310 - local test server
            f"{base}/api/inbound/email",
            data=body,
            method="POST",
            headers={
                "Content-Type": "message/rfc822",
                "X-Vitalos-Timestamp": stamp,
                "X-Vitalos-Signature": signature,
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310  # nosec B310
            print(f"inbound {name}: HTTP {response.status} {response.read().decode()}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--axe", required=True, help="Path to axe.min.js (axe-core)")
    parser.add_argument("--session", required=True, help="vsa_session cookie value")
    parser.add_argument("--inbound-secret", default="")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    if args.inbound_secret:
        post_sample_mail(base, args.inbound_secret)

    failures = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for scheme in ("light", "dark"):
            context = browser.new_context(
                viewport={"width": 1440, "height": 900}, color_scheme=scheme, bypass_csp=True
            )
            page = context.new_page()
            for path in PAGES + RELAY_PAGES:
                context.clear_cookies()
                if path != "/login/":
                    context.add_cookies([{"name": "vsa_session", "value": args.session, "url": base}])
                response = page.goto(base + path)
                page.wait_for_load_state("networkidle")
                if path in RELAY_PAGES and response is not None and response.status == 404:
                    print(f"skip {scheme:5} {path}: Relay is not configured on this server")
                    continue
                if response is None or response.status >= 400:
                    print(f"FAIL {scheme:5} {path}: HTTP {response.status if response else 'no response'}")
                    failures += 1
                    continue
                page.add_script_tag(path=args.axe)
                result = page.evaluate(
                    "async (tags) => await axe.run(document, {runOnly: {type: 'tag', values: tags}})", TAGS
                )
                serious = [v for v in result["violations"] if v["impact"] in ("serious", "critical")]
                print(
                    f"{'FAIL' if serious else 'ok  '} {scheme:5} {path} ({len(result['violations'])} issue(s))"
                )
                for violation in result["violations"]:
                    targets = [", ".join(node["target"]) for node in violation["nodes"][:3]]
                    print(
                        f"     [{violation['impact']}] {violation['id']}: {violation['help']} e.g. {targets}"
                    )
                failures += len(serious)
            context.close()
        browser.close()
    print(f"Serious or critical accessibility violations: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
