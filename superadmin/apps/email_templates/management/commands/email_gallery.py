"""Render every email into a browsable gallery (docs/email/README.md).

    manage.py email_gallery --out ../docs/email/gallery [--import DIR ...]

Writes, per email, ``emails/<slug>.html`` (images from ``assets/``), ``emails/<slug>.dark.html`` (dark
theme forced) and ``emails/<slug>.txt``; plus ``manifest.json`` and ``index.html``, filterable by repo,
category and state. Library templates render with fictional sample values; code-defined emails render
from fictional records created inside a transaction that is rolled back, so nothing is stored or sent.
``--import`` adds emails rendered elsewhere (the website, Askbridge, Answerd): a directory with a
``manifest.json`` of ``{slug, name, repo, category, state, subject, html, text}``.
"""

from __future__ import annotations

import base64
import html
import json
import shutil
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from django.core.management.base import BaseCommand
from django.db import transaction
from django.test.utils import override_settings
from django.utils import timezone

from apps.mailer import layout

SAMPLE = {
    "first_name": "Alex",
    "last_name": "Example",
    "full_name": "Alex Example",
    "organisation": "Example Care Group",
    "email": "alex@example-care.example",
    "role": "Operations Director",
    "reference": "VIT-EXAMPLE-01",
    "service": "Engineering",
    "intent": "a new website",
    "timeframe": "within 3 months",
    "goal": "We need a new website for our care homes by spring, with a booking form for visits.",
    "budget_range": "Not provided",
    "offer": "Website rebuild",
    "source_page": "https://vitalos.co.uk/contact",
    "received_at": "Mon 26 Oct 2026, 09:12",
    "sender_name": "Sam Example",
    "sender_title": "Delivery Lead",
    "sender_email": "sam.example@vitalos.co.uk",
    "meeting_link": "https://vitalos.co.uk/contact?meeting=example",
    "meeting_time": "Thursday 29 October 2026, 10:00",
    "previous_meeting_time": "Wednesday 28 October 2026, 14:00",
    "reschedule_link": "https://vitalos.co.uk/contact?reschedule=example",
    "proposal_link": "https://vitalos.co.uk/contact?proposal=example",
    "document_link": "https://vitalos.co.uk/contact?document=example",
    "action_link": "https://vitalos.co.uk/contact?action=example",
    "link_expiry": "in 7 days",
    "project_name": "Example Care Group website",
    "milestone_name": "Design sign-off",
    "status_summary": "Designs are ready for review.",
    "next_steps": "Review the designs by Friday.",
    "change_reference": "CR-EXAMPLE-01",
    "case_study_title": "An example project",
    "case_study_link": "https://vitalos.co.uk",
    "invoice_number": "INV-EXAMPLE-01",
    "quote_number": "Q-EXAMPLE-01",
    "amount": "£1,000.00",
    "due_date": "30 November 2026",
    "days_overdue": "7",
    "renewal_date": "1 January 2027",
    "event_name": "Example event",
    "event_date": "Thursday 12 November 2026, 18:00",
    "event_link": "https://vitalos.co.uk",
    "assignee_name": "Sam",
    "task_name": "Send the proposal",
    "task_due": "today",
    "admin_link": "https://admin.vitalos.co.uk",
}
RECIPIENT = "alex@example-care.example"
BASE_URL = "https://admin.vitalos.co.uk"


def _entry(slug, name, category, subject, rendered, *, repo="vitalos-platform", kind="", source="code"):
    return {
        "slug": slug,
        "name": name,
        "repo": repo,
        "category": category,
        "state": "layout",
        "kind": kind,
        "source": source,
        "subject": subject,
        "html_source": rendered.html,
        "text_source": rendered.text,
    }


def library_entries() -> list[dict]:
    from apps.email_templates.rendering import render_content
    from apps.email_templates.services import load_seed

    entries = []
    for item in load_seed():
        rendered = render_content(item, SAMPLE, key=item["key"], recipient=RECIPIENT)
        entries.append(
            _entry(
                f"library-{item['key']}",
                item["name"],
                item["category"],
                rendered.subject,
                rendered.email,
                kind=item.get("kind", ""),
                source="library",
            )
        )
    return entries


