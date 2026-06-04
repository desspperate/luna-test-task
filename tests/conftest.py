import os

os.environ.setdefault("PG_USER", "test")
os.environ.setdefault("PG_PASSWORD", "test")
os.environ.setdefault("PG_DB", "test")
os.environ.setdefault("PG_DRIVER", "postgresql+asyncpg")
os.environ.setdefault("PG_HOST", "localhost")
os.environ.setdefault("PG_PORT", "5432")

os.environ.setdefault("RMQ_USER", "test")
os.environ.setdefault("RMQ_PASSWORD", "test")
os.environ.setdefault("RMQ_HOST", "localhost")
os.environ.setdefault("RMQ_PORT", "5672")
os.environ.setdefault("RMQ_VHOST", "/")

os.environ.setdefault("FASTAPI_TITLE", "Payments Processor Tests")
os.environ.setdefault("DEBUG", "1")
os.environ.setdefault("LOGURU_LEVEL", "DEBUG")
os.environ.setdefault("API_KEY", "test-api-key-must-be-32-chars-long")

os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret-32-chars-long!")
os.environ.setdefault("WEBHOOK_TIMEOUT_SECONDS", "5")
os.environ.setdefault("WEBHOOK_ALLOW_PRIVATE_HOSTS", "0")

os.environ.setdefault("OUTBOX_BATCH_SIZE", "100")
os.environ.setdefault("OUTBOX_POLL_INTERVAL_SECONDS", "1")
os.environ.setdefault("OUTBOX_BACKOFF_INITIAL_SECONDS", "2")
os.environ.setdefault("OUTBOX_BACKOFF_MAX_SECONDS", "60")

os.environ.setdefault("CONSUMER_PREFETCH_COUNT", "10")
os.environ.setdefault("CONSUMER_MAX_RETRIES", "3")
os.environ.setdefault("CONSUMER_PROCESS_MIN_SECONDS", "2")
os.environ.setdefault("CONSUMER_PROCESS_MAX_SECONDS", "5")
os.environ.setdefault("CONSUMER_SUCCESS_PROBABILITY", "0.9")
