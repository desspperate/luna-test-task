import hashlib
import hmac

from pydantic import SecretStr


def verify_api_key(provided: SecretStr | None, expected: SecretStr) -> bool:
    if not provided:
        return False
    expected_bytes = expected.get_secret_value().encode()
    provided_bytes = provided.get_secret_value().encode()
    return hmac.compare_digest(provided_bytes, expected_bytes)


def sign_webhook(body: bytes, secret: SecretStr, ts: int) -> str:
    payload = f"{ts}.".encode() + body
    return hmac.new(
        key=secret.get_secret_value().encode(),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()
