# Salesforce Master Service Project State

## Purpose and source of truth

This is an on-demand FastAPI service that authenticates with Salesforce, exports
supported objects through Bulk API 2.0, extracts CSV data, normalizes it into
relational tables, and publishes Parquet data to MinIO. The authoritative
requirements are in `SALESFORCE_MASTER_SERVICE 3.md`.

## Current phases

The implementation covers the main extraction, normalization, storage,
resilience, security, API, audit, migration, and deployment-reference scope.
Local automated validation is green, but this is not a claim of complete
production compliance. The final audit identified code-level gaps in
DLQ persistence wiring, child relationship extraction, and object catalog
accuracy. Credential re-supply for restart-safe resume, startup crash
detection, and stage heartbeat refresh are implemented and tested.

## Architecture and important files

The runtime uses FastAPI, SQLAlchemy/PostgreSQL, Salesforce OAuth and Bulk API
2.0, local scan files, and MinIO. No queues or additional infrastructure are
used. `ExtractionService` orchestrates `BatchPollingService` and
`BatchFileService`; `NormalizationService` uses the registry in
`src/app/normalization/normalizers.py`; `JobService` owns persisted lifecycle
updates.

## Database and lifecycle

Models are `Job`, `AuditLog`, and `FailedExternalCall`. The lifecycle is:

`PENDING -> BATCH_REQUESTED -> BATCH_PROCESSING -> BATCH_READY -> DOWNLOADING -> DOWNLOADED -> EXTRACTING -> EXTRACTED -> NORMALIZING -> NORMALIZED -> UPLOADING_TO_MINIO -> UPLOADED_TO_MINIO -> COMPLETED`

`FAILED` and `CANCELLED` are terminal side states. In-progress stages use
`last_heartbeat` for crash detection.

## Integration status

Salesforce authentication supports JWT Bearer and username/password grants with
near-expiry in-memory caching. Bulk API creation, polling primitives, result
pagination, abort, close, HTTP mapping, and timeouts are implemented.

CSV extraction writes to `data/scans/{scan_id}/extracted/`. Normalizers produce
the required table families and JSON or Parquet files. MinIO uploads use the
required Hive-style partition path. Retry and DLQ helpers are integrated around
OAuth, Bulk submission/status/result download/close/abort, and MinIO uploads and
bucket checks. Exhausted retryable calls include scrubbed context and HTTP
status when available.

HMAC-SHA256 protects non-public routes using coordinator and engineer keys,
timestamp freshness, nonce replay protection, and nonblocking audit writes.
Read-only routes accept the engineer key; write routes require the coordinator
key.

## Compliance gaps requiring code changes

- Resume after process restart requires the Coordinator to re-supply Salesforce
  credentials in the resume request. Raw credentials are not persisted, and
  runtime credentials are cleared after workflow completion, failure, or
  cancellation.
- Production retry failure paths call `write_to_dlq` without a database factory,
  so exhausted external calls may be logged instead of persisted to the DLQ.
- The supported-object registry reports the shared `TaskEvent` normalizer and
  does not accurately expose separate `Task`, `Event`, and
  `OpportunityLineItem` outputs.
- SOQL queries do not request the child relationships needed for opportunity
  line items/contact roles, case comments, and campaign members. The separate
  `OpportunityLineItem` query is also mapped to the opportunity normalizer.

## Known limitations and environment-pending validation

- Credentials are intentionally never persisted. Resume after a process restart
  cannot re-authenticate unless the Coordinator supplies credentials again.
- Nonce replay storage is process-local and should be replaced with shared state
  only if deployment requirements change; the specification forbids extra queue
  infrastructure, so this remains an operational consideration.
- A Nomad/Vault reference job is present under `deploy/nomad`; it has not been
  run against a real cluster.
- Alembic initial migration has been applied successfully to a disposable
  PostgreSQL 16 container; production PostgreSQL remains unverified.
- The API-boundary pipeline test uses injected Salesforce/MinIO fakes; live
  Salesforce and MinIO remain unverified here.
- Startup invokes stale-job detection using the existing heartbeat timeout, and
  normalization plus MinIO upload refresh the heartbeat at stage boundaries and
  during per-object processing. Live restart behavior remains unverified.
- Docker image metadata and Compose syntax were inspected, but live Compose
  startup was not verified. The attempted `docker compose up -d --build`
  command could not connect to the Docker Desktop Linux engine in this
  environment.
- Nomad and Vault CLI validators are unavailable in this environment.
- Salesforce and MinIO integration tests use mocks; production connectivity must
  be verified in the deployment environment.

## Verification

Recorded local verification in the project `.venv`:

- `pytest -q` — `123 passed, 3 warnings`
- `ruff check .` — passed
- `mypy src tests --hide-error-context --no-error-summary` — passed
- `python -m compileall -q .` — passed

These checks verify local code paths and mocked/fake external integrations.
They do not verify live Salesforce, MinIO, PostgreSQL, Docker Compose, or
Nomad/Vault behavior. See `FINAL_HANDOFF.md` for the requirement-by-requirement
status and the exact final testing procedure.