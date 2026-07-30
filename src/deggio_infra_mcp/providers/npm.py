"""Nginx Proxy Manager provider — creates and manages proxy hosts via REST API.

API surface used
----------------
- ``POST /api/tokens``                    → Bearer token auth
- ``GET  /api/nginx/proxy-hosts``         → list proxy hosts
- ``POST /api/nginx/proxy-hosts``         → create proxy host
- ``DELETE /api/nginx/proxy-hosts/{id}``  → delete proxy host
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from deggio_infra_mcp.logging import get_logger
from deggio_infra_mcp.models.errors import NpmError
from deggio_infra_mcp.providers import BaseNpmProvider

if TYPE_CHECKING:
    from deggio_infra_mcp.config import NpmConfig

log = get_logger("providers.npm")


class NpmProvider(BaseNpmProvider):
    """Nginx Proxy Manager proxy-host management."""

    def __init__(self, config: NpmConfig) -> None:
        self._config = config
        self._base_url = config.url.rstrip("/")
        self._token: str | None = None
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            verify=config.verify_ssl,
            timeout=30.0,
        )

    def _invalidate_auth(self) -> None:
        """Clear cached token so the next call re-authenticates."""
        self._token = None

    async def _ensure_auth(self) -> None:
        """Obtain a Bearer token if we don't have one."""
        if self._token:
            return
        log.debug("npm_authenticating", url=self._base_url)
        try:
            resp = await self._client.post(
                "/api/tokens",
                json={
                    "identity": self._config.username,
                    "secret": self._config.password,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self._token = data.get("token")
            if not self._token:
                raise NpmError(
                    f"NPM auth returned no token: {data}",
                    details={"response": data},
                )
            log.info("npm_authenticated")
        except httpx.HTTPError as exc:
            raise NpmError(f"NPM authentication failed: {exc}") from exc

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Execute an HTTP request, retrying once on 401 (token expired)."""
        await self._ensure_auth()
        kwargs.setdefault("headers", self._auth_headers())

        resp = await self._client.request(method, url, **kwargs)
        if resp.status_code == 401:
            log.info("npm_token_expired_retrying")
            self._invalidate_auth()
            await self._ensure_auth()
            kwargs["headers"] = self._auth_headers()
            resp = await self._client.request(method, url, **kwargs)
        return resp

    async def get_proxy_hosts(self) -> list[dict[str, Any]]:
        try:
            resp = await self._request_with_retry("GET", "/api/nginx/proxy-hosts")
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except httpx.HTTPError as exc:
            raise NpmError(f"Failed to list proxy hosts: {exc}") from exc

    async def find_proxy_host_by_domain(self, domain: str) -> dict[str, Any] | None:
        hosts = await self.get_proxy_hosts()
        for host in hosts:
            domain_names = host.get("domain_names", [])
            if domain in domain_names:
                return host
        return None

    async def create_proxy_host(
        self,
        domain: str,
        forward_host: str,
        forward_port: int,
        *,
        forward_scheme: str = "http",
    ) -> dict[str, Any]:
        defaults = self._config.defaults

        # Idempotency: check if host already exists
        existing = await self.find_proxy_host_by_domain(domain)
        if existing:
            # Check for conflict vs. match
            if (
                existing.get("forward_host") == forward_host
                and existing.get("forward_port") == forward_port
                and existing.get("forward_scheme") == forward_scheme
            ):
                log.info("npm_host_exists_matching", domain=domain)
                return {**existing, "action": "already_exists"}
            else:
                raise NpmError(
                    f"Proxy host for '{domain}' already exists but with "
                    f"different settings (forward to "
                    f"{existing.get('forward_scheme')}://"
                    f"{existing.get('forward_host')}:"
                    f"{existing.get('forward_port')}). "
                    f"Requested: {forward_scheme}://{forward_host}:{forward_port}",
                    details={"existing": existing},
                )

        log.info(
            "npm_creating_proxy_host",
            domain=domain,
            forward=f"{forward_scheme}://{forward_host}:{forward_port}",
        )
        payload: dict[str, Any] = {
            "domain_names": [domain],
            "forward_scheme": forward_scheme,
            "forward_host": forward_host,
            "forward_port": forward_port,
            "access_list_id": defaults.access_list_id,
            "certificate_id": defaults.certificate_id,
            "ssl_forced": defaults.ssl_forced,
            "allow_websocket_upgrade": defaults.allow_websocket_upgrade,
            "block_exploits": defaults.block_exploits,
            "http2_support": defaults.http2_support,
            "meta": {
                "letsencrypt_agree": False,
                "dns_challenge": False,
            },
            "locations": [],
            "advanced_config": "",
        }
        try:
            resp = await self._request_with_retry(
                "POST",
                "/api/nginx/proxy-hosts",
                json=payload,
            )
            resp.raise_for_status()
            result = resp.json()
            return {**result, "action": "created"}
        except httpx.HTTPError as exc:
            raise NpmError(
                f"Failed to create proxy host for '{domain}': {exc}"
            ) from exc

    async def delete_proxy_host(self, host_id: int) -> None:
        log.info("npm_deleting_proxy_host", host_id=host_id)
        try:
            resp = await self._request_with_retry(
                "DELETE",
                f"/api/nginx/proxy-hosts/{host_id}",
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise NpmError(f"Failed to delete proxy host {host_id}: {exc}") from exc

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
