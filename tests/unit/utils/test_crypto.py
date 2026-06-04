import hashlib
import hmac

import pytest
from pydantic import SecretStr

from payments_processor.utils import sign_webhook, verify_api_key


EXPECTED_KEY = SecretStr("supersecret-correct-key-value-32")


class TestVerifyApiKey:
    def test_accepts_matching_key(self) -> None:
        assert verify_api_key(
            provided=SecretStr("supersecret-correct-key-value-32"),
            expected=EXPECTED_KEY,
        ) is True

    @pytest.mark.parametrize(
        ("provided", "reason"),
        [
            (None, "missing header"),
            (SecretStr(""), "empty string"),
            (SecretStr("supersecret"), "same prefix, shorter"),
            (SecretStr("supersecret-correct-key-value-32-extra"), "same prefix, longer"),
            (SecretStr("supersecret-correct-key-value-XX"), "single char mismatch"),
            (SecretStr("X"), "unrelated short value"),
        ],
    )
    def test_rejects_non_matching_input(
        self, provided: SecretStr | None, reason: str,
    ) -> None:
        _ = reason  # documents the case
        assert verify_api_key(provided=provided, expected=EXPECTED_KEY) is False

    def test_distinguishes_identical_length_but_different_value(self) -> None:
        """Constant-time comparison must reject same-length non-matching values
        (not bail early on length alone)."""
        a = SecretStr("A" * 32)
        b = SecretStr("B" * 32)
        assert verify_api_key(provided=a, expected=b) is False


class TestSignWebhook:
    def test_matches_hmac_sha256_of_dot_separated_payload(self) -> None:
        """Signature must be HMAC-SHA256 over `<ts>.<body>` with the secret."""
        secret = SecretStr("s3cret")
        ts = 1700000000
        body = b'{"a":1}'

        expected = hmac.new(
            key=b"s3cret",
            msg=b"1700000000." + body,
            digestmod=hashlib.sha256,
        ).hexdigest()

        assert sign_webhook(body=body, secret=secret, ts=ts) == expected

    def test_returns_lowercase_hex_of_32_bytes(self) -> None:
        sig = sign_webhook(body=b"test", secret=SecretStr("abc"), ts=1)
        assert len(sig) == 64
        assert sig == sig.lower()
        bytes.fromhex(sig)  # raises if not valid hex

    def test_is_deterministic_for_same_inputs(self) -> None:
        first = sign_webhook(body=b"x", secret=SecretStr("k"), ts=42)
        second = sign_webhook(body=b"x", secret=SecretStr("k"), ts=42)
        assert first == second

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ((b"x", SecretStr("k"), 1), (b"x", SecretStr("k"), 2)),  # ts differs
            ((b"x", SecretStr("k"), 1), (b"y", SecretStr("k"), 1)),  # body differs
            ((b"x", SecretStr("k1"), 1), (b"x", SecretStr("k2"), 1)),  # secret differs
        ],
    )
    def test_different_inputs_produce_different_signatures(
        self, a: tuple, b: tuple,
    ) -> None:
        sig_a = sign_webhook(body=a[0], secret=a[1], ts=a[2])
        sig_b = sign_webhook(body=b[0], secret=b[1], ts=b[2])
        assert sig_a != sig_b

    def test_handles_empty_body(self) -> None:
        sig = sign_webhook(body=b"", secret=SecretStr("k"), ts=1)
        expected = hmac.new(
            key=b"k", msg=b"1.", digestmod=hashlib.sha256,
        ).hexdigest()
        assert sig == expected
