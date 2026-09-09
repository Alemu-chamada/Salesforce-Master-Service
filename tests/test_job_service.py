from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.app.core.utils import utcnow
from src.app.db.base import Base
from src.app.models import JobStatus
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


# ---- NEW tests for Phase 3 methods ----

def test_update_batch_info():
    session = _in_memory_session()
    svc = JobService(session)
    scan_id = f"scan-{uuid.uuid4().hex[:12]}"
    svc.create_job(scan_id, "org-1")
    job = svc.update_batch_info(scan_id, batch_job_ids=["750A", "750B"], batch_status={"Account": "InProgress"})
    assert job.batch_job_ids == ["750A", "750B"]
    assert job.batch_status == {"Account": "InProgress"}
    assert job.batch_requested_at is not None


def test_update_download_info():
    session = _in_memory_session()
    svc = JobService(session)
    scan_id = f"scan-{uuid.uuid4().hex[:12]}"
    svc.create_job(scan_id, "org-1")
    job = svc.update_download_info(scan_id, file_paths={"Account": "/tmp/acc.csv"}, file_sizes={"Account": 1024})
    assert job.file_paths == {"Account": "/tmp/acc.csv"}
    assert job.downloaded_at is not None


def test_update_extraction_info():
    session = _in_memory_session()
    svc = JobService(session)
    scan_id = f"scan-{uuid.uuid4().hex[:12]}"
    svc.create_job(scan_id, "org-1")
    job = svc.update_extraction_info(scan_id, extracted_file_counts={"Account": 100, "Contact": 50})
    assert job.entity_record_counts["Account"] == 100
    assert job.extracted_at is not None


def test_start_and_complete_normalization():
    session = _in_memory_session()
    svc = JobService(session)
    scan_id = f"scan-{uuid.uuid4().hex[:12]}"
    svc.create_job(scan_id, "org-1")
    # transition to EXTRACTED first
    svc.update_job_status(scan_id, JobStatus.BATCH_REQUESTED)
    svc.update_job_status(scan_id, JobStatus.BATCH_PROCESSING)
    svc.update_job_status(scan_id, JobStatus.BATCH_READY)
    svc.update_job_status(scan_id, JobStatus.DOWNLOADING)
    svc.update_job_status(scan_id, JobStatus.DOWNLOADED)
    svc.update_job_status(scan_id, JobStatus.EXTRACTING)
    svc.update_job_status(scan_id, JobStatus.EXTRACTED)
    job = svc.start_normalization(scan_id)
    assert job.status == JobStatus.NORMALIZING
    job2 = svc.complete_normalization(scan_id, stats={"accounts": 10})
    assert job2.status == JobStatus.NORMALIZED
    assert job2.normalization_stats == {"accounts": 10}
    assert job2.normalized_at is not None


def test_start_and_complete_minio_upload():
    session = _in_memory_session()
    svc = JobService(session)
    scan_id = f"scan-{uuid.uuid4().hex[:12]}"
    svc.create_job(scan_id, "org-1")
    for st in [JobStatus.BATCH_REQUESTED, JobStatus.BATCH_PROCESSING, JobStatus.BATCH_READY,
               JobStatus.DOWNLOADING, JobStatus.DOWNLOADED, JobStatus.EXTRACTING,
               JobStatus.EXTRACTED, JobStatus.NORMALIZING, JobStatus.NORMALIZED]:
        svc.update_job_status(scan_id, st)
    job = svc.start_minio_upload(scan_id)
    assert job.status == JobStatus.UPLOADING_TO_MINIO
    job2 = svc.complete_minio_upload(scan_id, uploaded_keys={"accounts": "s3://bucket/accounts"})
    assert job2.status == JobStatus.UPLOADED_TO_MINIO
    assert job2.minio_object_keys == {"accounts": "s3://bucket/accounts"}
    assert job2.minio_uploaded_at is not None


def test_store_entity_record_counts():
    session = _in_memory_session()
    svc = JobService(session)
    scan_id = f"scan-{uuid.uuid4().hex[:12]}"
    svc.create_job(scan_id, "org-1")
    svc.store_entity_record_counts(scan_id, {"Account": 100})
    svc.store_entity_record_counts(scan_id, {"Contact": 50})
    job = svc.get_job(scan_id)
    assert job.entity_record_counts["Account"] == 100
    assert job.entity_record_counts["Contact"] == 50


def test_detect_crashed_jobs():
    import datetime as _dt
    session = _in_memory_session()
    svc = JobService(session)
    scan_id = f"scan-{uuid.uuid4().hex[:12]}"
    svc.create_job(scan_id, "org-1")
    svc.update_job_status(scan_id, JobStatus.BATCH_REQUESTED)
    svc.update_job_status(scan_id, JobStatus.BATCH_PROCESSING)
    # Manually set stale heartbeat
    job = svc.get_job(scan_id)
    job.last_heartbeat = utcnow() - _dt.timedelta(minutes=60)
    session.commit()
    crashed = svc.detect_crashed_jobs(timeout_minutes=30)
    assert scan_id in crashed
    updated = svc.get_job(scan_id)
    assert updated.status == JobStatus.FAILED


def test_list_jobs_and_statistics():
    session = _in_memory_session()
    svc = JobService(session)
    for i in range(3):
        svc.create_job(f"scan-{i}", "org-list")
    result = svc.list_jobs(organization_id="org-list")
    assert result["total"] == 3
    assert len(result["items"]) == 3
    stats = svc.get_statistics()
    assert stats.get("PENDING", 0) >= 3


def test_cleanup_old_jobs():
    import datetime as _dt
    session = _in_memory_session()
    svc = JobService(session)
    scan_id = f"scan-old-{uuid.uuid4().hex[:8]}"
    svc.create_job(scan_id, "org-1")
    # backdate created_at
    job = svc.get_job(scan_id)
    job.created_at = utcnow() - _dt.timedelta(days=40)
    session.commit()
    deleted = svc.cleanup_old_jobs(days_old=30)
    assert deleted >= 1
    assert svc.get_job(scan_id) is None
