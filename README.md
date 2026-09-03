# Salesforce Master Service

On-demand Salesforce data extraction, normalization, and publishing service.

Given a Salesforce organization, this service pulls data via **Bulk API 2.0**,
flattens the raw exports into clean relational tables, and stores the resulting
Parquet files in MinIO under a Hive-style partitioned layout. A "Coordinator"
system drives the service through signed HTTP calls. **Status tracking,
crash detection via heartbeats, resume from the last completed stage, a
dead-letter queue, and HMAC-authenticated endpoints** are part of the design.

The implementation is phased. This repository contains the **Phase 1
foundation**: project layout, configuration, database models, FastAPI app +
router scaffolding, service skeletons, health/stats endpoints, Docker packaging,
and an initial test suite. Salesforce connectivity, the actual batch export
pipeline, normalization logic, MinIO uploads, HMAC enforcement, retry and DLQ
behavior, and the full API workflow are implemented in later phases.

## Architecture

```
Coordinator (HMAC-signed HTTP)
        │
        ▼
FastAPI ── routers: scan / batch / normalization / maintenance / key / audit / credentials / public
 │
 ├─ config:  Pydantic BaseSettings (app, db, sf, bulk, minio, resilience, hmac, health)
 ├─ db:      SQLAlchemy engine, sessions, models: Job, AuditLog, FailedExternalCall
 ├─ services:
 │    JobService             state machine + heartbeat + progress
 │    ExtractionService      top-level scan orchestrator
 │    BatchPollingService    submit / poll / download (Phase 2)
 │    BatchFileService       CSV I/O on data/scans/{id}/extracted
 │    NormalizationService   per-object normalizers → JSON/Parquet (Phase 3)
 │    AuditService           fire-and-forget audit_logs inserts
 ├─ salesforce:
 │    SalesforceAuthClient        OAuth JWT Bearer / username-password (Phase 2)
 │    SalesforceBatchAPIClient    Bulk API 2.0 thin wrapper (Phase 2)
 ├─ storage/MinIOClient     partitioned Parquet upload (Phase 3)
 ├─ normalization/*         8 per-object normalizers producing 16 output tables
 ├─ resilience/             retry.py + dlq.py (Phase 2)
 └─ security/hmac.py        dual-key HMAC dependency (Phase 2)
        │
        ▼
 PostgreSQL (jobs / audit_logs / failed_external_calls)   +   MinIO bucket
```

### Data flow (once Phase 2–3 wiring is done)

Salesforce → Bulk API 2.0 query jobs → poll for `JobComplete` → download CSVs
into `data/scans/{scan_id}/extracted/` → parse into in-memory records →
per-object normalizers flatten the records → write Parquet tables → upload to
`salesforce/{table}/glynac_organization_id={org}/processing_date={date}/{table}.parquet`
in MinIO → mark the job `COMPLETED`.

### Job state machine

`PENDING → BATCH_REQUESTED → BATCH_PROCESSING → BATCH_READY → DOWNLOADING →
DOWNLOADED → EXTRACTING → EXTRACTED → NORMALIZING → NORMALIZED →
UPLOADING_TO_MINIO → UPLOADED_TO_MINIO → COMPLETED`.

Side states: `FAILED`, `CANCELLED`.

In-progress states (`BATCH_PROCESSING`, `DOWNLOADING`, `EXTRACTING`,
`NORMALIZING`, `UPLOADING_TO_MINIO`) are heartbeat-eligible for crash detection.

## Technology stack

| Layer | Choice |
|---|---|
| Language | Python ≥ 3.11 |
| Framework | FastAPI + Uvicorn |
| Configuration | Pydantic `BaseSettings` + `.env` |
| Database | PostgreSQL + SQLAlchemy 2.0 + psycopg2 |
| File storage | MinIO (S3-compatible) |
| Normalization output | Parquet via PyArrow + Pandas |
| Auth (incoming) | HMAC-SHA256 signed requests (dual key) |
| Auth (Salesforce) | OAuth 2.0 JWT Bearer flow (preferred) / username-password |
| Resilience | Bounded retries with jitter + dead-letter table |
| Packaging | Single Docker image; Docker Compose for local dev |
| Tests | pytest + httpx `TestClient` |

## Repository layout

