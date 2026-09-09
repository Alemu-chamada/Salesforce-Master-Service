# Project Context

Use `SALESFORCE_MASTER_SERVICE 3.md` as the source of truth. Preserve the
FastAPI + PostgreSQL + Salesforce Bulk API 2.0 + MinIO architecture. Do not add
Redis, Celery, RabbitMQ, Kafka, Kubernetes, another database, or another object
store. Keep Salesforce credentials out of persisted job data and logs. Job
state transitions must be sequential and persisted through `JobService`.