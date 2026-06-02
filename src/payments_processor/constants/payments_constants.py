class PaymentsConstants:
    AMOUNT_MAX_DIGITS = 20
    AMOUNT_DECIMAL_PLACES = 4
    DESCRIPTION_MAX_LEN = 1000
    IDEMPOTENCY_KEY_MAX_LEN = 255
    WEBHOOK_URL_MAX_LEN = 2048

    OUTBOX_AGGREGATE_TYPE_MAX_LEN = 64
    OUTBOX_EVENT_TYPE_MAX_LEN = 128
    OUTBOX_ROUTING_KEY_MAX_LEN = 128

    IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
    API_KEY_HEADER = "X-API-Key"
    API_V1_PREFIX = "/api/v1"

    HEALTH_PATH = "/health"
    DOCS_PATHS: frozenset[str] = frozenset({"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"})

    EXCHANGE_PAYMENTS = "payments"
    QUEUE_PAYMENTS_NEW = "payments.new"
    QUEUE_PAYMENTS_DLQ = "payments.dlq"
    QUEUE_PAYMENTS_RETRY_PREFIX = "payments.retry."
    RETRY_TTL_MS_BY_ATTEMPT: tuple[int] = (2_000, 8_000, 32_000)

    PAYMENT_CREATED_ROUTING_KEY = "payment.created"
    PAYMENT_CREATED_EVENT_TYPE = "payment.created"

    PAYMENT_AGGREGATE_TYPE = "payment"