```
SALESFORCE_MASTER_SERVICE/
├── src/
│   └── app/
│       ├── main.py                    FastAPI app factory, router wiring, lifespan
│       ├── core/
│       │   ├── config.py              Pydantic BaseSettings (all categories)
│       │   ├── logging_setup.py       JSON / human formatter selection
│       │   └── utils.py               deep_serialize, pagination, safe_get, ...
│       ├── db/
│       │   ├── base.py                Declarative Base
│       │   └── session.py             engine, sessionmaker, get_db, connectivity check
│       ├── models/
│       │   ├── enums.py               JobStatus, Audit enums, DLQStatus
│       │   ├── job.py                 jobs table
│       │   ├── audit_log.py           audit_logs table
│       │   └── failed_external_call.py failed_external_calls table
│       ├── schemas/common.py          Pydantic request/response DTOs
│       ├── api/routes/
│       │   ├── scan.py                start/status/cancel/resume/list/statistics/remove
│       │   ├── batch.py               /batch/info
│       │   ├── normalization.py       normalize + tables + supported-objects
│       │   ├── maintenance.py         cleanup + detect-crashed
│       │   ├── key.py                 /key/verify
│       │   ├── audit.py               /logs + /stats
│       │   ├── credentials.py         /validate-credentials
│       │   └── public.py              /health + /stats
│       ├── services/                  JobService, ExtractionService, Batch*Service, NormalizationService, AuditService skeletons
│       ├── salesforce/                SalesforceAuthClient + SalesforceBatchAPIClient skeletons
│       ├── normalization/normalizers.py  BaseNormalizer + 8 per-object normalizer skeletons + registry
│       ├── storage/minio_client.py    MinIOClient skeleton
│       ├── resilience/                retry.py + dlq.py (Phase 2 placeholders)
│       ├── security/hmac.py           Phase 1 HMAC placeholder dependency
│       └── audit/audit_service.py     non-blocking AuditLog writer
├── tests/                             pytest suite (Phase 1 covered: config+models, API routes, JobService, utils)
├── Dockerfile
├── docker-compose.yml                 app + Postgres 16 + MinIO
├── .env.example
├── .gitignore
├── .dockerignore
└── pyproject.toml
```

## Local setup

### Prerequisites

- Python ≥ 3.11 (with a virtual environment tool of your choice)
- Docker + Docker Compose (optional, for `docker-compose up`)

### Install (native)

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### Configure

Copy `.env.example` to `.env` and fill in the values. For Phase 1, only the
database, MinIO, and HMAC sections are relevant for scaffolding; Salesforce
secrets are used starting in Phase 2. Secrets must **not** be committed; the
included `.env.example` uses placeholder values intentionally.

### Run the service natively

```bash
# Start Postgres + MinIO first, then the app:
uvicorn src.app.main:app --reload --port 8000
```

Health check:

```bash
curl http://localhost:8000/api/health
# {"status":"degraded","app_env":"dev","version":"0.1.0","components":{...}}
```

The Phase 1 health endpoint reports the database reachability check and
degrades for MinIO until the real client is wired in Phase 3.

### Run via Docker Compose

```bash
docker compose up -d --build
curl http://localhost:8000/api/health
```

Compose starts Postgres, MinIO, and the app container on port `8000`.

## Environment configuration reference

All configuration is driven by environment variables via Pydantic
`BaseSettings` in [src/app/core/config.py](src/app/core/config.py). The names
match the categories in the specification exactly:

