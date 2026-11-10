"""Relay forms. They validate what Django sends; the website validates again (zod) and decides."""

from decimal import Decimal
from urllib.parse import urlsplit

from django import forms
from django.core.exceptions import ValidationError

INPUT = (
    "block w-full rounded-[2px] border border-line-strong bg-white px-3 py-2 text-sm text-midnight "
    "placeholder:text-slate-500 focus:border-cobalt-600 focus:outline-none focus:ring-2 focus:ring-cobalt-600/30 "
    "dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-400"
)
CHECKBOX = "h-[18px] w-[18px] accent-cobalt-600"
MAX_TEXT = 4000

DOCUMENT_TYPES = (
    ("faq", "FAQ"),
    ("guide", "Guide"),
    ("offer", "Offer"),
    ("solution", "Solution"),
    ("practice", "Practice"),
    ("industry", "Industry"),
    ("page", "Page"),
    ("policy", "Policy"),
    ("company", "Company"),
)
DAYS = (
    ("1", "Monday"),
    ("2", "Tuesday"),
    ("3", "Wednesday"),
    ("4", "Thursday"),
    ("5", "Friday"),
    ("6", "Saturday"),
    ("7", "Sunday"),
)


class _Styled:
    def _style(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", CHECKBOX)
            elif not isinstance(widget, forms.CheckboxSelectMultiple):
                widget.attrs.setdefault("class", INPUT)


class ReplyForm(_Styled, forms.Form):
    text = forms.CharField(max_length=MAX_TEXT, strip=True, widget=forms.Textarea(attrs={"rows": 3}))
    client_message_id = forms.UUIDField(widget=forms.HiddenInput)
    email_if_away = forms.BooleanField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class NoteForm(_Styled, forms.Form):
    text = forms.CharField(max_length=MAX_TEXT, strip=True, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class KnowledgeForm(_Styled, forms.Form):
    title = forms.CharField(max_length=300)
    url = forms.URLField(max_length=500, required=False, assume_scheme="https", label="URL")
    type = forms.ChoiceField(choices=DOCUMENT_TYPES, initial="faq")
    owner = forms.CharField(max_length=120, required=False)
    review_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    body_md = forms.CharField(
        max_length=60000,
        label="Answer (Markdown)",
        widget=forms.Textarea(attrs={"rows": 14, "spellcheck": "true"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()
        self.fields["body_md"].widget.attrs["class"] += " font-mono"

    def clean_url(self):
        url = self.cleaned_data["url"]
        if url and urlsplit(url).scheme != "https":
            raise ValidationError("Use an https link.")
        return url

    def api_fields(self) -> dict:
        data = self.cleaned_data
        return {
            "title": data["title"],
            "url": data["url"] or None,
            "type": data["type"],
            "owner": data["owner"] or None,
            "reviewDate": data["review_date"].isoformat() if data["review_date"] else None,
            "bodyMd": data["body_md"],
        }

    @classmethod
    def initial_from(cls, document: dict) -> dict:
        return {
            "title": document.get("title") or "",
            "url": document.get("url") or "",
            "type": document.get("type") or "faq",
            "owner": document.get("owner") or "",
            "review_date": (document.get("reviewDate") or "")[:10] or None,
            "body_md": document.get("bodyMd") or "",
        }


class RetrievalTestForm(_Styled, forms.Form):
    question = forms.CharField(max_length=300, label="Test question")
    page_path = forms.CharField(max_length=300, required=False, label="Page (optional)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


def _origin(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme != "https" or not parts.netloc or parts.path not in ("", "/") or parts.query:
        raise ValidationError(f"{value} is not an https origin such as https://www.vitalos.co.uk.")
    return f"https://{parts.netloc.lower()}"


class SettingsForm(_Styled, forms.Form):
    """The editable part of RelaySettings (API.md). Timezone stays Europe/London."""

    ai_enabled = forms.BooleanField(required=False, label="AI answers visitors")
    model = forms.CharField(max_length=80)
    days = forms.MultipleChoiceField(choices=DAYS, widget=forms.CheckboxSelectMultiple, label="Business days")
    start = forms.RegexField(regex=r"^([01]\d|2[0-3]):[0-5]\d$", max_length=5, label="Opens")
    end = forms.RegexField(regex=r"^([01]\d|2[0-3]):[0-5]\d$", max_length=5, label="Closes")
    out_of_hours_text = forms.CharField(
        max_length=1000, widget=forms.Textarea(attrs={"rows": 3}), label="Out-of-hours text"
    )
    reminder_minutes = forms.IntegerField(min_value=1, max_value=240, label="First reminder after (minutes)")
    second_reminder_minutes = forms.IntegerField(
        min_value=1, max_value=1440, label="Second reminder after (minutes)"
    )
    email_snippet = forms.BooleanField(required=False, label="Include the visitor's words in alert emails")
    visitor_emails_enabled = forms.BooleanField(
        required=False, label="Email replies to visitors who have left"
    )
    greeting = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 2}))
    question_1 = forms.CharField(max_length=120, label="Suggested question 1")
    question_2 = forms.CharField(max_length=120, label="Suggested question 2")
    question_3 = forms.CharField(max_length=120, label="Suggested question 3")
    question_4 = forms.CharField(max_length=120, label="Suggested question 4")
    confidence_threshold = forms.DecimalField(
        min_value=Decimal("0"), max_value=Decimal("1"), decimal_places=2, label="Answer threshold"
    )
    daily_token_cap = forms.IntegerField(min_value=0, max_value=1_000_000_000, label="Daily token cap")
    no_contact_days = forms.IntegerField(
        min_value=1, max_value=3650, label="Keep conversations without contact details (days)"
    )
    with_contact_days = forms.IntegerField(
        min_value=1, max_value=3650, label="Keep conversations with contact details (days)"
    )
    allowed_origins = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}), label="Allowed origins (one per line)", required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()

    def clean_allowed_origins(self):
        lines = [line for line in self.cleaned_data["allowed_origins"].splitlines() if line.strip()]
        origins = []
        for line in lines[:20]:
            origin = _origin(line)
            if origin not in origins:
                origins.append(origin)
        return origins

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("start") and cleaned.get("end") and cleaned["start"] >= cleaned["end"]:
            self.add_error("end", "Closing time must be after opening time.")
        first, second = cleaned.get("reminder_minutes"), cleaned.get("second_reminder_minutes")
        if first and second and second <= first:
            self.add_error("second_reminder_minutes", "The second reminder must come after the first.")
        return cleaned

    @classmethod
    def initial_from(cls, relay_settings: dict) -> dict:
        hours = relay_settings.get("businessHours") or {}
        retention = relay_settings.get("retention") or {}
        questions = list(relay_settings.get("suggestedQuestions") or []) + ["", "", "", ""]
        return {
            "ai_enabled": bool(relay_settings.get("aiEnabled")),
            "model": relay_settings.get("model") or "",
            "days": [str(day) for day in hours.get("days") or []],
            "start": hours.get("start") or "09:00",
            "end": hours.get("end") or "17:30",
            "out_of_hours_text": relay_settings.get("outOfHoursText") or "",
            "reminder_minutes": relay_settings.get("reminderMinutes"),
            "second_reminder_minutes": relay_settings.get("secondReminderMinutes"),
            "email_snippet": bool(relay_settings.get("emailSnippet")),
            "visitor_emails_enabled": bool(relay_settings.get("visitorEmailsEnabled")),
            "greeting": relay_settings.get("greeting") or "",
            "question_1": questions[0],
            "question_2": questions[1],
            "question_3": questions[2],
            "question_4": questions[3],
            "confidence_threshold": relay_settings.get("confidenceThreshold"),
            "daily_token_cap": relay_settings.get("dailyTokenCap"),
            "no_contact_days": retention.get("noContactDays"),
            "with_contact_days": retention.get("withContactDays"),
            "allowed_origins": "\n".join(relay_settings.get("allowedOrigins") or []),
        }

    def api_changes(self) -> dict:
        data = self.cleaned_data
        return {
            "aiEnabled": data["ai_enabled"],
            "model": data["model"],
            "businessHours": {
                "days": sorted(int(day) for day in data["days"]),
                "start": data["start"],
                "end": data["end"],
                "timezone": "Europe/London",
            },
            "outOfHoursText": data["out_of_hours_text"],
            "reminderMinutes": data["reminder_minutes"],
            "secondReminderMinutes": data["second_reminder_minutes"],
            "emailSnippet": data["email_snippet"],
            "visitorEmailsEnabled": data["visitor_emails_enabled"],
            "greeting": data["greeting"],
            "suggestedQuestions": [data[f"question_{n}"] for n in range(1, 5)],
            "confidenceThreshold": float(data["confidence_threshold"]),
            "dailyTokenCap": data["daily_token_cap"],
            "retention": {
                "noContactDays": data["no_contact_days"],
                "withContactDays": data["with_contact_days"],
            },
            "allowedOrigins": data["allowed_origins"],
        }
