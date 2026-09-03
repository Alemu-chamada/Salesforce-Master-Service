from __future__ import annotations

from src.app.core.config import get_settings
from src.app.models import (
    AuditLog,
    Base,
    DLQStatus,
    FailedExternalCall,
    Job,
    JobStatus,
    TERMINAL_STATUSES,
    IN_PROGRESS_STATUSES,
    ACTIVE_STATUSES,
    JobStatusTransition,
    AuditEventCategory,
    AuditOutcome,
)


def test_settings_loads_without_error():
    settings = get_settings()
    assert settings.APP_ENV == "dev"
    assert settings.DEBUG is True
    assert isinstance(settings.SF_BULK_SUPPORTED_OBJECTS, list)
    assert "Account" in settings.SF_BULK_SUPPORTED_OBJECTS
    assert settings.EXTERNAL_CALL_MAX_RETRIES >= 0
    assert settings.DB_POOL_SIZE >= 1


def test_job_status_enum_has_all_states():
    expected_main = [
        "PENDING",
        "BATCH_REQUESTED",
        "BATCH_PROCESSING",
        "BATCH_READY",
        "DOWNLOADING",
        "DOWNLOADED",
        "EXTRACTING",
        "EXTRACTED",
        "NORMALIZING",
        "NORMALIZED",
        "UPLOADING_TO_MINIO",
        "UPLOADED_TO_MINIO",
        "COMPLETED",
    ]
    for s in expected_main:
        assert JobStatus(s) is not None
    assert JobStatus.FAILED
    assert JobStatus.CANCELLED


def test_job_status_groups():
    for s in TERMINAL_STATUSES:
        assert JobStatusTransition.is_terminal(s)
    for s in IN_PROGRESS_STATUSES:
        assert s in ACTIVE_STATUSES
    assert JobStatus.COMPLETED not in ACTIVE_STATUSES
    assert JobStatus.FAILED not in ACTIVE_STATUSES


def test_status_transitions():
    assert JobStatusTransition.is_valid_transition(
        JobStatus.PENDING, JobStatus.BATCH_REQUESTED
    )
    assert JobStatusTransition.is_valid_transition(
        JobStatus.DOWNLOADING, JobStatus.FAILED
    )
    assert JobStatusTransition.is_valid_transition(
        JobStatus.EXTRACTING, JobStatus.CANCELLED
    )
    assert not JobStatusTransition.is_valid_transition(
        JobStatus.COMPLETED, JobStatus.PENDING
    )


def test_models_import():
    assert Job.__tablename__ == "jobs"
    assert AuditLog.__tablename__ == "audit_logs"
    assert FailedExternalCall.__tablename__ == "failed_external_calls"
    assert Base is not None
    assert AuditEventCategory.AUTH.value == "auth"
    assert AuditOutcome.SUCCESS.value == "success"
    assert DLQStatus.NEW.value == "new"
