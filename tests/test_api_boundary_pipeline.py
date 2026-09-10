import time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.api.routes import normalization as normalization_routes
from src.app.api.routes import scan as scan_routes
from src.app.audit.audit_service import AuditService
from src.app.db.base import Base
from src.app.db.session import get_db
from src.app.main import create_app
from src.app.models import JobStatus
from src.app.services.batch_file_service import BatchFileService
from src.app.services.batch_polling_service import BatchPollingService
from src.app.services.extraction_service import ExtractionService
from src.app.services.job_service import JobService
from src.app.services.normalization_service import NormalizationService


class FakeAuth:
    async def get_access_token(self, credentials):
        assert credentials["username"] == "coordinator-test"
        return {"access_token": "fake-token", "instance_url": "https://fake.salesforce.test"}


class FakeBatchClient:
    def __init__(self, *args, **kwargs):
        self.status_calls = 0

    async def create_query_job(self, object_name, soql):
        return {"job_id": "750-fake", "state": "UploadComplete"}

    async def get_job_status(self, job_id):
        self.status_calls += 1
        return {"job_id": job_id, "state": "JobComplete", "number_records_processed": 1}

    async def get_job_results_paginated(self, job_id):
        yield b"Id,Name,Status\n00Q,Ada,Open\n"

    async def close_job(self, job_id):
        raise AssertionError("completed Bulk API query jobs must not be closed after download")


class FakeMinio:
    def upload_normalized_data(self, scan_id, organization_id, processing_date, tables):
        return [f"salesforce/leads/glynac_organization_id={organization_id}/processing_date={processing_date}/leads.parquet"]


def test_api_boundary_pipeline_reaches_completed(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    jobs = JobService(session)
    files = BatchFileService(str(tmp_path))
    polling = BatchPollingService(session, jobs, auth_client=FakeAuth(), file_service=files)
    monkeypatch.setattr("src.app.services.batch_polling_service.SalesforceBatchAPIClient", FakeBatchClient)
    extraction = ExtractionService(session, jobs, polling_service=polling, file_service=files)
    normalization = NormalizationService(session, jobs, file_service=files, minio_client=FakeMinio())
    extraction.audit = AuditService(SessionLocal)
    polling.audit = AuditService(SessionLocal)
    normalization.audit = AuditService(SessionLocal)

    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[scan_routes._extraction_service] = lambda: extraction
    app.dependency_overrides[normalization_routes._norm_service] = lambda: normalization

    with TestClient(app) as client:
        response = client.post("/api/scan/start", json={
            "organization_id": "org-api",
            "salesforce_credentials": {"grant_type": "password", "username": "coordinator-test", "password": "discarded"},
            "object_names": ["Lead"],
        })
        assert response.status_code == 202
        scan_id = response.json()["scan_id"]
        for _ in range(50):
            status_response = client.get(f"/api/scan/{scan_id}/status")
            if status_response.json()["status"] == JobStatus.EXTRACTED.value:
                break
            time.sleep(0.01)
        normalize_response = client.post(
            f"/api/normalization/{scan_id}/normalize",
            json={"output_format": "parquet", "save_to_disk": True, "upload_to_minio": True, "processing_date": "2026-09-04"},
        )
        client.get("/api/stats")

    assert normalize_response.status_code == 200, normalize_response.text
    job = jobs.get_job(scan_id)
    assert job.status == JobStatus.COMPLETED
    assert job.entity_record_counts == {"Lead": 1}
    assert job.minio_object_keys["0"].startswith("salesforce/leads/")
    assert (tmp_path / scan_id / "normalized" / "leads.parquet").exists()
    time.sleep(0.1)
    audit_events = {row.event_type for row in SessionLocal().query(__import__("src.app.models", fromlist=["AuditLog"]).AuditLog).all()}
    assert {"scan_created", "batch_submission_success", "normalization_success", "minio_upload_success"} <= audit_events