| Group | Variables |
|---|---|
| App | `APP_ENV`, `LOG_LEVEL`, `APP_NAME`, `API_PREFIX`, `DEBUG` |
| Database | `DATABASE_URL`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` |
| Salesforce | `SF_LOGIN_URL`, `SF_CLIENT_ID`, `SF_CLIENT_SECRET`, `SF_JWT_PRIVATE_KEY_PATH`, `SF_API_VERSION`, `SF_TIMEOUT_SECONDS` |
| Bulk API | `SF_BULK_POLL_INTERVAL_SECONDS`, `SF_BULK_MAX_WAIT_MINUTES`, `SF_BULK_SUPPORTED_OBJECTS` |
| MinIO | `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`, `MINIO_SECURE` |
| Resilience | `EXTERNAL_CALL_MAX_RETRIES`, `EXTERNAL_CALL_RETRY_DELAYS`, `EXTERNAL_CALL_JITTER`, `DLQ_PAYLOAD_MAX_BYTES` |
| HMAC | `HMAC_ENABLED`, `HMAC_SECRET_KEY_CORE`, `HMAC_SECRET_KEY_ENGINEER`, `HMAC_SIGNATURE_MAX_AGE`, `HMAC_CLIENT_CONFIG` |
| Health | `HEALTH_CHECK_DB_ENABLED`, `HEALTH_CHECK_MINIO_ENABLED` |
| Data | `DATA_ROOT_DIR` |

Production guardrails in `config.py` raise startup errors if secrets are still
`REPLACE_ME`, HMAC is disabled, or `DEBUG` is enabled in staging/prod.

## API surface

All routes (except `/api/health` and `/api/stats`) require HMAC-signed headers
`X-SF-Signature`, `X-SF-Timestamp`, `X-SF-Client-ID`, `X-SF-Nonce`. Actual
signature validation is wired in Phase 2; during Phase 1 the dependency acts
as a pass-through so routing tests exercise the same code paths.

| Method | Path | Status in Phase 1 |
|---|---|---|
| POST | `/api/scan/start` | `501 Not Implemented` |
| GET  | `/api/scan/{id}/status` | Returns skeleton status for jobs in the DB |
| POST | `/api/scan/{id}/cancel` | `501 Not Implemented` |
| POST | `/api/scan/{id}/resume` | `501 Not Implemented` |
| GET  | `/api/scan/list` | Returns empty paginated envelope |
| GET  | `/api/scan/statistics` | Returns `counts_by_status: {}` |
| DELETE | `/api/scan/{id}/remove` | `501 Not Implemented` |
| GET  | `/api/batch/info` | ✅ Returns configured settings + supported objects |
| POST | `/api/normalization/{id}/normalize` | `501 Not Implemented` |
| POST | `/api/normalization/{id}/normalize/{object}` | `501 Not Implemented` |
| GET  | `/api/normalization/{id}/tables` | ✅ Empty list |
| GET  | `/api/normalization/supported-objects` | ✅ Static catalog |
| POST | `/api/maintenance/cleanup` | `501 Not Implemented` |
| POST | `/api/maintenance/detect-crashed` | `501 Not Implemented` |
| GET  | `/api/key/verify` | ✅ Placeholder identity response |
| GET  | `/api/audit/logs` | `501 Not Implemented` |
| GET  | `/api/audit/stats` | `501 Not Implemented` |
| POST | `/api/validate-credentials` | `501 Not Implemented` |
| GET  | `/api/health` | ✅ DB check + MinIO placeholder |
| GET  | `/api/stats` | ✅ Uptime + request counters |

## Running tests

```bash
pip install -e ".[dev]"
pytest -q
```

The test suite currently covers:

- Settings loading + Pydantic validators, including the job status enum and
  the transition guardrails.
- FastAPI app startup + routing for `health`, `stats`, `batch/info`,
  `key/verify`, `normalization/supported-objects`, `scan/list`, and
  `scan/statistics`, plus `501` stubs for later phases.
- `JobService` core lifecycle: create, valid/invalid status transitions,
  fail/cancel, heartbeat, progress reporting, and missing-job handling.
- `utils.py` helpers: `deep_serialize`, `calculate_duration`,
  `build_pagination_info`, `chunks`, `safe_get`, `utcnow`.

Test isolation uses an in-memory SQLite engine for the `JobService` tests and
disables DB/MinIO health checks for the API route tests; no running Postgres or
MinIO is required to run `pytest`.

## Scope boundaries

Per the specification this service does **not** include:
- scheduling (a Coordinator calls `/scan/start`)
- post-extract data consumers
- deduplication or change-detection
- PII masking / anonymization / redaction
- message queues or infrastructure beyond Postgres and MinIO
- permanent storage of Salesforce credentials

## Deployment

A single Docker image is built from the `Dockerfile` (multi-stage build,
non-root user, `HEALTHCHECK` on `/api/health`). The deployment target in the
spec is a Nomad task per environment with secrets templated from Vault at
`secrets/data/salesforce/salesforce-master-service-{env}`; no Kubernetes or
additional deployment infrastructure is included in this repository.