def _code_entries() -> list[dict]:
    from apps.accounts.services import password_email
    from apps.careers import alerts as careers
    from apps.careers import config as careers_config
    from apps.enquiries import notifications, services
    from apps.enquiries.models import Enquiry, Message, OutboundNotification
    from apps.portal.services import invitation_email
    from apps.relay import emails as relay

    render = layout.render_email
    entries = []
    now = timezone.now()

    people = [
        ("Alex Example", "alex@example-care.example", "Website rebuild for our care homes"),
        ("Sam Example", "sam@example-housing.example", "Support for our tenant portal"),
        ("Jo Example", "jo@example-school.example", "Data dashboard for governors"),
    ]
    enquiries = []
    for name, address, subject in people:
        enquiry = services.create_enquiry(
            subject=subject,
            from_name=name,
            from_email=address,
            to_email="support@vitalos.co.uk",
            source=Enquiry.Source.EMAIL,
            snippet="Example message text for the gallery.",
        )
        Message.objects.create(
            enquiry=enquiry,
            direction=Message.Direction.INBOUND,
            message_id_header=f"<gallery-{uuid.uuid4()}@example.invalid>",
            from_name=name,
            from_email=address,
            subject=subject,
            text_body=f"Hello, this is {name}. We would like to talk about {subject.lower()}. "
            "Could you tell us how you would approach it and what you need from us?",
            provider=Message.Provider.LOG,
        )
        enquiries.append(enquiry)
    events = ["new_enquiry", "customer_reply", "assigned_to_me"]
    rows = [
        OutboundNotification(enquiry=enquiry, event=event, mode="instant", created_at=now)
        for enquiry, event in zip(enquiries, events, strict=True)
    ]
    for slug, name, chosen, digest in (
        ("enquiry-alert-single", "Enquiry alert: one update", rows[:1], False),
        ("enquiry-alert-several", "Enquiry alert: several updates", rows, False),
        ("enquiry-digest", "Enquiries daily digest", rows, True),
    ):
        subject, doc = notifications.build_email(chosen, digest=digest, now=now)
        entries.append(_entry(slug, name, "enquiries-system", subject, render(doc)))

    subject = services.reply_subject(enquiries[0])
    reply = services.reply_document(
        subject,
        "Hi Alex,\n\nThanks for the details. We can start with a short discovery call next week.\n\n"
        "Would Tuesday or Wednesday morning suit you?",
        "Kind regards,\nVitalos Support\nVitalos Technologies Limited\nhttps://www.vitalos.co.uk",
    )
    entries.append(
        _entry("inbox-reply", "Inbox reply (correspondence)", "enquiries-system", subject, render(reply))
    )

    subject, doc = password_email(f"{BASE_URL}/account/set-password/EXAMPLE/example-token/")
    entries.append(_entry("account-password-link", "Set your password", "account", subject, render(doc)))

    member = SimpleNamespace(
        organisation=SimpleNamespace(name="Example Ledger Ltd (synthetic)"),
        get_role_display=lambda: "Contributor",
    )
    subject, doc = invitation_email(member, "https://portal.vitalos.co.uk/invitation/EXAMPLE-TOKEN/")
    entries.append(_entry("portal-invitation", "Client portal invitation", "portal", subject, render(doc)))

    applications = [
        SimpleNamespace(pk=uuid.uuid4(), name="Alex Example", created_at=now, duplicate_of_id=None),
        SimpleNamespace(pk=uuid.uuid4(), name="Sam Example", created_at=now, duplicate_of_id=1),
    ]
    subject, doc = careers.alert_email(applications, "Example role")
    entries.append(
        _entry("careers-hiring-alert", "Careers hiring-team alert", "careers", subject, render(doc))
    )
    for kind in careers_config.EMAIL_KINDS:
        email = careers.candidate_email(None, kind)
        entries.append(
            _entry(
                f"careers-candidate-{kind}",
                f"Careers candidate: {kind}",
                "careers",
                email["subject"],
                render(email["doc"]),
            )
        )

    conversation = str(uuid.uuid4())
    waiting = (now - timedelta(minutes=12)).isoformat()
    base = {
        "conversationId": conversation,
        "displayName": "Alex Example",
        "pagePath": "/services/engineering",
        "requestedAt": waiting,
        "trigger": "visitor_asked",
        "lastVisitorMessage": "Can someone tell me how long a website rebuild takes?",
    }
    samples = {
        "handoff_requested": (base, {}),
        "reminder": ({**base, "minutesWaiting": 12, "nth": 1}, {}),
        "visitor_replied": (base, {"assigned": True}),
        "no_answer": ({**base, "question": "Do you work with schools?"}, {}),
        "digest": (
            {
                "yesterday": {
                    "conversations": 14,
                    "aiResolved": 10,
                    "handoffs": 4,
                    "handoffRate": 0.29,
                    "helpful": 8,
                    "notHelpful": 1,
                },
                "waitingNow": 1,
                "openGaps": 2,
                "topGaps": [{"question": "Do you work with schools?", "count": 3}],
            },
            {},
        ),
        "token_cap": ({"day": "2026-10-26", "tokensUsed": 200000, "cap": 200000}, {}),
        "faq_attention": ({"held": 2, "consecutiveFailures": 1}, {}),
    }
    from apps.relay import models as relay_models

    for kind_name, (data, options) in samples.items():
        kind = getattr(relay_models, kind_name.upper(), kind_name)
        alert = relay.build(kind, data, **options)
        entries.append(
            _entry(
                f"relay-{kind_name.replace('_', '-')}",
                f"Site assistant (legacy) alert: {kind_name.replace('_', ' ')}",
                "relay",
                alert.subject,
                render(alert.document),
            )
        )
    return entries


