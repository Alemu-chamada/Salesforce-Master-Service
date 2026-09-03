# Salesforce Master Service — What To Build

## 0. Getting Started — Account, Repo & Submission

### Create your account
- Create a GitHub account if you don't already have one (or use your existing one).
- Send your GitHub username to the project contact so you can be invited/granted access as needed.

### Set up your own repository
- Create a new repository named `salesforce-master-service`.
- Initialize it with a `README.md`, a Python `.gitignore`, and this document (saved as `DESIGN.md`).

### Timeline
- Total timeline: **1 month** from kickoff to final submission.
- Suggested milestones:
  - **Week 1** — Project set up, Salesforce test account access, logging into Salesforce works.
  - **Week 2** — Requesting and downloading a data export from Salesforce works.
  - **Week 3** — Turning the downloaded data into clean tables works, for the main record types (Accounts, Contacts, Opportunities, Leads, Cases).
  - **Week 4** — Saving/uploading the finished tables, handling errors gracefully, testing, and final submission.

### How to submit
- Push all code to your repository and make sure it runs from scratch (someone else should be able to clone it and get it running by following your README).
- Include a `README.md` that explains: how to set it up, what settings/credentials it needs, how to run it, and how to run the tests.
- Include a short write-up describing what you built, how it was working (what you tested and confirmed worked), what's incomplete, and anything you weren't able to finish.
- Share the repository link with the project contact ahead of the 1-month deadline.

## 1. What This Service Is, In Plain Terms

This service's only job is to **pull data out of Salesforce on demand and hand it off in a clean, organized form.**

Think of it as a pipeline with one job: given a Salesforce account, go get its data, clean it up, and put it somewhere it can be picked up and used. Nothing about scheduling ("when to run"), and nothing about what happens to the data afterward — this service only handles the extraction and cleanup step.

Another system (a "Coordinator") will be the one calling this service to say "start pulling data for this account", "how's it going", "cancel it", etc. This service just needs to respond correctly to those requests and do the work reliably.

## 2. What Exactly You Need To Build

At a high level, build these pieces:

