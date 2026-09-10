import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.db.base import Base
from src.app.models import JobStatus
from src.app.schemas.common import ScanStartRequest
from src.app.services.batch_file_service import BatchFileService
from src.app.services.extraction_service import ExtractionService
from src.app.services.job_service import JobService
from src.app.services.normalization_service import NormalizationService


class FakePolling:
    def __init__(self, job_service, file_service):
        self.job_service = job_service
        self.file_service = file_service
        self.batch_client = None

    async def configure(self, credentials):
        assert credentials["username"] == "mock-user"

    async def submit_batch_jobs(self, scan_id, objects):
        self.job_service.update_job_status(scan_id, JobStatus.BATCH_REQUESTED)
        self.job_service.update_batch_info(scan_id, [{"object_name": "Lead", "job_id": "mock-job"}], {"Lead": "InProgress"})
        self.job_service.update_job_status(scan_id, JobStatus.BATCH_PROCESSING)
        return {"batch_job_ids": [{"object_name": "Lead", "job_id": "mock-job"}]}

    async def poll_until_ready(self, scan_id, max_wait_minutes, check_interval_seconds):
        self.job_service.update_job_status(scan_id, JobStatus.BATCH_READY)
        return {"ready": True, "statuses": {"Lead": {"state": "JobComplete"}}}

    async def download_results(self, scan_id):
        self.job_service.update_job_status(scan_id, JobStatus.DOWNLOADING)
        info = self.file_service.save_results_to_disk(scan_id, "Lead", iter(["Id,Name,Status\n", "00Q,Ada,Open\n"]))
        self.job_service.update_download_info(scan_id, {"Lead": info["path"]}, {"Lead": info["file_size"]})
        self.job_service.update_job_status(scan_id, JobStatus.DOWNLOADED)
        return info


class FakeMinio:
    def upload_normalized_data(self, scan_id, organization_id, processing_date, tables):
        return [
            (
                f"salesforce/leads/glynac_organization_id={organization_id}/"
                f"processing_date={processing_date}/leads.parquet"
            )
        ]


