"""Pi-hole v6 provider — manages local DNS A records via the REST API.

API surface used
----------------
- ``POST /api/auth``                        → session (sid + CSRF token)
- ``GET  /api/config/dns/hosts``            → list custom DNS records
- ``PUT  /api/config/dns/hosts/<ip>%20<domain>``  → add a record
- ``DELETE /api/config/dns/hosts/<ip>%20<domain>`` → remove a record

Pi-hole v5 compatibility
------------------------
Pi-hole v5 used a completely different API (``api.php?customdns``).
If you're on v5, you'll need to swap this provider or create a v5 adapter.
The base class contract remains the same.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

from deggio_infra_mcp.logging import get_logger
from deggio_infra_mcp.models.errors import PiHoleError
from deggio_infra_mcp.providers import BasePiHoleProvider

if TYPE_CHECKING:
    from deggio_infra_mcp.config import PiHoleConfig

log = get_logger("providers.pihole")


class PiHoleProvider(BasePiHoleProvider):
    """Pi-hole v6 custom DNS record management."""

    def __init__(self, config: PiHoleConfig) -> None:
        self._config = config
        self._base_url = config.url.rstrip("/")
        self._sid: str | None = None
        self._csrf: str | None = None
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            verify=config.verify_ssl,
            timeout=30.0,
        )

    def _invalidate_auth(self) -> None:
        """Clear cached session so the next call re-authenticates."""
        self._sid = None
        self._csrf = None

    async def _ensure_auth(self) -> None:
        """Authenticate if we don't have a valid session."""
        if self._sid:
            return
        log.debug("pihole_authenticating", url=self._base_url)
        try:
            resp = await self._client.post(
                "/api/auth",
                json={"password": self._config.password},
            )
            resp.raise_for_status()
            data = resp.json()
            session = data.get("session", {})
            self._sid = session.get("sid")
            self._csrf = session.get("csrf")
            if not self._sid:
                raise PiHoleError(
                    f"Pi-hole auth returned no session ID: {data}",
                    details={"response": data},
                )
            log.info("pihole_authenticated")
        except httpx.HTTPError as exc:
            raise PiHoleError(f"Pi-hole authentication failed: {exc}") from exc

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._sid:
            headers["sid"] = self._sid
        if self._csrf:
            headers["X-CSRF-Token"] = self._csrf
        return headers

    @staticmethod
    def _record_key(ip: str, domain: str) -> str:
        """URL-encoded ``ip domain`` path component for the hosts endpoint."""
        return quote(f"{ip} {domain}", safe="")

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Execute an HTTP request, retrying once on 401 (session expired)."""
        await self._ensure_auth()
        kwargs.setdefault("headers", self._auth_headers())

        resp = await self._client.request(method, url, **kwargs)
        if resp.status_code == 401:
            log.info("pihole_session_expired_retrying")
            self._invalidate_auth()
            await self._ensure_auth()
            kwargs["headers"] = self._auth_headers()
            resp = await self._client.request(method, url, **kwargs)
        return resp

    async def get_dns_records(self) -> list[dict[str, str]]:
        try:
            resp = await self._request_with_retry("GET", "/api/config/dns/hosts")
            resp.raise_for_status()
            data = resp.json()
            # Pi-hole v6 returns {"config": {"dns": {"hosts": [...]}}}
            hosts_raw = (
                data.get("config", {}).get("dns", {}).get("hosts", [])
            )
            records: list[dict[str, str]] = []
            for entry in hosts_raw:
                if isinstance(entry, str) and " " in entry:
                    parts = entry.split(maxsplit=1)
                    records.append({"ip": parts[0], "domain": parts[1]})
            return records
        except httpx.HTTPError as exc:
            raise PiHoleError(f"Failed to list DNS records: {exc}") from exc

    async def record_exists(self, domain: str, target_ip: str) -> bool:
        records = await self.get_dns_records()
        return any(
            r["domain"] == domain and r["ip"] == target_ip for r in records
        )

    async def add_dns_record(self, domain: str, target_ip: str) -> dict[str, Any]:
        # Idempotency: check first
        if await self.record_exists(domain, target_ip):
            log.info("pihole_record_exists", domain=domain, ip=target_ip)
            return {"domain": domain, "ip": target_ip, "action": "already_exists"}

        log.info("pihole_adding_record", domain=domain, ip=target_ip)
        key = self._record_key(target_ip, domain)
        try:
            resp = await self._request_with_retry(
                "PUT",
                f"/api/config/dns/hosts/{key}",
            )
            resp.raise_for_status()
            return {"domain": domain, "ip": target_ip, "action": "created"}
        except httpx.HTTPError as exc:
            raise PiHoleError(
                f"Failed to add DNS record {domain} → {target_ip}: {exc}"
            ) from exc

    async def delete_dns_record(self, domain: str, target_ip: str) -> dict[str, Any]:
        log.info("pihole_deleting_record", domain=domain, ip=target_ip)
        key = self._record_key(target_ip, domain)
        try:
            resp = await self._request_with_retry(
                "DELETE",
                f"/api/config/dns/hosts/{key}",
            )
            resp.raise_for_status()
            return {"domain": domain, "ip": target_ip, "action": "deleted"}
        except httpx.HTTPError as exc:
            raise PiHoleError(
                f"Failed to delete DNS record {domain}: {exc}"
            ) from exc

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
