import hmac

from pydantic import SecretStr


def verify_api_key(provided: SecretStr | None, expected: SecretStr) -> bool:
    if not provided:
        return False
    expected_bytes = expected.get_secret_value().encode()
    provided_bytes = provided.get_secret_value().encode()
    return hmac.compare_digest(provided_bytes, expected_bytes)
