from __future__ import annotations

from typing import Any, Dict, List, Optional

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
    salesforce_credentials: Dict[str, Any]
    object_names: Optional[List[str]] = None
    processing_date: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ScanStatusResponse(BaseResponse):
    scan_id: str
    organization_id: Optional[str]
    status: str
    created_at: Optional[str]
    updated_at: Optional[str]
    completed_at: Optional[str]
    error_message: Optional[str] = None
    pipeline_progress: Dict[str, Any] = Field(default_factory=dict)
    entity_record_counts: Dict[str, Any] = Field(default_factory=dict)


class ScanListResponse(BaseResponse):
    items: List[Dict[str, Any]]
    pagination: PaginationInfo


class ScanStatisticsResponse(BaseResponse):
    counts_by_status: Dict[str, int] = Field(default_factory=dict)


class NormalizationOptions(BaseModel):
    output_format: str = "parquet"
    save_to_disk: bool = True
    upload_to_minio: bool = False
    processing_date: Optional[str] = None


class SupportedObjectInfo(BaseResponse):
    object_name: str
    output_tables: List[str]


class SalesforceCredentials(BaseModel):
    grant_type: str = "password"
    username: Optional[str] = None
    password: Optional[str] = None
    security_token: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    jwt_private_key: Optional[str] = None
    jwt_subject: Optional[str] = None
    login_url: Optional[str] = None


class CredentialsValidationResponse(BaseResponse):
    valid: bool
    error: Optional[str] = None
    identity: Optional[Dict[str, Any]] = None


class HealthComponent(BaseResponse):
    status: str
    latency_ms: Optional[float] = None
    error: Optional[str] = None


class HealthResponse(BaseResponse):
    status: str
    app_env: str
    version: str = "0.1.0"
    components: Dict[str, HealthComponent]


class ServiceStatsResponse(BaseResponse):
    started_at: str
    uptime_seconds: float
    requests_total: int = 0
    jobs_total: int = 0
