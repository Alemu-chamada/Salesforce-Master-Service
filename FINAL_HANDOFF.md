# Salesforce Master Service Final Handoff

## Scope and evidence rule

`SALESFORCE_MASTER_SERVICE 3.md` is the source of truth for this review. A
requirement is marked verified only when repository code and an executable test
or other direct evidence support the claim. Mocked Salesforce/MinIO tests are
identified as local verification; they are not live integration evidence.

## Compliance summary

The service implements the principal FastAPI, Salesforce Bulk API, job
tracking, normalization, MinIO, HMAC, retry, audit, Docker, and migration
surfaces. The latest local quality gate is green: 129 tests passed, Ruff
passed, Mypy passed, Python compilation passed, Docker Compose configuration
passed, and `git diff --check` passed.

Runtime credential re-supply for restart-safe resume, startup stale-job detection,
heartbeat refresh, separate child-object extraction, atomic result downloads,
persistent DLQ wiring, and
catalog accuracy are implemented and locally tested. Live
Salesforce, MinIO, PostgreSQL, Docker Compose, and Nomad/Vault validation also
remain pending because those services or credentials were not available in
this workspace.

## Major requirement matrix

| Requirement | Status | Evidence or remaining work |
|---|---|---|
| Python/FastAPI service | ✅ Implemented/verified | `pyproject.toml`, `src/app/main.py`; app and route tests pass. |
| PostgreSQL job database | ⚠️ Implemented but live verification pending | SQLAlchemy models, session setup, and Alembic migration exist; no live production database run in this session. |
| MinIO output storage | ⚠️ Implemented but live verification pending | `MinIOClient` and partition-key unit test exist; no live MinIO upload was performed. |
| Docker packaging and Compose topology | ⚠️ Implemented but live verification pending | `Dockerfile` and `docker-compose.yml` are present and Compose syntax was checked; Docker daemon was unavailable for startup verification. |
| Salesforce JWT/password authentication | ⚠️ Implemented but live verification pending | Mocked auth tests pass; real OAuth and identity lookup need a Salesforce org. |
| Bulk API 2.0 job creation, polling, pagination, download, abort, close | ⚠️ Implemented but live verification pending | Mocked client tests cover these paths; live Bulk API behavior is unverified. |
| Required object coverage: Account, Contact, Opportunity, Lead, Case, Task, Event, Campaign, User | ⚠️ Implemented but live verification pending | Queries and normalizers exist, but comprehensive live extraction is absent. |
| Opportunity line items, contact roles, case comments, campaign members | ⚠️ Implemented but live verification pending | Each child object has its own Bulk API query and normalizer; live Salesforce relationship permissions/data remain environment-dependent. |
| CSV extraction and local file persistence | ✅ Implemented/verified | `BatchFileService` and mocked end-to-end extraction test pass. |
| Normalization to relational table families | ⚠️ Implemented but live verification pending | Normalizers and Parquet tests exist; live output shape and row availability remain environment-dependent. |
| Hive-style MinIO path by organization/date | ✅ Implemented/verified | Unit test verifies `salesforce/{table}/glynac_organization_id={org}/processing_date={date}/...`. |
| Persisted job lifecycle and progress | ✅ Implemented/verified | State transition, progress, lifecycle, and API-boundary tests pass. |
| Background start and status API | ✅ Implemented/verified | `POST /api/scan/start`, status, list, statistics, and pipeline tests pass locally. |
| Cancel and best-effort Salesforce abort | ⚠️ Implemented but live verification pending | Code and local tests exist; live remote abort is unverified. |
| Resume from a failed/cancelled stage | ⚠️ Implemented but live verification pending | Resume accepts fresh Salesforce credentials after a restart, uses them only in memory, and never persists them; live restart behavior is unverified. |
| Crash detection by heartbeat | ⚠️ Implemented but live verification pending | `JobService.detect_crashed_jobs` runs at startup and has a unit test; normalization and MinIO upload refresh heartbeats locally, but live restart behavior is unverified. |
| Automatic startup crash handling | ✅ Implemented/verified | Application lifespan invokes stale-job detection and a startup recovery regression test passes. |
| HMAC signed requests, timestamp, nonce, body integrity, audit | ✅ Implemented/verified | HMAC tests cover valid signatures, missing headers, replay, body tampering, and role rejection. |
| Coordinator full access and engineer read-only access | ✅ Implemented/verified | Read-only routers use `hmac_auth_readonly`; write routes require `hmac_auth_required`; role tests pass. |
| Credentials excluded from persistent job records | ✅ Implemented/verified | `ExtractionService` removes `salesforce_credentials` before `request_config` persistence; scrubbing tests exist. |
| Credentials discarded after use | ✅ Implemented/verified | Workflow cleanup removes runtime credentials in all terminal/error paths; persisted job config excludes them. |
| Bounded retries with jitter | ✅ Implemented/verified | Retry classification and exhausted-retry tests pass. |
| Persistent DLQ for exhausted external calls | ✅ Implemented/verified | Production external-call failure paths pass the session factory; scrubbed persistence is covered by tests. |
| Audit logs and audit statistics | ✅ Implemented/verified | Audit service, routes, and API-boundary assertions are present. |
| Health and service stats endpoints | ✅ Implemented/verified | `/api/health` and `/api/stats` are implemented and covered locally. |
| Production/staging configuration guardrails | ⚠️ Implemented but live verification pending | Settings reject placeholder secrets, disabled HMAC, or production DEBUG; deployment environment values are not configured here. |
| Alembic schema deployment | ⚠️ Implemented but live verification pending | Migration and `alembic upgrade head` workflow exist; production PostgreSQL execution remains pending. |
| Nomad/Vault deployment reference | ⚠️ Implemented but live verification pending | Nomad job includes one Docker task, Vault templating, and `/api/health`; no cluster/Vault validation occurred. |
| No extra queues/infrastructure, scheduling, deduplication, or PII masking | ✅ Implemented/verified | The implementation stays within the specification scope. |

