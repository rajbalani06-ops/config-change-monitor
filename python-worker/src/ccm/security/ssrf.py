from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeWebhookError(ValueError):
    pass


BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "metadata"}


class WebhookUrlValidator:
    def __init__(self, allow_private: bool = False):
        self.allow_private = allow_private

    def validate(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise UnsafeWebhookError("webhook URL must be http or https")
        if not parsed.hostname:
            raise UnsafeWebhookError("webhook URL must include a hostname")
        host = parsed.hostname.lower()
        if host in BLOCKED_HOSTS and not self.allow_private:
            raise UnsafeWebhookError("localhost and metadata hosts are blocked")
        if host.endswith(".internal") and not self.allow_private:
            raise UnsafeWebhookError("internal hosts are blocked")
        self._check_resolved(host)
        return url

    def revalidate_after_dns(self, url: str) -> list[str]:
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            raise UnsafeWebhookError("missing hostname")
        addresses = self._resolve(host)
        for addr in addresses:
            self._assert_public(addr)
        return addresses

    def _check_resolved(self, host: str) -> None:
        try:
            ipaddress.ip_address(host)
            self._assert_public(host)
            return
        except ValueError:
            pass
        for addr in self._resolve(host):
            self._assert_public(addr)

    def _resolve(self, host: str) -> list[str]:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise UnsafeWebhookError(f"DNS resolution failed: {exc}") from exc
        addrs = sorted({info[4][0] for info in infos})
        if not addrs:
            raise UnsafeWebhookError("DNS resolution returned no addresses")
        return addrs

    def _assert_public(self, addr: str) -> None:
        ip = ipaddress.ip_address(addr)
        if self.allow_private:
            return
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise UnsafeWebhookError("webhook destination resolves to a blocked network range")
        # AWS/GCP/Azure metadata
        if str(ip) == "169.254.169.254":
            raise UnsafeWebhookError("cloud metadata addresses are blocked")
