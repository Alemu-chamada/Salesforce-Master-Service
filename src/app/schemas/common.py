from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")


class PaginationInfo(BaseResponse):
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    has_prev: bool


class ScanStartRequest(BaseModel):
    organization_id: str = Field(..., min_length=1)
    salesforce_credentials: dict[str, Any]
    object_names: list[str] | None = None
    processing_date: str | None = None
    metadata: dict[str, Any] | None = None


class ScanResumeRequest(BaseModel):
    salesforce_credentials: dict[str, Any] | None = None


class ScanStatusResponse(BaseResponse):
    scan_id: str
    organization_id: str | None
    status: str
    created_at: str | None
    updated_at: str | None
    completed_at: str | None
    error_message: str | None = None
    pipeline_progress: dict[str, Any] = Field(default_factory=dict)
    entity_record_counts: dict[str, Any] = Field(default_factory=dict)


class ScanListResponse(BaseResponse):
    items: list[dict[str, Any]]
    pagination: PaginationInfo


class ScanStatisticsResponse(BaseResponse):
    counts_by_status: dict[str, int] = Field(default_factory=dict)


class NormalizationOptions(BaseModel):
    output_format: str = "parquet"
    save_to_disk: bool = True
    upload_to_minio: bool = False
    processing_date: str | None = None


class SupportedObjectInfo(BaseResponse):
    object_name: str
    output_tables: list[str]


class SalesforceCredentials(BaseModel):
    grant_type: str = "password"
    username: str | None = None
    password: str | None = None
    security_token: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    jwt_private_key: str | None = None
    jwt_subject: str | None = None
    login_url: str | None = None


class CredentialsValidationResponse(BaseResponse):
    valid: bool
    error: str | None = None
    identity: dict[str, Any] | None = None


class HealthComponent(BaseResponse):
    status: str
    latency_ms: float | None = None
    error: str | None = None


class HealthResponse(BaseResponse):
    status: str
    app_env: str
    version: str = "0.1.0"
    components: dict[str, HealthComponent]


class ServiceStatsResponse(BaseResponse):
    started_at: str
    uptime_seconds: float
    requests_total: int = 0
    jobs_total: int = 0
