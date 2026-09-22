"""Independent acceptance coverage for Phase 16 audit and restore safety."""

import sqlite3

import pytest

from accounts.models import User, UserRole
from scheduling.models import AuditAction, AuditEvent
from scheduling.services.audit import AuditService
from scheduling.services.operations import BackupError, create_backup, restore_backup
from scheduling.services.operations import backup as backup_module


def sqlite_database(path, value):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE django_migrations (app TEXT NOT NULL, name TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO django_migrations (app, name) VALUES (?, ?)",
            ["scheduling", "0005_audit_event"],
        )
        connection.execute("CREATE TABLE state (value TEXT NOT NULL)")
        connection.execute("INSERT INTO state (value) VALUES (?)", [value])


@pytest.mark.django_db
def test_audit_actor_snapshot_and_secret_scrubbing_are_stable():
    actor = User.objects.create_user(
        username="phase16-auditor", password="secret-pass-123", role=UserRole.COLLEGE_ADMIN
    )
    event = AuditService.record(
        action=AuditAction.COLLEGE_DRAFT_GENERATED,
        actor=actor,
        metadata={"entry_count": 1, "authorization": "Bearer secret", "password": "secret"},
    )
    actor.username = "renamed-auditor"
    actor.role = UserRole.VIEWER
    actor.save(update_fields=["username", "role"])
    event.refresh_from_db()
    assert event.actor_username_snapshot == "phase16-auditor"
    assert event.actor_role_snapshot == UserRole.COLLEGE_ADMIN
    assert event.metadata == {"entry_count": 1}
    assert AuditEvent.objects.count() == 1


def test_restore_never_replaces_target_when_safety_backup_fails(tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite3"
    target = tmp_path / "target.sqlite3"
    sqlite_database(source, "state-a")
    sqlite_database(target, "state-b")
    archive = create_backup(source=source, directory=tmp_path / "backups")
    original = target.read_bytes()

    def fail_safety_backup(**kwargs):
        raise BackupError("SAFETY_BACKUP_FAILED", "forced failure")

    monkeypatch.setattr(backup_module, "create_backup", fail_safety_backup)
    with pytest.raises(BackupError, match="forced failure"):
        restore_backup(
            archive=archive.path,
            target=target,
            confirm="RESTORE",
            directory=tmp_path / "backups",
            expected_fingerprint=archive.fingerprint,
        )
    assert target.read_bytes() == original
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT value FROM state").fetchone()[0] == "state-b"
