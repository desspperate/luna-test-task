import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from loguru import logger

from payments_processor.errors import WebhookUrlNotAllowedError

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class SSRFGuard:
    _ALLOWED_SCHEMES = frozenset({"https"})

    def __init__(self, *, allow_private_hosts: bool) -> None:
        self.allow_private_hosts = allow_private_hosts

    async def validate_url(self, url: str) -> None:
        parsed = urlparse(url)

        if parsed.scheme.lower() not in self._ALLOWED_SCHEMES:
            raise WebhookUrlNotAllowedError(url=url, reason="scheme_not_allowed")

        host = parsed.hostname
        if not host:
            raise WebhookUrlNotAllowedError(url=url, reason="missing_host")

        if self.allow_private_hosts:
            return

        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, parsed.port, type=socket.SOCK_STREAM)
        except OSError as e:
            logger.warning(f"SSRF guard: DNS resolution failed for host={host!r}: {e}")
            raise WebhookUrlNotAllowedError(url=url, reason="resolution_failed") from e

        for info in infos:
            sockaddr = info[4]
            raw_ip = sockaddr[0]
            if not isinstance(raw_ip, str):
                continue
            ip = self._normalize_ip(raw_ip)
            if self._is_disallowed(ip):
                logger.warning(
                    f"SSRF guard: blocked host={host!r} resolved to disallowed IP {ip}",
                )
                raise WebhookUrlNotAllowedError(
                    url=url,
                    reason="address_disallowed",
                    resolved_ip=str(ip),
                )

    @staticmethod
    def _normalize_ip(raw: str) -> IPAddress:
        if "%" in raw:
            raw = raw.split("%", 1)[0]
        ip = ipaddress.ip_address(raw)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        return ip

    @staticmethod
    def _is_disallowed(ip: IPAddress) -> bool:
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