## Features implemented and verified locally

- FastAPI application factory and required route groups.
- HMAC-SHA256 canonical signing, freshness, nonce replay protection, body
  integrity, coordinator/full and engineer/read-only roles, and auth auditing.
- Salesforce username/password and JWT Bearer client flows under mocked HTTP.
- Bulk API 2.0 request, status, pagination, download, abort, and close client
  behavior under mocked HTTP.
- Job state transitions, persisted progress fields, heartbeats, cancellation,
  listing, statistics, and stale-job detection.
- CSV persistence and mocked extraction through normalization to Parquet.
- Object normalizer registry for the primary Salesforce object families.
- MinIO client behavior and required Hive-style object key construction.
- SQLAlchemy models, initial Alembic migration, Docker packaging metadata, and
  Compose configuration.

## Automated test results

Recorded local results from the project virtual environment:

- `pytest -q`: **129 passed, 1 warning**
- `ruff check .`: **passed**
- `mypy src tests --hide-error-context --no-error-summary`: **passed**
- `python -m compileall -q .`: **passed**

Important test scope limitation: Salesforce and MinIO behavior is tested with
not prove credentials, network access, Salesforce permissions, MinIO bucket
access, or production data shape.

## Live environment items not yet verified

- Salesforce OAuth against a real sandbox or production org.
- Bulk API permissions, object visibility, query compatibility, and real result
  pagination.
- Real MinIO bucket creation and Parquet upload/download.
- PostgreSQL startup, migration application, connection pooling, and recovery.
- Docker image build and live Compose startup. The attempted command could not
  connect to the Docker Desktop Linux engine in this environment.
- Nomad scheduling, Vault secret rendering, service registration, and health
  checks.
- Production load, timeout, retry, and restart behavior.

## Manual setup still required

1. Start a reachable PostgreSQL instance and apply `alembic upgrade head`.
2. Start a reachable MinIO instance and provide endpoint, access key, secret,
   bucket, and secure/TLS settings.
3. Create or obtain a Salesforce Connected App and sandbox/production org
   credentials. Configure the JWT private key or username/password flow as
   appropriate.
4. Configure production/staging values for `APP_ENV`, `DEBUG`, HMAC keys,
   Salesforce settings, database URL, MinIO settings, retry settings, and
   supported objects. Do not commit `.env` or private keys.
