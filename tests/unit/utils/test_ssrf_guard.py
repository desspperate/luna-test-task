import asyncio
import socket
from collections.abc import Callable
from typing import Any

import pytest

from payments_processor.errors import WebhookUrlNotAllowedError
from payments_processor.utils import SSRFGuard


def _addrinfo_v4(ip: str) -> list[tuple[Any, ...]]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 443))]


def _addrinfo_v6(ip: str) -> list[tuple[Any, ...]]:
    return [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", (ip, 443, 0, 0))]


@pytest.fixture
def stub_dns(monkeypatch: pytest.MonkeyPatch):
    """Stub asyncio's getaddrinfo so SSRFGuard sees a controlled resolution."""

    def install(result: list[tuple[Any, ...]] | Exception) -> None:
        async def fake_getaddrinfo(*_args: Any, **_kwargs: Any) -> Any:
            if isinstance(result, Exception):
                raise result
            return result

        # Monkey-patch onto the running loop instance so the production code's
        # `loop.getaddrinfo(...)` call hits our fake.
        loop = asyncio.get_event_loop()
        monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo, raising=False)

    return install


class TestSchemeValidation:
    @pytest.mark.parametrize(
        "url",
        [
            "http://example.com/",
            "ftp://example.com/",
            "file:///etc/passwd",
            "gopher://example.com/",
        ],
    )
    async def test_rejects_non_https_scheme(self, url: str) -> None:
        guard = SSRFGuard(allow_private_hosts=False)
        with pytest.raises(WebhookUrlNotAllowedError) as exc_info:
            await guard.validate_url(url)
        assert exc_info.value.reason == "scheme_not_allowed"
        assert exc_info.value.url == url

    async def test_still_blocks_bad_scheme_when_private_hosts_allowed(self) -> None:
        guard = SSRFGuard(allow_private_hosts=True)
        with pytest.raises(WebhookUrlNotAllowedError) as exc_info:
            await guard.validate_url("http://localhost/")
        assert exc_info.value.reason == "scheme_not_allowed"


class TestHostValidation:
    async def test_rejects_url_without_host(self) -> None:
        guard = SSRFGuard(allow_private_hosts=False)
        with pytest.raises(WebhookUrlNotAllowedError) as exc_info:
            await guard.validate_url("https:///path")
        assert exc_info.value.reason == "missing_host"


class TestAddressBlocklist:
    @pytest.mark.parametrize(
        ("ip", "category"),
        [
            ("127.0.0.1", "loopback"),
            ("10.0.0.1", "private (RFC1918)"),
            ("192.168.1.1", "private (RFC1918)"),
            ("172.16.0.1", "private (RFC1918)"),
            ("169.254.169.254", "link-local (AWS metadata)"),
            ("0.0.0.0", "unspecified"),
            ("255.255.255.255", "reserved broadcast"),
        ],
    )
    async def test_blocks_resolved_address(
        self, stub_dns, ip: str, category: str,
    ) -> None:
        _ = category  # documents intent in pytest output
        stub_dns(_addrinfo_v4(ip))
        guard = SSRFGuard(allow_private_hosts=False)

        with pytest.raises(WebhookUrlNotAllowedError) as exc_info:
            await guard.validate_url("https://malicious.example.com/path")
        assert exc_info.value.reason == "address_disallowed"
        assert exc_info.value.resolved_ip == ip

    @pytest.mark.parametrize("ip", ["1.1.1.1", "8.8.8.8", "93.184.216.34"])
    async def test_allows_public_addresses(self, stub_dns, ip: str) -> None:
        stub_dns(_addrinfo_v4(ip))
        guard = SSRFGuard(allow_private_hosts=False)
        await guard.validate_url("https://public.example.com/")

    async def test_blocks_ipv6_loopback(self, stub_dns) -> None:
        stub_dns(_addrinfo_v6("::1"))
        guard = SSRFGuard(allow_private_hosts=False)
        with pytest.raises(WebhookUrlNotAllowedError) as exc_info:
            await guard.validate_url("https://malicious.example.com/")
        assert exc_info.value.reason == "address_disallowed"

    async def test_unwraps_ipv4_mapped_ipv6_before_classification(
        self, stub_dns,
    ) -> None:
        """`::ffff:127.0.0.1` must be treated as 127.0.0.1, not as a public v6."""
        stub_dns(_addrinfo_v6("::ffff:127.0.0.1"))
        guard = SSRFGuard(allow_private_hosts=False)
        with pytest.raises(WebhookUrlNotAllowedError) as exc_info:
            await guard.validate_url("https://malicious.example.com/")
        assert exc_info.value.reason == "address_disallowed"
        assert exc_info.value.resolved_ip == "127.0.0.1"

    async def test_strips_ipv6_zone_id_before_classification(self, stub_dns) -> None:
        """A zone suffix (`%en0`) must not bypass the link-local check."""
        stub_dns(_addrinfo_v6("fe80::1%en0"))
        guard = SSRFGuard(allow_private_hosts=False)
        with pytest.raises(WebhookUrlNotAllowedError) as exc_info:
            await guard.validate_url("https://malicious.example.com/")
        assert exc_info.value.reason == "address_disallowed"


class TestPrivateHostBypass:
    async def test_skips_resolution_when_private_hosts_allowed(self) -> None:
        """With private hosts allowed, no DNS lookup happens — even a host that
        would normally be blocked is accepted."""
        guard = SSRFGuard(allow_private_hosts=True)
        # No DNS stub installed: a real getaddrinfo call would either succeed
        # or fail, but the guard must short-circuit before reaching it.
        await guard.validate_url("https://127.0.0.1/path")


class TestResolutionFailure:
    async def test_dns_error_surfaces_as_resolution_failed(self, stub_dns: Callable[..., None]) -> None:
        stub_dns(socket.gaierror("name or service not known"))
        guard = SSRFGuard(allow_private_hosts=False)
        with pytest.raises(WebhookUrlNotAllowedError) as exc_info:
            await guard.validate_url("https://nonexistent.invalid/")
        assert exc_info.value.reason == "resolution_failed"
