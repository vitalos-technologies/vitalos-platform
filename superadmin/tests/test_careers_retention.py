"""Recruitment data retention and the upload purge (brief section 9, ADR-041)."""

import io
import json
import uuid
from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management import call_command
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.careers import retention, services
from apps.careers.models import Application, Role, RoleStatus, UploadTicket
from apps.content_sync import render
from apps.content_sync.models import TickState
from apps.insights.models import Author, Post, PostStatus

from .content_helpers import configure, make_role, ok_render, pdf_bytes

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _setup(settings, monkeypatch):
    configure(settings, targets=())
    monkeypatch.setattr(render, "render", ok_render)


def _application(role, *, stage="rejected", decided_days_ago=None, name="Example Candidate"):
    application = Application.objects.create(
        role=role,
        name=name,
        email=f"{uuid.uuid4().hex[:6]}@example.test",
        right_to_work="yes",
        consent_at=timezone.now(),
        source="role_page",
        submission_id=uuid.uuid4(),
        stage=stage,
        decided_at=timezone.now() - timedelta(days=decided_days_ago)
        if decided_days_ago is not None
        else None,
    )
    key = f"applications/{application.pk}/cv.pdf"
    storages["careers_cvs"].save(key, ContentFile(pdf_bytes()))
    Application.objects.filter(pk=application.pk).update(cv_path=key)
    return Application.objects.get(pk=application.pk)


@pytest.fixture
def dataset(superadmin):
    old_role = make_role("Example old role (fixture)", actor=superadmin, status="closed")
    Role.objects.filter(pk=old_role.pk).update(closed_at=timezone.now() - timedelta(days=400))
    open_role = make_role("Example open role (fixture)", actor=superadmin)
    return {
        "due": _application(old_role, decided_days_ago=300),
        "hired": _application(old_role, stage="hired", decided_days_ago=300),
        "recent": _application(old_role, decided_days_ago=30),
        "open_role": _application(open_role, decided_days_ago=300),
    }


def test_retention_is_a_dry_run_by_default(dataset, settings):
    assert settings.RETENTION_ENFORCE is False
    assert retention.run() == 1
    assert Application.objects.count() == 4
    assert not Application.objects.filter(retention_flagged_at__isnull=False).exists()
    assert not AuditEvent.objects.filter(action="careers.application_deleted").exists()


def test_retention_enforced(dataset, settings):
    settings.RETENTION_ENFORCE = True
    due = dataset["due"]
    assert retention.run() == 1
    assert not Application.objects.filter(pk=due.pk).exists()
    assert not storages["careers_cvs"].exists(due.cv_path)
    hired = Application.objects.get(pk=dataset["hired"].pk)
    assert hired.retention_flagged_at is not None
    assert Application.objects.filter(pk=dataset["recent"].pk).exists()
    assert Application.objects.filter(pk=dataset["open_role"].pk).exists()  # its role has not closed
    deleted = AuditEvent.objects.get(action="careers.application_deleted")
    assert deleted.entity_id == retention.hashed_id(due.pk)
    assert AuditEvent.objects.filter(action="careers.application_flagged").count() == 1
    assert retention.run() == 0  # nothing left to do; hired is not flagged twice
    assert AuditEvent.objects.filter(action="careers.application_flagged").count() == 1


def test_retention_months_setting_is_respected(dataset, settings, superadmin):
    settings.RETENTION_ENFORCE = True
    services.update_settings({"retention_months": 1}, actor=superadmin)
    # A month after a 30-day-old decision is up to 31 days after it (on 1 Nov it is 2 Nov), so look two days
    # ahead: the 30-day-old decision is then due on any date.
    assert retention.run(now=timezone.now() + timedelta(days=2)) == 2


def test_add_months_handles_month_ends():
    from datetime import datetime

    assert retention.add_months(datetime(2026, 8, 31), 6) == datetime(2027, 2, 28)
    assert retention.add_months(datetime(2026, 1, 15), 12) == datetime(2027, 1, 15)