5. For Nomad deployment, build/publish the single Docker image and configure
   the Vault policy and secret path expected by the job specification.

## Known limitations

- Resume after a process restart requires the Coordinator to re-supply raw
  Salesforce credentials in the resume request. They are used only in memory,
  excluded from job records, and cleared after the workflow ends.
- Nonce replay protection is process-local; multiple service instances would
  need shared replay state if that deployment requirement is introduced.
- The current startup path calls `Base.metadata.create_all`; production still
  requires an explicit migration step and operational migration policy.
- Child objects are queried independently rather than through nested parent
  SOQL. Live Salesforce permissions and data determine whether child tables
  contain rows.
- Nomad/Vault files are deployment references, not evidence of a live cluster
  deployment.

## Exact steps for final real Salesforce testing

1. Prepare a dedicated Salesforce sandbox or test org with a Connected App,
   API access, Bulk API access, and permissions for Account, Contact,
  Opportunity, OpportunityLineItem, OpportunityContactRole, Lead, Case,
  CaseComment, Task, Event, Campaign, CampaignMember, User, and the required
  Salesforce permissions.
2. Configure the service with the sandbox login URL, API version, OAuth values,
   JWT key path or password-flow values, and conservative timeout/poll settings.
3. Start PostgreSQL and MinIO, create the configured bucket, and run
   `alembic upgrade head`.
4. Start the service and call `GET /api/health`. Confirm both database and
   MinIO components are healthy.
5. Generate an HMAC request using the exact canonical string
   `METHOD\\nPATH\\nTIMESTAMP\\nNONCE\\nSHA256(BODY)`. Call
   `POST /api/validate-credentials` and confirm a real token grant and identity
   lookup succeed. Never place raw credentials in job metadata.
6. Call `POST /api/scan/start` for a small object set. Confirm the immediate
   202 response contains a scan id and that the persisted job contains no raw
   Salesforce credentials.
7. Poll `GET /api/scan/{scan_id}/status` until the scan reaches the available
   extraction stage. Verify Salesforce batch ids, heartbeat updates, result
   files, record counts, and failure details.
8. Call the normalization endpoint with Parquet output and MinIO upload
   enabled. Verify local tables, row counts, and MinIO keys under
   `salesforce/{table}/glynac_organization_id={org}/processing_date={date}/`.
9. Verify the required child tables contain records where the Salesforce test
   data has them: opportunity line items/contact roles, case comments, and
   campaign members.
10. Exercise cancel, remote abort, retry exhaustion/DLQ persistence, stale
    heartbeat detection, resume, audit queries, and removal on disposable test
    jobs. Capture request ids, scan ids, statuses, and MinIO object listings as
    deployment evidence.
11. Restart the service while a disposable job is active. Confirm startup
  marks stale heartbeat jobs failed, then call `POST /api/scan/{scan_id}/resume`
  with a fresh `salesforce_credentials` object. Confirm the job resumes and
  raw credentials are absent from the persisted record.

## Production deployment requirements from the specification

- Deploy one Docker image to Nomad in dev, stage, and prod.
- Run one service task per environment unless an approved deployment design
  changes that constraint.
- Use PostgreSQL for job, audit, and failed-external-call persistence.
- Use MinIO for normalized Parquet output.
- Configure the Nomad HTTP health check at `/api/health`.
- Render secrets from Vault at
  `secrets/data/salesforce/salesforce-master-service-{env}`.
- Set production/staging guardrails: real Salesforce and HMAC secrets,
  `HMAC_ENABLED=true`, and `DEBUG=false`.
- Apply Alembic migrations before serving traffic and maintain a rollback/
  backup procedure for PostgreSQL and MinIO.
- Do not add Redis, Celery, RabbitMQ, Kafka, Kubernetes, or other infrastructure
  outside the specification.
- Do not persist Salesforce credentials or commit `.env`, private keys, or
  other secrets.

## Remaining approval items

No additional code-level gaps are identified against the specification. Live
Salesforce relationship permissions/data, production PostgreSQL/MinIO,
Nomad/Vault deployment, and private-key history rotation remain operational
validation or security tasks outside automated repository verification.