def code_entries() -> list[dict]:
    with transaction.atomic():
        entries = _code_entries()
        transaction.set_rollback(True)
    return entries


def _assets(out: Path) -> dict[str, str]:
    folder = out / "assets"
    folder.mkdir(parents=True, exist_ok=True)
    mapping = {}
    for image in layout.spec()["images"].values():
        (folder / image["filename"]).write_bytes(base64.b64decode(image["base64"]))
        mapping[image["contentId"]] = f"../assets/{image['filename']}"
    return mapping


def _with_assets(source: str, mapping: dict[str, str]) -> str:
    for content_id, path in mapping.items():
        source = source.replace(f"cid:{content_id}", path)
    return source


def _plain_page(subject: str, text: str) -> str:
    """A plain-text email as a mail client shows it, for emails with no HTML part."""
    return (
        '<!doctype html><html lang="en-GB"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(subject)}</title></head>"
        '<body style="margin:0;padding:16px;background:#fff;color:#111;font:15px/1.5 -apple-system,'
        '\'Segoe UI\',Roboto,Arial,sans-serif"><pre style="white-space:pre-wrap;font:inherit;margin:0">'
        f"{html.escape(text)}</pre></body></html>"
    )


def _imported(directory: Path) -> list[dict]:
    entries = []
    for item in json.loads((directory / "manifest.json").read_text(encoding="utf-8")):
        text = (directory / item["text"]).read_text(encoding="utf-8")
        page = (directory / item["html"]).read_text(encoding="utf-8") if item.get("html") else ""
        entries.append(
            {
                **{
                    key: item.get(key, "") for key in ("slug", "name", "repo", "category", "state", "subject")
                },
                "kind": item.get("kind", ""),
                "source": "imported",
                "html_source": page or _plain_page(item.get("subject", ""), text),
                "text_source": text,
            }
        )
    return entries


def write_gallery(out: Path, entries: list[dict]) -> list[dict]:
    emails = out / "emails"
    if emails.exists():
        shutil.rmtree(emails)
    emails.mkdir(parents=True)
    mapping = _assets(out)
    manifest = []
    for entry in entries:
        page = _with_assets(entry.pop("html_source"), mapping)
        text = entry.pop("text_source")
        slug = entry["slug"]
        (emails / f"{slug}.html").write_text(page, encoding="utf-8")
        (emails / f"{slug}.dark.html").write_text(layout.force_theme(page, "dark"), encoding="utf-8")
        (emails / f"{slug}.txt").write_text(text, encoding="utf-8")
        manifest.append(
            {
                **entry,
                "html": f"emails/{slug}.html",
                "dark": f"emails/{slug}.dark.html",
                "text": f"emails/{slug}.txt",
                "bytes": len(page.encode()),
            }
        )
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "index.html").write_text(_index(manifest), encoding="utf-8")
    return manifest


def _options(manifest: list[dict], key: str) -> str:
    values = sorted({entry[key] for entry in manifest if entry[key]})
    return "".join(f'<option value="{html.escape(v)}">{html.escape(v)}</option>' for v in values)