@pytest.mark.asyncio
async def test_mocked_pipeline_reaches_extracted_then_normalized(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    jobs = JobService(session)
    files = BatchFileService(str(tmp_path))
    polling = FakePolling(jobs, files)
    extraction = ExtractionService(session, jobs, polling_service=polling, file_service=files)

    request = ScanStartRequest(
        organization_id="org-1",
        salesforce_credentials={"grant_type": "password", "username": "mock-user", "password": "discarded"},
        object_names=["Lead"],
    )
    started = await extraction.start_scan(request)
    await asyncio.sleep(0)
    await extraction._execute_batch_workflow(started["scan_id"], ["Lead"])
    assert jobs.get_job(started["scan_id"]).status == JobStatus.EXTRACTED
    assert jobs.get_job(started["scan_id"]).entity_record_counts == {"Lead": 1}

    normalized = await NormalizationService(session, jobs, file_service=files).normalize_scan(started["scan_id"])
    assert normalized["tables"] == {"leads": 1}
    assert (tmp_path / started["scan_id"] / "normalized" / "leads.parquet").exists()
    assert started["scan_id"] not in extraction._runtime_credentials
    assert "salesforce_credentials" not in jobs.get_job(started["scan_id"]).request_config


@pytest.mark.asyncio
async def test_resume_accepts_credentials_after_process_restart(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    jobs = JobService(session)
    files = BatchFileService(str(tmp_path))
    polling = FakePolling(jobs, files)
    extraction = ExtractionService(session, jobs, polling_service=polling, file_service=files)

    jobs.create_job("scan-restart", "org-1", {"object_names": ["Lead"]})
    jobs.fail_job("scan-restart", "simulated restart")

    with pytest.raises(RuntimeError, match="must be supplied"):
        await extraction.resume_scan("scan-restart")

    result = await extraction.resume_scan(
        "scan-restart",
        {"grant_type": "password", "username": "mock-user", "password": "discarded"},
    )
    assert result["scan_id"] == "scan-restart"
    assert "salesforce_credentials" not in jobs.get_job("scan-restart").request_config


@pytest.mark.asyncio
async def test_cancelled_extracted_scan_resumes_at_extracted_checkpoint(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    jobs = JobService(session)
    files = BatchFileService(str(tmp_path))
    polling = FakePolling(jobs, files)
    extraction = ExtractionService(session, jobs, polling_service=polling, file_service=files)

    jobs.create_job("scan-cancelled-extracted", "org-1", {"object_names": ["Lead"]})
    info = files.save_results_to_disk(
        "scan-cancelled-extracted", "Lead", iter(["Id,Name,Status\n", "00Q,Ada,Open\n"])
    )
    jobs.update_download_info(
        "scan-cancelled-extracted", {"Lead": info["path"]}, {"Lead": info["file_size"]}
    )
    jobs.update_extraction_info("scan-cancelled-extracted", {"Lead": 1})
    jobs.cancel_job("scan-cancelled-extracted", reason="test")

    result = await extraction.resume_scan(
        "scan-cancelled-extracted",
        {"grant_type": "password", "username": "mock-user", "password": "discarded"},
    )

    assert result == {"scan_id": "scan-cancelled-extracted", "status": JobStatus.EXTRACTED.value}
    assert jobs.get_job("scan-cancelled-extracted").status == JobStatus.EXTRACTED

    # A worker that was already running before cancellation must not advance
    # the resumed checkpoint or restart extraction from an obsolete state.
    await extraction._execute_batch_workflow("scan-cancelled-extracted", ["Lead"])
    assert jobs.get_job("scan-cancelled-extracted").status == JobStatus.EXTRACTED

    normalized = await NormalizationService(
        session, jobs, file_service=files, minio_client=FakeMinio()
    ).normalize_scan(
        "scan-cancelled-extracted", upload_to_minio=True, processing_date="2026-09-10"
    )
    assert normalized["status"] == JobStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_cancelled_downloaded_scan_resumes_worker_and_completes(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    jobs = JobService(session)
    files = BatchFileService(str(tmp_path))
    polling = FakePolling(jobs, files)
    extraction = ExtractionService(session, jobs, polling_service=polling, file_service=files)

    jobs.create_job("scan-cancelled-downloaded", "org-1", {"object_names": ["Lead"]})
    info = files.save_results_to_disk(
        "scan-cancelled-downloaded", "Lead", iter(["Id,Name,Status\n", "00Q,Ada,Open\n"])
    )
    jobs.update_download_info(
        "scan-cancelled-downloaded", {"Lead": info["path"]}, {"Lead": info["file_size"]}
    )
    jobs.cancel_job("scan-cancelled-downloaded", reason="test")

    # A stale worker must exit while the job is still cancelled.
    await extraction._execute_batch_workflow("scan-cancelled-downloaded", ["Lead"])
    assert jobs.get_job("scan-cancelled-downloaded").status == JobStatus.CANCELLED
    assert jobs.get_job("scan-cancelled-downloaded").extracted_at is None

    result = await extraction.resume_scan(
        "scan-cancelled-downloaded",
        {"grant_type": "password", "username": "mock-user", "password": "discarded"},
    )
    assert result["status"] == JobStatus.EXTRACTING.value
    await extraction._execute_batch_workflow("scan-cancelled-downloaded", ["Lead"])
    assert jobs.get_job("scan-cancelled-downloaded").status == JobStatus.EXTRACTED

    normalized = await NormalizationService(
        session, jobs, file_service=files, minio_client=FakeMinio()
    ).normalize_scan(
        "scan-cancelled-downloaded", upload_to_minio=True, processing_date="2026-09-10"
    )
    assert normalized["status"] == JobStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_cancel_clears_runtime_credentials(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    jobs = JobService(session)
    files = BatchFileService(str(tmp_path))
    extraction = ExtractionService(session, jobs, polling_service=FakePolling(jobs, files), file_service=files)
    jobs.create_job("scan-cancel", "org-1")
    extraction._runtime_credentials["scan-cancel"] = {"password": "discarded"}

    await extraction.cancel_scan("scan-cancel")

    assert "scan-cancel" not in extraction._runtime_credentials
