"""create initial service schema

Revision ID: 0001_initial_schema
Revises:
"""
import sqlalchemy as sa

from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

job_status = sa.Enum("PENDING", "BATCH_REQUESTED", "BATCH_PROCESSING", "BATCH_READY", "DOWNLOADING", "DOWNLOADED", "EXTRACTING", "EXTRACTED", "NORMALIZING", "NORMALIZED", "UPLOADING_TO_MINIO", "UPLOADED_TO_MINIO", "COMPLETED", "FAILED", "CANCELLED", name="job_status_enum")
audit_category = sa.Enum("AUTH", "SCAN", "NORMALIZATION", "MAINTENANCE", "KEY", "EXTERNAL", "SYSTEM", name="audit_event_category_enum")
audit_outcome = sa.Enum("SUCCESS", "FAILURE", "UNAUTHORIZED", "BLOCKED", name="audit_outcome_enum")
dlq_status = sa.Enum("NEW", "RETRIABLE", "MANUAL", "RESOLVED", name="dlq_status_enum")


def upgrade() -> None:
    op.create_table("jobs",
        sa.Column("scan_id", sa.String(64), primary_key=True), sa.Column("organization_id", sa.String(128)), sa.Column("status", job_status, nullable=False),
        sa.Column("request_config", sa.JSON), sa.Column("error_message", sa.Text), sa.Column("error_detail", sa.JSON), sa.Column("cancelled_by", sa.String(128)), sa.Column("cancel_reason", sa.Text),
        sa.Column("batch_job_ids", sa.JSON), sa.Column("batch_status", sa.JSON), sa.Column("batch_requested_at", sa.DateTime(timezone=True)), sa.Column("downloaded_at", sa.DateTime(timezone=True)), sa.Column("file_paths", sa.JSON), sa.Column("file_sizes", sa.JSON),
        sa.Column("extracted_at", sa.DateTime(timezone=True)), sa.Column("entity_record_counts", sa.JSON), sa.Column("normalized_at", sa.DateTime(timezone=True)), sa.Column("normalization_stats", sa.JSON),
        sa.Column("minio_uploaded_at", sa.DateTime(timezone=True)), sa.Column("minio_object_keys", sa.JSON), sa.Column("last_heartbeat", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_jobs_org_status_created", "jobs", ["organization_id", "status", "created_at"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])
    op.create_index("ix_jobs_last_heartbeat", "jobs", ["last_heartbeat"])
    op.create_table("audit_logs",
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("event_category", audit_category, nullable=False), sa.Column("event_type", sa.String(128), nullable=False), sa.Column("actor_client_id", sa.String(128)), sa.Column("actor_role", sa.String(64)), sa.Column("organization_id", sa.String(128)), sa.Column("entity_type", sa.String(64)), sa.Column("resource_type", sa.String(64)), sa.Column("resource_id", sa.String(128)), sa.Column("http_method", sa.String(16)), sa.Column("endpoint", sa.String(255)), sa.Column("request_ip", sa.String(64)), sa.Column("status_code", sa.Integer), sa.Column("outcome", audit_outcome, nullable=False), sa.Column("severity", sa.String(16)), sa.Column("error_detail", sa.Text), sa.Column("extra_metadata", sa.JSON), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_audit_org_category_created", "audit_logs", ["organization_id", "event_category", "created_at"])
    op.create_index("ix_audit_resource_category_outcome", "audit_logs", ["resource_id", "event_category", "outcome"])
    op.create_table("failed_external_calls",
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("target_service", sa.String(64), nullable=False), sa.Column("operation", sa.String(128), nullable=False), sa.Column("organization_id", sa.String(128)), sa.Column("scan_id", sa.String(64)), sa.Column("payload", sa.JSON), sa.Column("payload_size_bytes", sa.BigInteger), sa.Column("attempts", sa.Integer, nullable=False), sa.Column("last_error", sa.Text), sa.Column("status", dlq_status, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_dlq_service_status_created", "failed_external_calls", ["target_service", "status", "created_at"])


def downgrade() -> None:
    op.drop_table("failed_external_calls")
    op.drop_table("audit_logs")
    op.drop_table("jobs")
    bind = op.get_bind()
    for enum in (dlq_status, audit_outcome, audit_category, job_status):
        enum.drop(bind, checkfirst=True)
