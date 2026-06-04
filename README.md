# Payments Processor

Asynchronous payment processing microservice. Accepts payment requests over HTTP, processes them through an emulated payment gateway in a background consumer, and notifies the merchant via signed webhook. Implements the Transactional Outbox pattern, idempotency, retry topology, and a DLQ — per the test task spec (`spec.pdf`).

## Quick Start
Use the following command corresponding to your environment:
```shell
# dev
make dev
# prod
make prod
```

API listens on `127.0.0.1:8000`, RabbitMQ management UI on `127.0.0.1:15672`.

Before the first run, generate an `.env`:
```shell
make configure
```
This prompts for the secrets (`PG_PASSWORD`, `RMQ_PASSWORD`, `API_KEY`, `WEBHOOK_SECRET`) and writes the rest from `.env.example`. Migrations run automatically on container start via the API entrypoint.

## Tech Stack
Driven by the spec:
- **FastAPI** + **Pydantic v2** — HTTP write surface, request validation, OpenAPI
- **SQLAlchemy 2.0** (async) + **asyncpg** — DB access
- **PostgreSQL** — source of truth (`payments`, `outbox`)
- **RabbitMQ** + **FastStream** (aio-pika) — broker, consumer framework, retry/DLQ topology
- **Alembic** — migrations
- **Docker** + **docker-compose** — local & prod orchestration (separate `dev` / `prod` profiles)

Supporting libs: `dishka` (DI container shared across the three services), `loguru` (structured JSON logs), `httpx` (webhook delivery), `gunicorn` + `uvicorn` (prod runtime), `pytest` + `pytest-asyncio` + `testcontainers` (tests).

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

## Data Model

### `payments`
| Column            | Type                              | Notes                                          |
|-------------------|-----------------------------------|------------------------------------------------|
| `id`              | `UUID` (UUIDv7) PK                | Time-ordered for index locality                |
| `amount`          | `NUMERIC(20, 4)`                  | `Decimal` end-to-end; rejects floats           |
| `currency`        | `CHAR(3)`                         | `RUB`, `USD`, `EUR`                            |
| `description`     | `VARCHAR(1000) NULL`              |                                                |
| `meta`            | `JSONB NULL`                      | Arbitrary merchant-supplied JSON               |
| `status`          | `ENUM('pending','succeeded','failed')` | Default `pending`                         |
| `idempotency_key` | `VARCHAR(255)`                    | Unique per merchant (currently single-tenant)  |
| `webhook_url`     | `VARCHAR(2048)`                   | Validated `HttpUrl`, SSRF-guarded at delivery  |
| `created_at`      | `TIMESTAMPTZ`                     | Set on insert                                  |
| `updated_at`      | `TIMESTAMPTZ NULL`                | Bumped on every UPDATE                         |
| `processed_at`    | `TIMESTAMPTZ NULL`                | Set when consumer finalizes status             |

### `outbox`
| Column            | Type                              | Notes                                          |
|-------------------|-----------------------------------|------------------------------------------------|
| `id`              | `UUID` (UUIDv7) PK                |                                                |
| `aggregate_type`  | `VARCHAR(64)`                     | `payment`                                      |
| `aggregate_id`    | `UUID`                            | FK-shaped pointer to `payments.id`             |
| `event_type`      | `VARCHAR(128)`                    | `payment.created`, `payment.processed`         |
| `routing_key`     | `VARCHAR(128)`                    | RabbitMQ routing key                           |
| `payload`         | `JSONB`                           | Event body                                     |
| `status`          | `ENUM('pending','published')`     | Default `pending`                              |
| `created_at`      | `TIMESTAMPTZ`                     |                                                |
| `published_at`    | `TIMESTAMPTZ NULL`                | Set by the dispatcher                          |

## API

All endpoints require:
- `X-API-Key: <API_KEY>` — static API key, from `.env`
- `Content-Type: application/json` (writes)

OpenAPI lives at `http://127.0.0.1:8000/docs`.

