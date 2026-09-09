import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.db.base import Base
from src.app.models import JobStatus
from src.app.services.batch_file_service import BatchFileService
from src.app.services.job_service import JobService
from src.app.services.normalization_service import NormalizationService


@pytest.mark.asyncio
async def test_normalization_service_writes_parquet(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    job_service = JobService(session)
    job_service.create_job("scan-1", "org-1")
    file_service = BatchFileService(str(tmp_path))
    file_service.save_results_to_disk("scan-1", "Lead", iter(["Id,Name,Status\n", "00Q,Ada,Open\n"]))
    job_service.update_job_status("scan-1", JobStatus.BATCH_REQUESTED)
    job_service.update_job_status("scan-1", JobStatus.BATCH_PROCESSING)
    job_service.update_job_status("scan-1", JobStatus.BATCH_READY)
    job_service.update_job_status("scan-1", JobStatus.DOWNLOADING)
    job_service.update_job_status("scan-1", JobStatus.DOWNLOADED)
    job_service.update_job_status("scan-1", JobStatus.EXTRACTING)
    job_service.update_job_status("scan-1", JobStatus.EXTRACTED)
    service = NormalizationService(session, job_service, file_service=file_service)
    result = await service.normalize_scan("scan-1")
    assert result["tables"]["leads"] == 1
    assert (tmp_path / "scan-1" / "normalized" / "leads.parquet").exists()


@pytest.mark.asyncio
async def test_normalization_and_upload_refresh_heartbeat(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    job_service = JobService(session)
    job_service.create_job("scan-heartbeat", "org-1")
    file_service = BatchFileService(str(tmp_path))
    file_service.save_results_to_disk("scan-heartbeat", "Lead", iter(["Id,Name\n", "00Q,Ada\n"]))
    for status in [JobStatus.BATCH_REQUESTED, JobStatus.BATCH_PROCESSING, JobStatus.BATCH_READY,
                   JobStatus.DOWNLOADING, JobStatus.DOWNLOADED, JobStatus.EXTRACTING,
                   JobStatus.EXTRACTED]:
        job_service.update_job_status("scan-heartbeat", status)

    heartbeat_calls = []
    original_update_heartbeat = job_service.update_heartbeat

    def record_heartbeat(scan_id):
        heartbeat_calls.append(scan_id)
        return original_update_heartbeat(scan_id)

    monkeypatch.setattr(job_service, "update_heartbeat", record_heartbeat)

    class FakeMinio:
        def upload_normalized_data(self, scan_id, organization_id, processing_date, tables):
            return ["salesforce/leads/leads.parquet"]

    service = NormalizationService(session, job_service, file_service=file_service, minio_client=FakeMinio())
    await service.normalize_scan("scan-heartbeat", upload_to_minio=True, processing_date="2026-09-08")

    assert heartbeat_calls.count("scan-heartbeat") >= 4
    assert job_service.get_job("scan-heartbeat").last_heartbeat is not None
