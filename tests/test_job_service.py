from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.app.db.base import Base
from src.app.models import Job, JobStatus
from src.app.services.job_service import JobService


def _in_memory_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def test_job_service_creates_job():
    session = _in_memory_session()
    svc = JobService(session)
    scan_id = f"scan-{uuid.uuid4().hex[:12]}"
    job = svc.create_job(scan_id=scan_id, organization_id="org-test", request_config={"foo": "bar"})
    assert job is not None
    assert job.scan_id == scan_id
    assert job.organization_id == "org-test"
    assert job.status == JobStatus.PENDING
    assert job.request_config == {"foo": "bar"}


def test_job_service_updates_status():
    session = _in_memory_session()
    svc = JobService(session)
    scan_id = f"scan-{uuid.uuid4().hex[:12]}"
    svc.create_job(scan_id=scan_id, organization_id="org-1")
    updated = svc.update_job_status(scan_id, JobStatus.BATCH_REQUESTED)
    assert updated is not None
    assert updated.status == JobStatus.BATCH_REQUESTED


def test_job_service_rejects_invalid_transition():
    session = _in_memory_session()
    svc = JobService(session)
    scan_id = f"scan-{uuid.uuid4().hex[:12]}"
    svc.create_job(scan_id=scan_id, organization_id="org-1")
    svc.update_job_status(scan_id, JobStatus.COMPLETED)
    job = svc.get_job(scan_id)
    assert job.status == JobStatus.PENDING


def test_job_service_fail_and_cancel():
    session = _in_memory_session()
    svc = JobService(session)

    s1 = f"scan-{uuid.uuid4().hex[:12]}"
    svc.create_job(s1, "org-1")
    failed = svc.fail_job(s1, "boom")
    assert failed.status == JobStatus.FAILED
    assert "boom" in failed.error_message
    assert failed.completed_at is not None

    s2 = f"scan-{uuid.uuid4().hex[:12]}"
    svc.create_job(s2, "org-2")
    cancelled = svc.cancel_job(s2, reason="manual", actor="engineer")
    assert cancelled.status == JobStatus.CANCELLED
    assert cancelled.cancel_reason == "manual"
    assert cancelled.cancelled_by == "engineer"


def test_job_service_heartbeat_and_progress():
    session = _in_memory_session()
    svc = JobService(session)
    scan_id = f"scan-{uuid.uuid4().hex[:12]}"
    svc.create_job(scan_id=scan_id, organization_id="org-1")
    svc.update_heartbeat(scan_id)
    job = svc.get_job(scan_id)
    assert job.last_heartbeat is not None

    progress = svc.get_pipeline_progress(scan_id)
    assert progress["status"] == JobStatus.PENDING.value
    assert progress["created_at"] is not None


def test_job_service_get_missing_returns_none():
    session = _in_memory_session()
    svc = JobService(session)
    assert svc.get_job("nope") is None