### `POST /api/v1/payments` — create a payment

Headers:
- `Idempotency-Key: <opaque string up to 255 chars>` (**required**)
- `X-API-Key: <API_KEY>`

Body:
```json
{
  "amount": "1499.90",
  "currency": "USD",
  "description": "Order #4711",
  "meta": {"order_id": "4711", "user_id": "u_42"},
  "webhook_url": "https://merchant.example.com/hooks/payments"
}
```

`amount` **must** be a JSON string (or already a `Decimal`) — floats are rejected to avoid precision loss.

Response — `202 Accepted`:
```json
{
  "payment_id": "0192f8e7-6d31-7b22-8a4f-0c2a0f4f9a01",
  "status": "pending",
  "created_at": "2026-06-04T12:34:56.789012+00:00"
}
```

Error codes:
- `401` — missing / invalid `X-API-Key`
- `409` — same `Idempotency-Key` already used with a different payload
- `422` — schema validation failed
- `202` (replay) — same `Idempotency-Key` + same payload returns the original `payment_id`

Example:
```shell
curl -X POST http://127.0.0.1:8000/api/v1/payments \
  -H "X-API-Key: $API_KEY" \
  -H "Idempotency-Key: 8c0b3f1e-b2c5-4d4d-9c1a-7b1f0e2a4f33" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "1499.90",
    "currency": "USD",
    "description": "Order #4711",
    "meta": {"order_id": "4711"},
    "webhook_url": "https://webhook.site/your-id"
  }'
```

### `GET /api/v1/payments/{payment_id}` — fetch a payment

Headers: `X-API-Key: <API_KEY>`

Response — `200 OK`:
```json
{
  "id": "0192f8e7-6d31-7b22-8a4f-0c2a0f4f9a01",
  "amount": "1499.90",
  "currency": "USD",
  "description": "Order #4711",
  "meta": {"order_id": "4711"},
  "webhook_url": "https://merchant.example.com/hooks/payments",
  "status": "succeeded",
  "idempotency_key": "8c0b3f1e-b2c5-4d4d-9c1a-7b1f0e2a4f33",
  "processed_at": "2026-06-04T12:35:01.456789+00:00",
  "created_at": "2026-06-04T12:34:56.789012+00:00",
  "updated_at": "2026-06-04T12:35:01.456789+00:00"
}
```

Error codes:
- `401` — missing / invalid `X-API-Key`
- `404` — unknown `payment_id`

### Health probes
- `GET /health` — liveness (no auth)
- `GET /ready` — readiness, pings Postgres (no auth); workers additionally check broker connectivity + a heartbeat freshness window

## Message Broker

### Topology
- Main exchange: `payments` (topic)
- DLX: `payments.dlx` (topic)
- Main queue: `payments.new` — bound with `payment.created`; DLX-routed on reject
- Retry queues: `payments.retry.1`, `payments.retry.2`, `payments.retry.3` — per-step TTL `(2s, 8s, 32s)`, dead-letter back to `payments.new` after expiry
- Dead-letter queue: `payments.dlq` — terminal sink for messages that exhausted all 3 retries, tagged with the `x-dlq-reason` header

### Flow
1. API writes the payment + inserts an `outbox` row inside one DB transaction → returns `202`.
2. Outbox dispatcher polls `outbox` rows where `status='pending'`, publishes them to the `payments` exchange with the row's `routing_key`, and marks them `published`. A crash between publish and DB update is safe: the next poll retries publishing (consumer is idempotent on the message-id boundary).
3. The consumer reads `payments.new`:
   - emulates processing for `2–5s` with `~90%` success / `~10%` failure (configurable via `CONSUMER_*` env);
   - writes the final status (`succeeded` / `failed`) + `processed_at`;
   - signs and POSTs a webhook to the merchant URL with HMAC-SHA256.
4. On webhook delivery failure (timeout, 5xx, transport error, SSRF reject):
   - retry attempts 1..3 → republished to `payments.retry.{n}` with the next TTL step (exponential `2s → 8s → 32s`);
   - after attempt 3 fails → republished to `payments.dlq` with `x-dlq-reason`.

