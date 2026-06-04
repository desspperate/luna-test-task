## Quick Start
Use the following command corresponding to your environment:
```shell
# dev
make dev
# prod
make prod
```

API listens on `127.0.0.1:8000`, RabbitMQ management UI on `127.0.0.1:15672`.

## Architecture
- Postgres is the source of truth for payment state and the Outbox table
- RabbitMQ delivers `payment.created` events to the consumer and feeds the retry/DLQ topology
- Three independent services share the same image and DI container:
  - **API** — FastAPI write surface (`POST /api/v1/payments`, `GET /api/v1/payments/{id}`); idempotent via `Idempotency-Key`, guarded by a static `X-API-Key`
  - **Outbox Dispatcher** — single-process loop that polls `outbox`, publishes to RabbitMQ, and marks rows `published` in the same transaction window
  - **Consumer** — FastStream-based worker that emulates processing, sends signed webhooks, and routes failures to retry / DLQ
- Cross-system consistency:
  - **Transactional Outbox** — `INSERT INTO outbox` happens in the same DB transaction as the payment write; the dispatcher publishes to RabbitMQ asynchronously, so a crash never leaves "payment created in DB but no event"
  - **Idempotency** — `idempotency_key` is uniquely indexed per merchant; replays return the original payment instead of creating a duplicate
  - **At-least-once + retry topology** — failed webhook deliveries are republished to `payments.retry.{n}` with per-step TTL; exhausted retries land in the DLQ with the `x-dlq-reason` header
  - **Webhook integrity** — HMAC-SHA256 over `timestamp.body`, SSRF guard refuses private/loopback hosts unless `WEBHOOK_ALLOW_PRIVATE_HOSTS=1` (dev only)
- All three services expose `/health` (liveness) and `/ready` (DB ping); workers additionally track a heartbeat so a stuck loop fails its probe

## Layout
- `make dev` — builds the image locally, mounts `src/payments_processor`, runs every service via `uvicorn --reload`
- `make prod` — pulls `ghcr.io/desspperate/luna-test-task:latest` (built on GitHub Release), runs every service under `gunicorn` with `UvicornWorker`: API uses 4 workers, outbox-dispatcher / consumer pin to 1 worker (singleton broker connection and dispatcher loop — multiple workers would double-publish / double-consume)
- `make configure` — interactive `.env` writer; `make stop` / `make clean` for teardown

## What I'd add for production
The scope here is intentionally narrow. In a real fintech setting the following would all earn their seat:

- **Observability**
  - SigNoz (self-hosted) + OpenTelemetry auto-instrumentation for FastAPI / SQLAlchemy / aio-pika / httpx — distributed traces stitching `API → outbox → dispatcher → consumer → webhook`
  - Prometheus exporters for queue depth, retry/DLQ counts, outbox lag (`head − cursor`), webhook latency histograms; Grafana dashboards + Alertmanager rules (DLQ growth, dispatcher heartbeat stale, p99 webhook latency)
  - Structured JSON logs already in place — ship via Vector/Fluent Bit to Loki or ClickHouse; correlate by `payment_id` / `trace_id`
  - Sentry for uncaught exceptions with PII scrubbers
- **Resilience & safety nets**
  - Real DLQ consumer with replay tooling (operator UI / CLI), poison-message quarantine
  - Circuit breaker around webhook delivery (e.g. `purgatory`) so a single broken merchant doesn't saturate retry queues
  - Outbox dispatcher leader election (Postgres advisory lock or Redis-based) so horizontal scaling doesn't double-publish
  - `pg_partman` partitioning on `payments` and `outbox` by month; archival job for `published` outbox rows
- **Security & compliance**
  - mTLS between services, secret rotation via Vault / AWS Secrets Manager (no `.env` in prod)
  - Webhook signing with key rotation (`kid` header), replay protection window enforced strictly
  - Per-merchant API keys with scopes, rate limiting at the edge (Envoy / Kong) and per-key quotas in app
  - PCI-DSS-aware logging filters (no PAN, no CVV anywhere in the pipeline), audit log on a separate immutable store
  - SBOM + signed images (cosign), Trivy / Grype in CI, Dependabot
- **Data & money correctness**
  - Double-entry ledger as the canonical store (the current `payments` table becomes a projection); reconciliation jobs against PSP statements
  - Money as `Decimal` end-to-end (already true here) + currency-aware rounding modes per scheme
  - Exactly-once webhook delivery via consumer-side dedup table keyed by `webhook_id`
- **Delivery**
  - Helm chart / Kustomize manifests, HPA on RabbitMQ queue depth, PDB for the API
  - Blue/green or canary via Argo Rollouts; DB migrations gated by `safe_migrations` style checks (no destructive DDL in the same release as code)
  - Load tests in CI (k6) with SLOs as pass/fail gates
  - Chaos drills: kill the dispatcher mid-batch, partition RabbitMQ, drop Postgres — verify no payment is lost or duplicated