def test_pending_uploads_are_purged_after_a_day(superadmin):
    role = make_role(actor=superadmin)
    now = timezone.now()
    old = UploadTicket.objects.create(
        role=role,
        mode="fallback",
        mime="application/pdf",
        extension="pdf",
        size=10,
        filename="cv.pdf",
        key="pending/old.pdf",
        expires_at=now,
        created_at=now - timedelta(hours=25),
    )
    storages["careers_cvs"].save(old.key, ContentFile(b"%PDF-1.7"))
    fresh = UploadTicket.objects.create(
        role=role,
        mode="fallback",
        mime="application/pdf",
        extension="pdf",
        size=10,
        filename="cv.pdf",
        key="pending/fresh.pdf",
        expires_at=now,
        created_at=now - timedelta(hours=2),
    )
    assert retention.purge_uploads() == 1  # runs for real: abandoned uploads are not retention data
    assert not storages["careers_cvs"].exists(old.key)
    assert list(UploadTicket.objects.values_list("pk", flat=True)) == [fresh.pk]
    assert AuditEvent.objects.filter(action="careers.upload_purged").count() == 1


def test_tick_runs_retention_nightly(dataset, settings):
    from apps.content_sync import tick

    settings.RETENTION_ENFORCE = True
    TickState.objects.filter(pk=1).update(last_daily_at=None)
    tick.run()
    assert not Application.objects.filter(pk=dataset["due"].pk).exists()
    assert TickState.load().last_result.get("retention") == 1


# --- import_repo_content -------------------------------------------------------------------------


def _export(tmp_path, data) -> str:
    path = tmp_path / "export.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


EXPORT = {
    "posts": [
        {
            "sourcePath": "content/insights/example-one.md",
            "title": "Example imported post (fixture)",
            "excerpt": "Example excerpt (fixture).",
            "bodyMarkdown": "## Example\n\nExample body (fixture).",
            "format": "engineering-note",
            "publishedAt": "2026-01-01T00:00:00Z",
            "authors": ["Example Imported Author"],
            "topics": ["data"],
        },
        {"sourcePath": "content/insights/placeholder.md", "title": "Placeholder", "placeholder": True},
        {"title": "No source path"},
    ],
    "roles": [
        {
            "sourcePath": "content/careers/example-role.md",
            "title": "Example imported role (fixture)",
            "practice": "engineering",
            "workModel": "hybrid",
            "employmentType": "permanent_full_time",
            "summary": "Example summary (fixture).",
            "about": "Example about (fixture).",
            "salaryMin": 1,
            "salaryMax": 2,
        }
    ],
}


def test_import_is_a_dry_run_by_default(tmp_path):
    out = io.StringIO()
    call_command("import_repo_content", _export(tmp_path, EXPORT), stdout=out)
    assert "Dry run" in out.getvalue() and "created=2" in out.getvalue() and "refused=2" in out.getvalue()
    assert not Post.objects.exists() and not Role.objects.exists()


def test_import_applies_drafts_only_and_is_idempotent(tmp_path):
    path = _export(tmp_path, EXPORT)
    call_command("import_repo_content", path, "--apply", stdout=io.StringIO())
    post = Post.objects.get(source_path="content/insights/example-one.md")
    assert post.status == PostStatus.DRAFT and post.published_snapshot is None
    assert post.format == "engineering_note" and post.first_published_at is None
    author = Author.objects.get(name="Example Imported Author")
    assert not author.is_confirmed
    assert list(post.topics.values_list("slug", flat=True)) == ["data"]
    role = Role.objects.get(source_path="content/careers/example-role.md")
    assert role.status == RoleStatus.DRAFT and role.show_salary is False and role.salary_max == 2
    assert not Post.objects.filter(title="Placeholder").exists()
    assert AuditEvent.objects.filter(action="content.imported").count() == 1
    out = io.StringIO()
    call_command("import_repo_content", path, "--apply", stdout=out)
    assert "created=0 skipped=2" in out.getvalue()
    assert Post.objects.count() == 1 and Role.objects.count() == 1