### Webhook contract
Headers sent to the merchant URL:
- `X-Signature: sha256=<hex>` — HMAC-SHA256 over `f"{X-Timestamp}.{raw_body}"` keyed by `WEBHOOK_SECRET`
- `X-Timestamp: <unix seconds>` — for replay protection on the merchant side
- `X-Webhook-Id: <uuid>` — stable per attempt; safe to dedup on
- `X-Event-Type: payment.processed`
- `User-Agent: LunaTestTask/1.0`

## Configuration
All runtime config goes through `.env` (loaded by docker-compose). See `.env.example` for the full set; the load-bearing knobs are:
- `API_KEY` — value clients send in `X-API-Key`
- `WEBHOOK_SECRET` — HMAC key for webhook signing
- `WEBHOOK_ALLOW_PRIVATE_HOSTS` — `0` in prod; set to `1` only to point the consumer at `webhook.site` / a local stub
- `CONSUMER_MAX_RETRIES=3`, `CONSUMER_PROCESS_MIN_SECONDS=2`, `CONSUMER_PROCESS_MAX_SECONDS=5`, `CONSUMER_SUCCESS_PROBABILITY=0.9` — match the spec's processing emulation
- `OUTBOX_BATCH_SIZE`, `OUTBOX_POLL_INTERVAL_SECONDS`, `OUTBOX_BACKOFF_INITIAL_SECONDS`, `OUTBOX_BACKOFF_MAX_SECONDS` — dispatcher loop tuning

## Layout
- `make dev` — builds the image locally, mounts `src/payments_processor`, runs every service via `uvicorn --reload`
- `make prod` — pulls `ghcr.io/desspperate/luna-test-task:latest` (built on GitHub Release), runs every service under `gunicorn` with `UvicornWorker`: API uses 4 workers, outbox-dispatcher / consumer pin to 1 worker (singleton broker connection and dispatcher loop — multiple workers would double-publish / double-consume)
- `make configure` — interactive `.env` writer; `make stop` / `make clean` for teardown

## Testing
- `pytest` — unit tests for actions, repositories, signing, SSRF guard
- Integration tests use `testcontainers` to spin up real Postgres + RabbitMQ — no DB mocks
- CI (`.github/workflows`) runs `ruff` (lint), `mypy` (type check), and the full test suite on every push

## Spec coverage
Mapping back to `spec.pdf` requirements:

| Requirement                                        | Where                                                                 |
|----------------------------------------------------|-----------------------------------------------------------------------|
| `payments` + `outbox` tables, Alembic migrations   | `src/payments_processor/models/`, `alembic/versions/`                 |
| `POST /api/v1/payments` (202, Idempotency-Key)     | `routers/payment_router.py`                                           |
| `GET /api/v1/payments/{id}`                        | `routers/payment_router.py`                                           |
| Single consumer doing everything                   | `src/payments_processor/consumer/`                                    |
| `payments.new` queue                               | `constants/payments_constants.py` (`QUEUE_PAYMENTS_NEW`)              |
| Processing emulation 2–5s, 90/10 success/failure   | `CONSUMER_PROCESS_*`, `CONSUMER_SUCCESS_PROBABILITY` envs             |
| Outbox pattern                                     | `outbox_dispatcher/`, `repositories/outbox_repository.py`             |
| Idempotency-Key uniqueness                         | Unique index on `payments.idempotency_key`                            |
| 3 retries with exponential backoff                 | `RETRY_TTL_MS_BY_ATTEMPT = (2_000, 8_000, 32_000)`                    |
| Dead Letter Queue                                  | `payments.dlq` + `x-dlq-reason` header                                |
| Static `X-API-Key` auth on every endpoint          | `middlewares/api_key_middleware.py`                                   |
| Docker / docker-compose with pg + rmq + api + cons | `docker-compose.yml` (`dev` / `prod` profiles)                        |

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