1. **A way to log into Salesforce** using credentials provided to the service, and get a token that lets you make requests.
2. **A way to request an export of data** from Salesforce for a given account — one request per type of record (Accounts, Contacts, Opportunities, etc.).
3. **A way to check whether that export is ready yet**, and wait/retry until it is (with a sensible timeout so it doesn't wait forever).
4. **A way to download the exported files** once ready, and save them locally.
5. **A way to read those downloaded files** and turn them into usable records in memory.
6. **A way to clean up and reorganize each record type** into simple, consistent tables (e.g., turn a messy nested "Account" record into a flat `accounts` table, a flat `account_addresses` table, etc.).
7. **A way to save the finished tables** as files and upload them to shared storage (MinIO), organized so other systems know where to find them (by account and by date).
8. **A tracking system for each run** ("job"), so that at any point you can ask "what's the status of this run?" and get an accurate answer — including if it crashed partway through and needs to resume instead of restarting from zero.
9. **A small set of API endpoints** so the Coordinator system can start a run, check its status, cancel it, resume it, and list past runs.
10. **Basic security**, so that only the Coordinator (not just anyone on the network) can call this service.
11. **Basic error handling**, so that if Salesforce or the storage system is briefly unavailable, the service retries a few times automatically instead of failing immediately — and if it keeps failing, it records what went wrong somewhere so someone can investigate later, instead of silently losing the request.

That's the entire scope. Everything below just explains each of these in more detail.

## 3. Tech Stack

- **Language/Framework:** Python, using **FastAPI** to build the API
- **Database:** PostgreSQL — to keep track of every run ("job") and its status
- **File storage:** MinIO — where the finished, cleaned-up data gets uploaded
- **Packaging:** Docker, so it can run the same way anywhere

You don't need anything more exotic than this — no message queues, no extra infrastructure beyond a database and a place to store files.

## 4. Step-By-Step: How A Single Run Should Work

1. The Coordinator tells your service: "start pulling data for this Salesforce account."
2. Your service saves a new "job" record so it can track progress, and immediately replies "started" (it doesn't make the Coordinator wait for the whole thing to finish).
3. In the background, your service:
   a. Logs into Salesforce.
   b. Asks Salesforce for an export of each type of record it needs (Accounts, Contacts, Opportunities, Leads, Cases, etc.).
   c. Waits and checks periodically until each export is ready.
   d. Downloads the finished exports.
   e. Reads the downloaded data and reorganizes it into clean tables.
   f. Saves those tables and uploads them to storage.
   g. Marks the job as complete — or as failed, with a reason, if something went wrong.
4. At any point, the Coordinator can ask your service for the status of a job, cancel it, or (if it failed) ask it to resume from wherever it left off rather than starting over.

## 5. What Data To Pull From Salesforce

Build support for at least these record types to start:

- Accounts
- Contacts
- Opportunities (and their line items)
- Leads
- Cases
- Tasks and Events
- Campaigns
- Users

Each one should end up as its own clean table (or a small handful of related tables) after processing.

## 6. API Endpoints You Need To Expose

| What it does | Example endpoint |
|---|---|
| Start a new run for an account | `POST /scan/start` |
| Check the status of a run | `GET /scan/{id}/status` |
| Cancel a run | `POST /scan/{id}/cancel` |
| Resume a failed/cancelled run | `POST /scan/{id}/resume` |
| List past/active runs | `GET /scan/list` |
| Remove a run's records | `DELETE /scan/{id}/remove` |
| Trigger the "clean up the data" step for a run | `POST /normalize/{id}` |
| Check that credentials are valid before starting a run | `POST /validate-credentials` |
| Basic health check (is the service up) | `GET /health` |

You don't need to build much beyond this list — keep the API small and focused.

## 7. Handling Errors Gracefully

- If a call to Salesforce or to storage fails because of a temporary problem (timeout, connection issue, "server busy" response), automatically try again a few times before giving up.
- If it still fails after those retries, don't lose the request — save a record of what failed and why, so it can be looked into later.
- If the service crashes or gets restarted mid-run, it should be able to tell (from its tracking records) that a run was left in an unfinished state, and either resume it or mark it as failed rather than leaving it stuck forever.

## 8. Security

- Only the Coordinator system should be able to call this service — every request coming in should be signed with a shared secret key, and the service should reject anything that isn't signed correctly.
- Credentials used to log into Salesforce should never be permanently stored — use them to get a token, then discard them.

## 9. What NOT To Build

This service does **not** need:
- Any deduplication or "has this record changed" logic — every run just produces a fresh set of tables.
- Any PII masking, anonymization, or redaction of the data — the data is passed through as-is.

Keep the scope limited to: connect → export → download → clean up → store → track status.

---

## 10. Technical Appendix

Everything above is the plain-language version. This section spells out the same system in implementation-level detail.

### 10.1 Architecture Overview

```
Coordinator (calls via signed HTTP)
        │
        ▼
Salesforce Master Service (FastAPI)
        │
        ├── Auth: Salesforce OAuth (JWT Bearer flow / username-password flow)
        ├── Batch export: Salesforce Bulk API 2.0 (SOQL query jobs per object)
        ├── Polling: job status until "JobComplete"
        ├── Download: CSV result files per Bulk API job
        ├── Extraction: parse CSV → in-memory records
        ├── Normalization: flatten Salesforce objects into relational tables
        └── Publish: upload normalized Parquet files to MinIO
```

Each Salesforce object (Account, Contact, Opportunity, Lead, Case, Task, Event, Campaign, User, Opportunity Line Item, etc.) is extracted via its own Bulk API query job, tracked as a sub-unit of the overall scan.

### 10.2 Job Lifecycle / State Machine

A single `Job` row represents one scan (one extraction run for one organization). Status values:

```
PENDING
  → BATCH_REQUESTED
  → BATCH_PROCESSING
  → BATCH_READY
  → DOWNLOADING
  → DOWNLOADED
  → EXTRACTING
  → EXTRACTED
  → NORMALIZING
  → NORMALIZED
  → UPLOADING_TO_MINIO
  → UPLOADED_TO_MINIO
  → COMPLETED
```

Side states: `FAILED`, `CANCELLED`.

In-progress states (`BATCH_PROCESSING`, `DOWNLOADING`, `EXTRACTING`, `NORMALIZING`, `UPLOADING_TO_MINIO`) are the ones eligible for crash detection via heartbeat timeout.

### 10.3 API Endpoints (FastAPI routers)

All endpoints below (except `/health` and `/stats`) require HMAC-signed requests from the Coordinator (`X-SF-Signature`, `X-SF-Timestamp`, `X-SF-Client-ID`, `X-SF-Nonce` headers).

**`scan` router — `/api/scan`**

| Method | Path | Function |
|---|---|---|
| POST | `/scan/start` | `start_scan(request: ScanStartRequest)` — validates payload, creates job, kicks off background workflow, returns 202 with scan id |
| GET | `/scan/{scan_id}/status` | `get_scan_status(scan_id: str)` — returns current job status + pipeline progress |
| POST | `/scan/{scan_id}/cancel` | `cancel_scan(scan_id: str)` — cancels the job locally and best-effort cancels the remote Bulk API job |
| POST | `/scan/{scan_id}/resume` | `resume_scan(scan_id: str)` — resumes a failed/cancelled scan from the last completed stage |
| GET | `/scan/list` | `list_scans(organization_id: str \| None, page: int, page_size: int)` — paginated scan listing |
| GET | `/scan/statistics` | `get_scan_statistics()` — aggregate counts by status |
| DELETE | `/scan/{scan_id}/remove` | `remove_scan(scan_id: str)` — deletes job row + local files (blocked while active) |

**`batch` router — `/api/batch`**

| Method | Path | Function |
|---|---|---|
| GET | `/batch/info` | `get_batch_info()` — returns configured Bulk API settings (objects supported, query defaults) |

**`normalization` router — `/api/normalization`**

| Method | Path | Function |
|---|---|---|
| POST | `/normalization/{scan_id}/normalize` | `normalize_scan(scan_id: str, format: str, save_to_disk: bool, upload_to_minio: bool, processing_date: str \| None)` — runs normalization → save → (optional) MinIO upload |
| POST | `/normalization/{scan_id}/normalize/{object_name}` | `normalize_single_object(scan_id: str, object_name: str)` — normalizes one extracted Salesforce object only |
| GET | `/normalization/{scan_id}/tables` | `list_normalized_tables(scan_id: str)` — lists normalized table files for a scan |
| GET | `/normalization/supported-objects` | `get_supported_objects()` — static catalog of supported Salesforce objects and their output tables |

**`maintenance` router — `/api/maintenance`**

| Method | Path | Function |
|---|---|---|
| POST | `/maintenance/cleanup` | `cleanup_old_scans(days_old: int)` — deletes scans + local files older than N days |
| POST | `/maintenance/detect-crashed` | `detect_crashed_jobs(timeout_minutes: int)` — flags jobs with stale heartbeats as `FAILED` |

**`key` router — `/api/key`**

| Method | Path | Function |
|---|---|---|
| GET | `/key/verify` | `verify_key()` — returns the caller's HMAC client identity + permission profile |

**`credentials`**

| Method | Path | Function |
|---|---|---|
| POST | `/api/validate-credentials` | `validate_credentials(request: SalesforceCredentials)` — validates Salesforce OAuth credentials via a real token grant, without creating a job |

**Public/unauthenticated**

| Method | Path | Function |
|---|---|---|
| GET | `/api/health` | `health()` — liveness/readiness probe (DB + MinIO reachability) |
| GET | `/api/stats` | `service_stats()` — lightweight service-level counters |

**`audit` router — `/api/audit`**

| Method | Path | Function |
|---|---|---|
| GET | `/audit/logs` | `get_audit_logs(org_id, event_category, event_type, outcome, from_date, to_date, page, page_size)` — paginated audit log query |
| GET | `/audit/stats` | `get_audit_stats(window_minutes: int)` — rolling-window audit aggregates |

### 10.4 Core Services & Functions

**`JobService`**
- `create_job(scan_id, organization_id, request_config)` — creates the job row (credentials are never persisted)
- `get_job(scan_id)` — fetches a job by id
- `update_job_status(scan_id, status)` — transitions job status
- `update_batch_info(scan_id, batch_job_ids, batch_status)`
- `update_zip_info` / `update_download_info(scan_id, file_paths, file_sizes)`
- `update_extraction_info(scan_id, extracted_file_counts)`
- `start_normalization(scan_id)` / `complete_normalization(scan_id, stats)`
- `start_minio_upload(scan_id)` / `complete_minio_upload(scan_id, uploaded_paths)`
- `store_entity_record_counts(scan_id, counts_by_object)`
- `fail_job(scan_id, error)` / `cancel_job(scan_id)`
- `detect_crashed_jobs(timeout_minutes)` — heartbeat-based crash detection
- `cleanup_old_jobs(days_old)`
- `get_pipeline_progress(scan_id)` — per-stage timestamps/status for the status endpoint
- `update_heartbeat(scan_id)` — called periodically during long-running stages

**`SalesforceAuthClient`**
- `get_access_token(credentials)` — OAuth 2.0 JWT Bearer flow (preferred) or username-password flow; caches token until near expiry
- `validate_credentials(credentials)` — performs a lightweight token grant + identity call to confirm credentials are valid without starting a scan

**`SalesforceBatchAPIClient` (Bulk API 2.0)**
- `create_query_job(object_name, soql, operation="query")` — creates a Bulk API 2.0 query job for one object
- `get_job_status(job_id)` — polls job state (`UploadComplete`, `InProgress`, `JobComplete`, `Failed`, `Aborted`)
- `get_job_results(job_id, locator=None)` — streams/pages CSV result data
- `abort_job(job_id)` — cancels a running Bulk API job
- `close_job(job_id)` — marks the job closed after successful retrieval

**`BatchPollingService`**
- `submit_batch_jobs(scan_id, objects)` — creates one Bulk API job per configured Salesforce object, persists job ids on the `Job` row
- `check_and_update_status(scan_id)` — polls all sub-jobs, maps Salesforce job states to the internal `JobStatus`
- `poll_until_ready(scan_id, max_wait_minutes, check_interval_seconds)` — async poll loop, refreshes heartbeat each iteration
- `download_results(scan_id)` — downloads and persists CSV result files per object

**`BatchFileService`**
- `save_results_to_disk(scan_id, object_name, csv_stream)` — writes raw CSV to `data/scans/{scan_id}/extracted/`
- `read_csv_file(path, page=None, page_size=None)` — paginated CSV read
- `get_file_info(scan_id)` — lists extracted files + record counts
- `infer_schema(path)` — infers field types from the first N rows
- `cleanup_extracted_files(scan_id)` — removes extracted CSVs after normalization

**`ExtractionService` (top-level orchestrator)**
- `start_scan(request_config)` — creates the job, launches `_execute_batch_workflow` as a background task, returns immediately
- `_execute_batch_workflow(scan_id)` — submit → poll → download → extract → record counts → mark `EXTRACTED`
- `resume_scan(scan_id)` — resumes from the last completed stage (download → extraction → normalization → MinIO upload)
- `cancel_scan(scan_id)` — best-effort remote abort + local cancel
- `get_scan_status(scan_id)`
- `get_scan_statistics()`
- `remove_scan(scan_id)`
- `get_pipeline_info()`

**`NormalizationService` + per-object normalizers**

Base class `BaseNormalizer` provides shared helpers (`safe_get`, `save_to_files`, `get_statistics`).

Per-object normalizers, each implementing `normalize(records) -> dict[str, list[dict]]`:
- `AccountNormalizer` → `accounts`, `account_addresses`, `account_teams`
- `ContactNormalizer` → `contacts`, `contact_roles`
- `OpportunityNormalizer` → `opportunities`, `opportunity_line_items`, `opportunity_contact_roles`
- `LeadNormalizer` → `leads`
- `CaseNormalizer` → `cases`, `case_comments`
- `TaskEventNormalizer` → `tasks`, `events`
- `CampaignNormalizer` → `campaigns`, `campaign_members`
- `UserNormalizer` → `users`

`NormalizationService.normalize_scan(scan_id, output_format, save_to_disk, upload_to_minio, processing_date)`:
1. `job_service.start_normalization(scan_id)` → status `NORMALIZING`
2. Lists extracted files, maps each to the correct normalizer via an object-name registry
3. Runs each normalizer, saves output as JSON or Parquet
4. Aggregates stats, marks `job_service.complete_normalization`
5. If `upload_to_minio`, calls `MinIOClient.upload_normalized_data`, then `job_service.complete_minio_upload`
6. Cleans up local scan data on success

**`MinIOClient`**
- `upload_file(local_path, object_key)`
- `upload_directory(local_dir, prefix)`
- `upload_normalized_data(scan_id, organization_id, processing_date, tables)` — writes to `salesforce/{table_name}/glynac_organization_id={org_id}/processing_date={date}/{table}.parquet`
- `ensure_bucket_exists()`

**`AuditService`**
- `write_audit(event_category, event_type, organization_id, outcome, extra_metadata)` — fire-and-forget insert into `audit_logs`, non-blocking (spawned as a background task so the request path is never delayed)

### 10.5 Resilience — Retry & Dead-Letter Queue

**`retry.py`**
- `is_retryable(exc)` — classifies transient failures (timeouts, connection errors, `408/429/500/502/503/504`)
- `retry_call(fn, max_retries, delays, jitter, op_label)` — bounded-retry executor used around every external call (Salesforce API, MinIO)

**`dlq.py`**
- `write_to_dlq(target_service, operation, payload, attempts, error, organization_id=None, scan_id=None)` — persists an exhausted external call into `failed_external_calls`, scrubbing sensitive fields and capping payload size; never raises
- `scrub_payload(payload)` — redacts sensitive keys before persisting
- Used around every call to the Salesforce API and MinIO

### 10.6 HMAC Authentication

Dual-key scheme:
- **Coordinator key** — full access (GET/POST/DELETE)
- **Engineer/read-only key** — GET-only, for inspection endpoints
- Required headers: `X-SF-Signature`, `X-SF-Timestamp`, `X-SF-Client-ID`, `X-SF-Nonce`
- Canonical string: `METHOD\nPATH\nTIMESTAMP\nNONCE\nSHA256(BODY)`, signed with HMAC-SHA256
- Nonce replay protection, timestamp freshness window, and audit logging on every auth outcome (success, missing header, expired timestamp, invalid signature, replay, unauthorized)
- Implemented as a FastAPI dependency (`Depends(hmac_auth_required)`) applied per-router

### 10.7 Data Models

**`Job` (`jobs` table)**

Core identity/status/timing columns, plus per-stage columns:
- Batch fields: `batch_job_ids` (JSON list, one per Salesforce object), `batch_status`, `batch_requested_at`
- Download fields: `downloaded_at`, `file_paths`, `file_sizes`
- Extraction fields: `extracted_at`, `entity_record_counts`
- Normalization fields: `normalized_at`, `normalization_stats`
- MinIO fields: `minio_uploaded_at`, `minio_object_keys`
- `last_heartbeat` — used for crash detection

**`AuditLog` (`audit_logs` table)**

`event_category`, `event_type`, `actor_client_id`, `actor_role`, `organization_id`, `entity_type`, `resource_type`, `resource_id`, `http_method`, `endpoint`, `request_ip`, `status_code`, `outcome`, `severity`, `error_detail`, `extra_metadata`, `created_at`.

**`FailedExternalCall` (`failed_external_calls` table)**

`target_service`, `operation`, `organization_id`, `scan_id`, `payload` (scrubbed/capped JSON), `attempts`, `last_error`, `status`, `created_at`.

### 10.8 Config

Environment-driven config (`Settings` via Pydantic `BaseSettings`), grouped as:
- App metadata (`APP_ENV`, `LOG_LEVEL`)
- Database (`DATABASE_URL`, pool size)
- Salesforce API (`SF_LOGIN_URL`, `SF_CLIENT_ID`, `SF_CLIENT_SECRET`/JWT key path, `SF_API_VERSION`, timeouts, rate limits)
- Bulk API settings (`SF_BULK_POLL_INTERVAL_SECONDS`, `SF_BULK_MAX_WAIT_MINUTES`, supported object list)
- MinIO (`MINIO_ENDPOINT`, `MINIO_BUCKET`, credentials)
- Resilience (`EXTERNAL_CALL_MAX_RETRIES`, `EXTERNAL_CALL_RETRY_DELAYS`, `EXTERNAL_CALL_JITTER`, `DLQ_PAYLOAD_MAX_BYTES`)
- HMAC (`HMAC_ENABLED`, `HMAC_SECRET_KEY_CORE`, `HMAC_SECRET_KEY_ENGINEER`, `HMAC_SIGNATURE_MAX_AGE`, `HMAC_CLIENT_CONFIG`)
- Health check flags

Environment-specific validation (staging/production) should fail fast at startup if secrets are placeholder values, HMAC is disabled, or DEBUG is enabled in production.

### 10.9 Deployment

Single Docker image, deployed to Nomad in dev/stage/prod, one task per environment, health check on `/api/health`, secrets templated from Vault (`secrets/data/salesforce/salesforce-master-service-{env}`).

### 10.10 Utils

- `deep_serialize(obj)` — recursively converts Decimals, UUIDs, Enums, and datetimes into JSON-safe structures for API responses
- `calculate_duration(start, end)` — ISO datetime diff in seconds for job duration reporting
- `build_pagination_info(page, page_size, total)` — standard pagination envelope
- `Encrypter` — optional Fernet-based symmetric encryption utility for any sensitive config blob that must be stored at rest
