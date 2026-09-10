# Real Salesforce E2E Acceptance Test

This guide is for the final manual test. It does not claim that a real Salesforce run has passed. Use a non-production Salesforce organization and a test organization id.

## Blockers to resolve first

1. `salesforce.key` is currently tracked by Git. Rotate the Salesforce JWT key pair, remove the tracked key from repository history/index, and keep only the replacement local key mounted at `./salesforce.key`. The `.gitignore` entry prevents future accidental addition but does not remove an already-tracked file.
2. The scan workflow reaches `EXTRACTED`; normalization and MinIO upload are a separate API call. The current normalization write routes and `/api/key/verify` apply the HMAC dependency twice, so nonce replay protection can reject those requests. Fix that genuine blocker before expecting `COMPLETED`.

## Prerequisites

- Python 3.11+ and Docker Desktop with Compose.
- A Salesforce External Client App configured for JWT Bearer flow, with the replacement public certificate, authorized user, and API access.
- A local `salesforce.key` matching that certificate. Do not paste its contents into a request or terminal command.
- `.env` populated with the Salesforce login URL and client id, the JWT key path, database/MinIO settings, and non-placeholder HMAC secrets.
- The working directory is the repository root.

Before testing, remove the already-tracked private key from Git while retaining the local file:

```powershell
git rm --cached salesforce.key
git status --short
```

Do not commit `.env` or `salesforce.key`. Rotate any credentials that have previously been exposed.

## Start the system

Use Docker Compose so the app sees the key at the path configured in the container:

```powershell
docker compose up -d --build
docker compose ps
```

The Compose app uses `http://postgres:5432` and `minio:9000` internally, mounts `./salesforce.key` read-only at `/app/salesforce.key`, and listens on `http://localhost:8000`.

## Check health

```powershell
Invoke-RestMethod http://localhost:8000/api/health | ConvertTo-Json -Depth 8
```

Proceed only when `status` is `healthy` and both `database.status` and `minio.status` are `healthy`.

## HMAC request helper

All routes other than `/api/health` and `/api/stats` require signed headers. The canonical string is:

```text
METHOD\nPATH\nUNIX_TIMESTAMP\nNONCE\nSHA256(REQUEST_BODY)
```

The Compose development HMAC values are `coordinator` / `dev-coordinator-secret` for full access and `engineer` / `dev-engineer-secret` for read-only GET access. For native execution, use the corresponding values from `.env` without printing them.

Define this PowerShell helper once. It prints only the API response:

```powershell
function Invoke-SfmsSigned {
    param(
        [ValidateSet('GET','POST','DELETE')][string]$Method,
        [string]$Path,
        [string]$Body = '',
        [string]$ClientId = 'coordinator',
        [string]$Secret = 'dev-coordinator-secret'
    )

    $timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds().ToString()
    $nonce = [guid]::NewGuid().ToString('N')
    $bodyBytes = [Text.Encoding]::UTF8.GetBytes($Body)
    $sha = [Security.Cryptography.SHA256]::Create()
    $bodyHash = [Convert]::ToHexString($sha.ComputeHash($bodyBytes)).ToLowerInvariant()
    $canonical = "$($Method.ToUpperInvariant())`n$Path`n$timestamp`n$nonce`n$bodyHash"
    $hmac = [Security.Cryptography.HMACSHA256]::new([Text.Encoding]::UTF8.GetBytes($Secret))
    $signature = [Convert]::ToHexString($hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($canonical))).ToLowerInvariant()
    $headers = @{
        'X-SF-Signature' = $signature
        'X-SF-Timestamp' = $timestamp
        'X-SF-Client-ID' = $ClientId
        'X-SF-Nonce' = $nonce
    }
    $params = @{ Method = $Method; Uri = "http://localhost:8000$Path"; Headers = $headers }
    if ($Body -ne '') { $params.Body = $Body; $params.ContentType = 'application/json' }
    Invoke-RestMethod @params
}
```

## Verify HMAC and configured objects

```powershell
Invoke-SfmsSigned GET /api/key/verify | ConvertTo-Json
Invoke-SfmsSigned GET /api/batch/info | ConvertTo-Json -Depth 8
Invoke-SfmsSigned GET /api/normalization/supported-objects | ConvertTo-Json -Depth 8
```

The key response should identify `coordinator`, role `full`, and `signature_valid: true`. The configured object list should contain `Account`, `Contact`, `Opportunity`, `OpportunityLineItem`, `Lead`, `Case`, `Task`, `Event`, `Campaign`, and `User`.

## Start a real scan

The endpoint is `POST /api/scan/start`. It returns HTTP 202 and a `scan_id`. The request body must include an organization id and Salesforce credentials. With the server-side JWT key configured, send only the grant type and username:

```powershell
$organizationId = 'e2e-test-org'
$salesforceUsername = 'REPLACE_WITH_AUTHORIZED_SALESFORCE_USERNAME'
$startBody = @{
    organization_id = $organizationId
    salesforce_credentials = @{
        grant_type = 'jwt_bearer'
        username = $salesforceUsername
    }
    # Omit object_names to use all configured objects.
} | ConvertTo-Json -Depth 5 -Compress

$start = Invoke-SfmsSigned POST /api/scan/start $startBody
$scanId = $start.scan_id
$start | ConvertTo-Json -Depth 8
```

Do not include `client_secret`, `password`, `security_token`, or `jwt_private_key` in this request. The response should contain `status: PENDING` and a non-empty `scan_id`.

## Monitor extraction