def _index(manifest: list[dict]) -> str:
    cards = []
    for entry in manifest:
        e = {key: html.escape(str(value)) for key, value in entry.items()}
        cards.append(
            f'<li class="card" data-repo="{e["repo"]}" data-category="{e["category"]}" data-state="{e["state"]}">'
            f'<img src="shots/{e["slug"]}.light.600.png" alt="" loading="lazy" onerror="this.remove()">'
            f'<div class="body"><p class="name">{e["name"]}</p><p class="subject">{e["subject"]}</p>'
            f'<p class="tags"><span>{e["repo"]}</span><span>{e["category"]}</span><span>{e["state"]}</span></p>'
            f'<p class="links"><a href="{e["html"]}">Light</a><a href="{e["dark"]}">Dark</a>'
            f'<a href="{e["text"]}">Plain text</a></p></div></li>'
        )
    return f"""<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vitalos email gallery</title>
<style>
:root{{color-scheme:light dark;--bg:#f5f7fa;--card:#fff;--text:#0f172a;--muted:#475569;--rule:#d9e0e8;--link:#1d4ed8}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b1220;--card:#111a2e;--text:#f5f7fa;--muted:#cbd5e1;--rule:#334155;--link:#bfdbfe}}}}
body{{margin:0;padding:24px 16px;background:var(--bg);color:var(--text);font:16px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}}
h1{{margin:0 0 4px;font-size:24px}} .muted{{color:var(--muted);margin:0 0 16px}}
form{{display:flex;flex-wrap:wrap;gap:12px;margin:0 0 20px}} label{{display:flex;flex-direction:column;font-size:14px;color:var(--muted)}}
select{{font:inherit;padding:6px 8px;border:1px solid var(--rule);border-radius:6px;background:var(--card);color:var(--text)}}
ul{{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}}
.card{{background:var(--card);border:1px solid var(--rule);border-radius:12px;overflow:hidden}}
.card img{{display:block;width:100%;height:220px;object-fit:cover;object-position:top;border-bottom:1px solid var(--rule)}}
.body{{padding:12px 14px}} .name{{margin:0;font-weight:700}} .subject{{margin:2px 0 8px;color:var(--muted);font-size:14px}}
.tags span{{display:inline-block;margin:0 6px 6px 0;padding:2px 8px;border:1px solid var(--rule);border-radius:999px;font-size:13px}}
.links a{{margin-right:12px;color:var(--link)}} .hidden{{display:none}}
</style></head><body>
<h1>Vitalos email gallery</h1>
<p class="muted"><span id="count">{len(manifest)}</span> emails. Fictional data only. Generated by <code>manage.py email_gallery</code>.</p>
<form><label>Repository<select data-filter="repo"><option value="">All</option>{_options(manifest, "repo")}</select></label>
<label>Category<select data-filter="category"><option value="">All</option>{_options(manifest, "category")}</select></label>
<label>State<select data-filter="state"><option value="">All</option>{_options(manifest, "state")}</select></label></form>
<ul>{"".join(cards)}</ul>
<script>
const selects=[...document.querySelectorAll("select[data-filter]")];
function apply(){{let n=0;for(const card of document.querySelectorAll(".card")){{
const show=selects.every(s=>!s.value||card.dataset[s.dataset.filter]===s.value);card.classList.toggle("hidden",!show);if(show)n++;}}
document.getElementById("count").textContent=n;}}
selects.forEach(s=>s.addEventListener("change",apply));
</script></body></html>
"""


class Command(BaseCommand):
    help = "Render every email (library templates and code-defined emails) into a static gallery."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="../docs/email/gallery")
        parser.add_argument(
            "--import", dest="imports", action="append", default=[], help="Directory with manifest.json"
        )
        parser.add_argument(
            "--imports-only", action="store_true", help="Only the imported emails (e.g. the baseline)."
        )

    def handle(self, *args, **options):
        # Links in the gallery (unsubscribe, buttons) use the production origin, for this command only.
        with override_settings(APP_BASE_URL=BASE_URL):
            self._handle(options)

    def _handle(self, options):
        out = Path(options["out"]).resolve()
        entries = [] if options["imports_only"] else library_entries() + code_entries()
        for directory in options["imports"]:
            entries += _imported(Path(directory))
        slugs = [entry["slug"] for entry in entries]
        duplicates = sorted({slug for slug in slugs if slugs.count(slug) > 1})
        if duplicates:
            raise SystemExit(f"Duplicate gallery slugs: {duplicates}")
        manifest = write_gallery(out, entries)
        largest = max(manifest, key=lambda entry: entry["bytes"])
        self.stdout.write(
            f"{len(manifest)} emails written to {out} (largest {largest['slug']}: {largest['bytes']} bytes)."
        )
