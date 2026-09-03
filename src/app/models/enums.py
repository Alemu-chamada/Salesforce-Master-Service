from __future__ import annotations

import enum


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    BATCH_REQUESTED = "BATCH_REQUESTED"
    BATCH_PROCESSING = "BATCH_PROCESSING"
    BATCH_READY = "BATCH_READY"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOADED = "DOWNLOADED"
    EXTRACTING = "EXTRACTING"
    EXTRACTED = "EXTRACTED"
    NORMALIZING = "NORMALIZING"
    NORMALIZED = "NORMALIZED"
    UPLOADING_TO_MINIO = "UPLOADING_TO_MINIO"
    UPLOADED_TO_MINIO = "UPLOADED_TO_MINIO"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}

IN_PROGRESS_STATUSES = {
    JobStatus.BATCH_PROCESSING,
    JobStatus.DOWNLOADING,
    JobStatus.EXTRACTING,
    JobStatus.NORMALIZING,
    JobStatus.UPLOADING_TO_MINIO,
}

ACTIVE_STATUSES = {s for s in JobStatus if s not in TERMINAL_STATUSES}


class JobStatusTransition:
    MAIN_CHAIN = [
        JobStatus.PENDING,
        JobStatus.BATCH_REQUESTED,
        JobStatus.BATCH_PROCESSING,
        JobStatus.BATCH_READY,
        JobStatus.DOWNLOADING,
        JobStatus.DOWNLOADED,
        JobStatus.EXTRACTING,
        JobStatus.EXTRACTED,
        JobStatus.NORMALIZING,
        JobStatus.NORMALIZED,
        JobStatus.UPLOADING_TO_MINIO,
        JobStatus.UPLOADED_TO_MINIO,
        JobStatus.COMPLETED,
    ]

    @classmethod
    def is_terminal(cls, status: JobStatus) -> bool:
        return status in TERMINAL_STATUSES

    @classmethod
    def is_valid_transition(cls, from_status: JobStatus, to_status: JobStatus) -> bool:
        if to_status in {JobStatus.FAILED, JobStatus.CANCELLED}:
            return True
        if from_status == to_status:
            return True
        if from_status not in cls.MAIN_CHAIN or to_status not in cls.MAIN_CHAIN:
            return False
        from_idx = cls.MAIN_CHAIN.index(from_status)
        to_idx = cls.MAIN_CHAIN.index(to_status)
        return 0 <= to_idx - from_idx <= 3


class AuditEventCategory(str, enum.Enum):
    AUTH = "auth"
    SCAN = "scan"
    NORMALIZATION = "normalization"
    MAINTENANCE = "maintenance"
    KEY = "key"
    EXTERNAL = "external"
    SYSTEM = "system"


class AuditOutcome(str, enum.Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    UNAUTHORIZED = "unauthorized"
    BLOCKED = "blocked"


class DLQStatus(str, enum.Enum):
    NEW = "new"
    RETRIABLE = "retriable"
    MANUAL = "manual"
    RESOLVED = "resolved"