```powershell
Invoke-SfmsSigned GET "/api/scan/$scanId/status" | ConvertTo-Json -Depth 12
Invoke-SfmsSigned GET "/api/scan/list?organization_id=$organizationId&page=1&page_size=20" | ConvertTo-Json -Depth 12
```

Poll status until `EXTRACTED`, or stop on `FAILED`/`CANCELLED`. The expected extraction progression is `PENDING`, `BATCH_REQUESTED`, `BATCH_PROCESSING`, `BATCH_READY`, `DOWNLOADING`, `DOWNLOADED`, `EXTRACTING`, `EXTRACTED`. Salesforce creates one Bulk API 2.0 query job for every configured object.

## Normalize and upload to MinIO

After status is `EXTRACTED`, the intended request is:

```powershell
$normalizeBody = @{
    output_format = 'parquet'
    save_to_disk = $true
    upload_to_minio = $true
    processing_date = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd')
} | ConvertTo-Json -Compress

Invoke-SfmsSigned POST "/api/normalization/$scanId/normalize" $normalizeBody | ConvertTo-Json -Depth 12
```

This should produce `NORMALIZING`, `NORMALIZED`, `UPLOADING_TO_MINIO`, `UPLOADED_TO_MINIO`, and finally `COMPLETED`. Due to the HMAC double-dependency blocker listed above, this call is not expected to succeed until that blocker is fixed.

## Verify MinIO output

Open the MinIO console at `http://localhost:9001` and inspect bucket `salesforce-data`. The expected key pattern is:

```text
salesforce/{table}/glynac_organization_id={organizationId}/processing_date={yyyy-MM-dd}/{table}.parquet
```

Expected tables are:

| Salesforce object | Parquet tables |
|---|---|
| Account | `accounts`, `account_addresses`, `account_teams` |
| Contact | `contacts`, `contact_roles` |
| Opportunity | `opportunities`, `opportunity_line_items`, `opportunity_contact_roles` |
| Lead | `leads` |
| Case | `cases`, `case_comments` |
| Task/Event | `tasks`, `events` |
| Campaign | `campaigns`, `campaign_members` |
| User | `users` |

The API can also list local normalized files:

```powershell
Invoke-SfmsSigned GET "/api/normalization/$scanId/tables" | ConvertTo-Json -Depth 12
```

## Verify database/job status

```powershell
docker compose exec postgres psql -U sf_master -d sf_master -c "SELECT scan_id, organization_id, status, extracted_at, normalized_at, minio_uploaded_at, completed_at, error_message FROM jobs WHERE scan_id = '$scanId';"
docker compose exec postgres psql -U sf_master -d sf_master -c "SELECT scan_id, batch_job_ids, entity_record_counts, normalization_stats, minio_object_keys FROM jobs WHERE scan_id = '$scanId';"
```

The final row must be `COMPLETED`, with extraction counts, normalization statistics, and MinIO object keys populated. Do not expect credentials in `request_config`; the scan service excludes them before persistence.

## Cancel, resume, list, and remove

Use a separate short-lived scan or cancel a running acceptance scan:

```powershell
Invoke-SfmsSigned POST "/api/scan/$scanId/cancel" | ConvertTo-Json
Invoke-SfmsSigned GET "/api/scan/$scanId/status" | ConvertTo-Json -Depth 12
```

Resume a failed or cancelled scan. After a process restart, credentials must be supplied again; use the same JWT username and grant type, never a private key or client secret in the body:

```powershell
$resumeBody = @{ salesforce_credentials = @{ grant_type = 'jwt_bearer'; username = $salesforceUsername } } | ConvertTo-Json -Compress
Invoke-SfmsSigned POST "/api/scan/$scanId/resume" $resumeBody | ConvertTo-Json
```

Only terminal jobs can be removed. Remove only after preserving the acceptance evidence:

```powershell
Invoke-SfmsSigned DELETE "/api/scan/$scanId/remove" | ConvertTo-Json
Invoke-SfmsSigned GET "/api/scan/list?organization_id=$organizationId&page=1&page_size=20" | ConvertTo-Json -Depth 12
```

## Successful result

The acceptance test is successful only when all configured Salesforce object exports complete, CSV files are downloaded, extraction counts are recorded, all expected Parquet tables are uploaded under the expected MinIO partition, the database job is `COMPLETED`, and no secret appears in logs, database JSON, local output, or Git.

## Troubleshooting

- `401 missing_auth_headers`, `invalid_signature`, or `nonce_replayed`: generate a fresh nonce for every request; sign the exact path and exact UTF-8 body sent; use the coordinator secret for writes.
- `401` from Salesforce: verify the JWT certificate/private-key match, External Client App policy, authorized user, username, client id, and login URL.
- `healthy` but scan fails immediately: inspect `docker compose logs app` for a class/error code only; verify `/app/salesforce.key` exists in the container with `docker compose exec app sh -c "test -f /app/salesforce.key"`.
- `BATCH` failure or timeout: check Salesforce API access, object permissions, Bulk API limits, and `SF_BULK_MAX_WAIT_MINUTES`.
- `EXTRACTED` but no completion: call the normalization endpoint; resolve the documented HMAC double-dependency blocker first.
- MinIO unhealthy or upload failure: check `docker compose ps`, bucket `salesforce-data`, MinIO credentials, and the app's `MINIO_ENDPOINT=minio:9000` setting.
- Database errors: check `docker compose logs postgres`, confirm the app uses `postgres:5432` inside Compose, and rerun `docker compose up -d --build`.

Collect the scan id, final status response, sanitized database row, MinIO key listing, and application error class/code as the acceptance evidence. Never collect tokens, assertions, client secrets, passwords, or private-key contents.