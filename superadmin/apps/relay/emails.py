"""Relay alert emails on the shared Vitalos layout (ADR-030), one family for every alert type.

The board (docs/relay/reference/relay/Email-Alert.*) is approximated with the layout's own blocks:
the eyebrow is a section title, the cobalt full stop is a plain full stop, and "Manage notifications"
is a pasted link in the footer notice. layout.py is generated against golden fixtures and is not edited.
Every email has a plain-text part. The deep link never carries a login token.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.urls import reverse

from apps.email_templates.rendering import company_footer
from apps.mailer import layout
from apps.mailer.messages import build_message

from . import presenters
from .models import DIGEST, FAQ_ATTENTION, HANDOFF_REQUESTED, NO_ANSWER, REMINDER, TOKEN_CAP, VISITOR_REPLIED

SIGN_IN_NOTICE = (
    "The link opens the conversation after you sign in to the super admin dashboard. "
    "It never signs you in on its own."
)
LIST_NOTICE = (
    "You get this because you are on the site assistant notification list. Manage notifications: {url}"
)
PER_CONVERSATION = "VITALOS SITE ASSISTANT · ONE EMAIL PER CONVERSATION EVERY 10 MINUTES AT MOST"
PER_DAY = "VITALOS SITE ASSISTANT · ONE EMAIL A DAY AT MOST"
HEADERS = {"Auto-Submitted": "auto-generated", "X-Auto-Response-Suppress": "All"}


@dataclass(frozen=True)
class AlertEmail:
    subject: str
    document: dict


def deep_link(conversation_id: str) -> str:
    return f"{settings.APP_BASE_URL}/relay/inbox/{conversation_id}?ref=email"


def _prefs_url() -> str:
    return settings.APP_BASE_URL + reverse("relay:prefs")


def _footer(limit_line: str) -> dict:
    facts, social = company_footer()
    notice = "\n\n".join((SIGN_IN_NOTICE, LIST_NOTICE.format(url=_prefs_url()), limit_line))
    return {"notice": notice, "social": social, "company": facts}


def _quote(text: str | None) -> list[dict]:
    text = layout.clean_multiline(text)
    return [{"type": "quote", "text": f"“{text}”"}] if text else []


def _conversation_blocks(eyebrow, headline, sentence, quote, rows, conversation_id) -> list[dict]:
    link = deep_link(conversation_id)
    return [
        {"type": "section", "text": eyebrow},
        {"type": "heading", "text": headline},
        {"type": "text", "text": sentence, "tone": "muted"},
        *_quote(quote),
        {"type": "details", "rows": rows},
        {"type": "button", "label": "Open conversation", "url": link},
        {"type": "text", "text": f"Or paste this link: {link}", "tone": "muted"},
    ]


def _document(subject: str, preheader: str, blocks: list[dict], limit_line: str = PER_CONVERSATION) -> dict:
    return {
        "title": subject,
        "preheader": preheader,
        "headerLabel": "Site assistant",
        "blocks": blocks,
        "footer": _footer(limit_line),
    }


def handoff(data: dict) -> AlertEmail:
    name = data.get("displayName") or "A visitor"
    reason = presenters.trigger(data.get("trigger"))
    sentence = reason.sentence.format(first=presenters.first_name(name))
    subject = f"Site assistant (legacy): {name} needs a person"
    rows = [
        {"label": "Trigger", "value": reason.label},
        {"label": "Page", "value": data.get("pagePath") or "", "code": True, "missing": "Not recorded"},
        {"label": "Waiting since", "value": presenters.long_date(data.get("requestedAt"))},
    ]
    blocks = _conversation_blocks(
        "Site assistant · Needs a person",
        f"{name} is waiting for a reply.",
        sentence,
        data.get("lastVisitorMessage"),
        rows,
        data["conversationId"],
    )
    return AlertEmail(subject, _document(subject, sentence, blocks))


def reminder(data: dict) -> AlertEmail:
    name = data.get("displayName") or "A visitor"
    minutes = int(data.get("minutesWaiting") or 0)
    nth = data.get("nth") or 1
    subject = f"Site assistant (legacy): {name} is still waiting"
    sentence = (
        f"No one has joined after {minutes} minutes. This is reminder {nth}."
        if minutes
        else f"No one has joined yet. This is reminder {nth}."
    )
    rows = [
        {"label": "Trigger", "value": presenters.trigger(data.get("trigger")).label},
        {"label": "Page", "value": data.get("pagePath") or "", "code": True, "missing": "Not recorded"},
        {"label": "Waiting since", "value": presenters.long_date(data.get("requestedAt"))},
    ]
    blocks = _conversation_blocks(
        "Site assistant · Still waiting",
        f"{name} is still waiting for a reply.",
        sentence,
        data.get("lastVisitorMessage"),
        rows,
        data["conversationId"],
    )
    return AlertEmail(subject, _document(subject, sentence, blocks))


def visitor_replied(data: dict, *, assigned: bool) -> AlertEmail:
    name = data.get("displayName") or "A visitor"
    first = presenters.first_name(name)
    subject = f"Site assistant (legacy): {name} replied"
    sentence = (
        f"{first} sent a new message in your conversation."
        if assigned
        else f"{first} sent a new message in a live conversation."
    )
    rows = [{"label": "Page", "value": data.get("pagePath") or "", "code": True, "missing": "Not recorded"}]
    blocks = _conversation_blocks(
        "Site assistant · Visitor replied",
        f"{name} replied.",
        sentence,
        data.get("lastVisitorMessage"),
        rows,
        data["conversationId"],
    )
    return AlertEmail(subject, _document(subject, sentence, blocks))


def no_answer(data: dict) -> AlertEmail:
    subject = "Site assistant (legacy): a question had no answer"
    sentence = "The site assistant could not answer from published knowledge and did not hand off."
    rows = [{"label": "Page", "value": data.get("pagePath") or "", "code": True, "missing": "Not recorded"}]
    blocks = _conversation_blocks(
        "Site assistant · No answer",
        "The site assistant could not answer a question.",
        sentence,
        data.get("question"),
        rows,
        data["conversationId"],
    )
    return AlertEmail(subject, _document(subject, sentence, blocks))


def _percent(value) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return ""


def digest(data: dict) -> AlertEmail:
    subject = "Site assistant (legacy) daily digest"
    yesterday = data.get("yesterday") or {}
    rows = [
        {"label": "Conversations", "value": str(yesterday.get("conversations", 0))},
        {"label": "Answered by the AI", "value": str(yesterday.get("aiResolved", 0))},
        {"label": "Hand-offs", "value": str(yesterday.get("handoffs", 0))},
        {
            "label": "Hand-off rate",
            "value": _percent(yesterday.get("handoffRate")),
            "missing": "Not available",
        },
        {
            "label": "Helpful / not helpful",
            "value": f"{yesterday.get('helpful', 0)} / {yesterday.get('notHelpful', 0)}",
        },
        {"label": "Waiting now", "value": str(data.get("waitingNow", 0))},
        {"label": "Open gaps", "value": str(data.get("openGaps", 0))},
    ]
    gaps = [g for g in data.get("topGaps") or [] if isinstance(g, dict) and g.get("question")]
    blocks = [
        {"type": "section", "text": "Site assistant · Daily digest"},
        {"type": "heading", "text": "Yesterday on the site assistant."},
        {
            "type": "text",
            "text": "A summary of yesterday's conversations and the questions the site assistant could not answer.",
            "tone": "muted",
        },
        {"type": "details", "rows": rows},
    ]
    if gaps:
        lines = "\n".join(f"- {g['question']} ({g.get('count', 0)})" for g in gaps[:5])
        blocks += [{"type": "section", "text": "Top gaps"}, {"type": "text", "text": lines}]
    url = settings.APP_BASE_URL + reverse("relay:inbox")
    blocks += [
        {"type": "button", "label": "Open the site assistant", "url": url},
        {"type": "text", "text": f"Or paste this link: {url}", "tone": "muted"},
    ]
    return AlertEmail(subject, _document(subject, "Yesterday on the site assistant.", blocks, PER_DAY))


def token_cap(data: dict) -> AlertEmail:
    subject = "Site assistant (legacy): daily token cap reached"
    url = settings.APP_BASE_URL + reverse("relay:settings")
    blocks = [
        {"type": "section", "text": "Site assistant · Token cap"},
        {"type": "heading", "text": "The site assistant reached its daily token cap."},
        {
            "type": "text",
            "text": "Check the cap and today's use in site assistant settings.",
            "tone": "muted",
        },
        {
            "type": "details",
            "rows": [
                {"label": "Day", "value": str(data.get("day") or "")},
                {"label": "Tokens used", "value": f"{data.get('tokensUsed', 0):,}"},
                {"label": "Daily cap", "value": f"{data.get('cap', 0):,}"},
            ],
        },
        {"type": "button", "label": "Open site assistant settings", "url": url},
    ]
    return AlertEmail(
        subject, _document(subject, "The site assistant reached its daily token cap.", blocks, PER_DAY)
    )


def faq_attention(data: dict) -> AlertEmail:
    subject = "Site assistant (legacy): Master FAQ sync needs attention"
    url = settings.APP_BASE_URL + reverse("relay:knowledge") + "?view=held"
    blocks = [
        {"type": "section", "text": "Site assistant · Master FAQ"},
        {"type": "heading", "text": "The Master FAQ sync needs attention."},
        {
            "type": "text",
            "text": "Held entries are not used by the site assistant until they are fixed in Notion.",
            "tone": "muted",
        },
        {
            "type": "details",
            "rows": [
                {"label": "Held entries", "value": str(data.get("held", 0))},
                {"label": "Failed runs in a row", "value": str(data.get("consecutiveFailures", 0))},
            ],
        },
        {"type": "button", "label": "Open Knowledge", "url": url},
    ]
    return AlertEmail(subject, _document(subject, "The Master FAQ sync needs attention.", blocks, PER_DAY))


BUILDERS = {
    HANDOFF_REQUESTED: handoff,
    REMINDER: reminder,
    NO_ANSWER: no_answer,
    DIGEST: digest,
    TOKEN_CAP: token_cap,
    FAQ_ATTENTION: faq_attention,
}


def build(kind: str, data: dict, **options) -> AlertEmail:
    if kind == VISITOR_REPLIED:
        return visitor_replied(data, assigned=options.get("assigned", False))
    return BUILDERS[kind](data)


def send(alert: AlertEmail, recipient: str) -> None:
    rendered = layout.render_email(alert.document)
    message = build_message(
        rendered,
        subject=layout.clean_line(alert.subject)[:200],
        to=[recipient],
        from_email=settings.RELAY_EMAIL_FROM,
        headers=dict(HEADERS),
    )
    message.send(fail_silently=False)
