from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    APP_ENV: str = Field(default="dev", description="Runtime environment: dev / stage / prod")
    LOG_LEVEL: str = Field(default="INFO")
    APP_NAME: str = Field(default="salesforce-master-service")
    API_PREFIX: str = Field(default="/api")
    DEBUG: bool = Field(default=False)

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @model_validator(mode="after")
    def _validate_production_guardrails(self) -> AppSettings:
        if self.APP_ENV.lower() in {"prod", "production", "stage", "staging"} and self.DEBUG:
            raise ValueError("DEBUG must be False in staging/production environments")
        return self


class DatabaseSettings(BaseSettings):
    DATABASE_URL: str = Field(
        default="postgresql+psycopg2://sf_master:sf_master_pass@localhost:5432/sf_master"
    )
    DB_POOL_SIZE: int = Field(default=10, ge=1)
    DB_MAX_OVERFLOW: int = Field(default=20, ge=0)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class SalesforceSettings(BaseSettings):
    SF_LOGIN_URL: str = Field(default="https://test.salesforce.com")
    SF_CLIENT_ID: str = Field(default="REPLACE_ME_CONNECTED_APP_CONSUMER_KEY")
    SF_CLIENT_SECRET: str = Field(default="REPLACE_ME_CONNECTED_APP_CONSUMER_SECRET")
    SF_JWT_PRIVATE_KEY_PATH: str | None = Field(default=None)
    SF_API_VERSION: str = Field(default="59.0")
    SF_TIMEOUT_SECONDS: int = Field(default=60, ge=1)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> SalesforceSettings:
        env = os.getenv("APP_ENV", "dev").lower()
        if env in {"prod", "production", "stage", "staging"}:
            if self.SF_CLIENT_ID.startswith("REPLACE_ME"):
                raise ValueError("SF_CLIENT_ID must be set in staging/production")
            if self.SF_CLIENT_SECRET.startswith("REPLACE_ME") and not self.SF_JWT_PRIVATE_KEY_PATH:
                raise ValueError("SF_CLIENT_SECRET or SF_JWT_PRIVATE_KEY_PATH must be set in staging/production")
        return self


_DEFAULT_OBJECTS = [
    "Account",
    "Contact",
    "Opportunity",
    "OpportunityLineItem",
    "Lead",
    "Case",
    "Task",
    "Event",
    "Campaign",
    "User",
]


class BulkAPISettings(BaseSettings):
    SF_BULK_POLL_INTERVAL_SECONDS: int = Field(default=10, ge=1)
    SF_BULK_MAX_WAIT_MINUTES: int = Field(default=120, ge=1)
    SF_BULK_SUPPORTED_OBJECTS: Any = Field(default_factory=lambda: list(_DEFAULT_OBJECTS))

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("SF_BULK_SUPPORTED_OBJECTS", mode="before")
    @classmethod
    def _split_objects(cls, v: Any) -> Any:
        if v is None:
            return list(_DEFAULT_OBJECTS)
        if isinstance(v, str):
            if not v.strip():
                return list(_DEFAULT_OBJECTS)
            return [obj.strip() for obj in v.split(",") if obj.strip()]
        if isinstance(v, (list, tuple)):
            return [str(x).strip() for x in v if str(x).strip()]
        return list(_DEFAULT_OBJECTS)


class MinIOSettings(BaseSettings):
    MINIO_ENDPOINT: str = Field(default="localhost:9000")
    MINIO_ACCESS_KEY: str = Field(default="minioadmin")
    MINIO_SECRET_KEY: str = Field(default="minioadmin")
    MINIO_BUCKET: str = Field(default="salesforce-data")
    MINIO_SECURE: bool = Field(default=False)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


_DEFAULT_DELAYS = [1, 2, 4]


class ResilienceSettings(BaseSettings):
    EXTERNAL_CALL_MAX_RETRIES: int = Field(default=3, ge=0)
    EXTERNAL_CALL_RETRY_DELAYS: Any = Field(default_factory=lambda: list(_DEFAULT_DELAYS))
    EXTERNAL_CALL_MAX_DELAY_SECONDS: float = Field(default=30.0, ge=0)
    EXTERNAL_CALL_JITTER: bool = Field(default=True)
    DLQ_PAYLOAD_MAX_BYTES: int = Field(default=65536, ge=1024)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("EXTERNAL_CALL_RETRY_DELAYS", mode="before")
    @classmethod
    def _split_delays(cls, v: Any) -> Any:
        if v is None:
            return list(_DEFAULT_DELAYS)
        if isinstance(v, str):
            if not v.strip():
                return list(_DEFAULT_DELAYS)
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        if isinstance(v, (list, tuple)):
            return [int(x) for x in v]
        return list(_DEFAULT_DELAYS)


class HMACSettings(BaseSettings):
    HMAC_ENABLED: bool = Field(default=True)
    HMAC_SECRET_KEY_CORE: str = Field(default="REPLACE_ME_COORDINATOR_SHARED_SECRET")
    HMAC_SECRET_KEY_ENGINEER: str = Field(default="REPLACE_ME_ENGINEER_READONLY_SECRET")
    HMAC_SIGNATURE_MAX_AGE: int = Field(default=300, ge=30)
    HMAC_CLIENT_CONFIG: dict[str, dict[str, Any]] = Field(
        default_factory=lambda: {
            "coordinator": {"role": "full"},
            "engineer": {"role": "read_only"},
        }
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("HMAC_CLIENT_CONFIG", mode="before")
    @classmethod
    def _parse_json_config(cls, v: Any) -> Any:
        if isinstance(v, str):
            return json.loads(v)
        return v

    @model_validator(mode="after")
    def _validate_production_guardrails(self) -> HMACSettings:
        env = os.getenv("APP_ENV", "dev").lower()
        if env in {"prod", "production", "stage", "staging"}:
            if not self.HMAC_ENABLED:
                raise ValueError("HMAC_ENABLED must be True in staging/production")
            if self.HMAC_SECRET_KEY_CORE.startswith("REPLACE_ME"):
                raise ValueError("HMAC_SECRET_KEY_CORE must be set in staging/production")
            if self.HMAC_SECRET_KEY_ENGINEER.startswith("REPLACE_ME"):
                raise ValueError("HMAC_SECRET_KEY_ENGINEER must be set in staging/production")
        return self


class HealthSettings(BaseSettings):
    HEALTH_CHECK_DB_ENABLED: bool = Field(default=True)
    HEALTH_CHECK_MINIO_ENABLED: bool = Field(default=True)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class DataSettings(BaseSettings):
    DATA_ROOT_DIR: str = Field(default="./data/scans")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class Settings(
    AppSettings,
    DatabaseSettings,
    SalesforceSettings,
    BulkAPISettings,
    MinIOSettings,
    ResilienceSettings,
    HMACSettings,
    HealthSettings,
    DataSettings,
):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
