"""Tests for the real NpmProvider using respx to mock httpx."""

from __future__ import annotations

import httpx
import pytest
import respx

from proxmox_mcp_server.config import NpmConfig
from proxmox_mcp_server.models.errors import NpmError
from proxmox_mcp_server.providers.npm import NpmProvider


def _make_provider(base_url: str = "http://npm.test:81") -> NpmProvider:
    return NpmProvider(NpmConfig(url=base_url, username="admin@test.com", password="secret"))


def _auth_response() -> dict:
    return {"token": "jwt-test-token-123"}


class TestNpmAuth:
    """Tests for NPM authentication flow."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_sends_credentials(self) -> None:
        auth_route = respx.post("http://npm.test:81/api/tokens").mock(
            return_value=httpx.Response(200, json=_auth_response())
        )
        respx.get("http://npm.test:81/api/nginx/proxy-hosts").mock(
            return_value=httpx.Response(200, json=[])
        )
        provider = _make_provider()
        await provider.get_proxy_hosts()

        assert auth_route.called
        body = auth_route.calls[0].request.content
        assert b"admin@test.com" in body
        assert b"secret" in body

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_failure_raises(self) -> None:
        respx.post("http://npm.test:81/api/tokens").mock(
            return_value=httpx.Response(401, json={"error": "Invalid credentials"})
        )
        provider = _make_provider()
        with pytest.raises(NpmError, match="authentication failed"):
            await provider.get_proxy_hosts()

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_no_token_raises(self) -> None:
        respx.post("http://npm.test:81/api/tokens").mock(
            return_value=httpx.Response(200, json={})
        )
        provider = _make_provider()
        with pytest.raises(NpmError, match="no token"):
            await provider.get_proxy_hosts()


class TestNpmProxyHosts:
    """Tests for proxy host CRUD via HTTP."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_list_proxy_hosts(self) -> None:
        respx.post("http://npm.test:81/api/tokens").mock(
            return_value=httpx.Response(200, json=_auth_response())
        )
        respx.get("http://npm.test:81/api/nginx/proxy-hosts").mock(
            return_value=httpx.Response(200, json=[
                {"id": 1, "domain_names": ["app.local"], "forward_host": "10.0.0.1", "forward_port": 80},
                {"id": 2, "domain_names": ["db.local"], "forward_host": "10.0.0.2", "forward_port": 3306},
            ])
        )
        provider = _make_provider()
        hosts = await provider.get_proxy_hosts()

        assert len(hosts) == 2
        assert hosts[0]["domain_names"] == ["app.local"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_create_proxy_host(self) -> None:
        respx.post("http://npm.test:81/api/tokens").mock(
            return_value=httpx.Response(200, json=_auth_response())
        )
        respx.get("http://npm.test:81/api/nginx/proxy-hosts").mock(
            return_value=httpx.Response(200, json=[])
        )
        create_route = respx.post("http://npm.test:81/api/nginx/proxy-hosts").mock(
            return_value=httpx.Response(201, json={
                "id": 5,
                "domain_names": ["new.local"],
                "forward_host": "10.0.0.5",
                "forward_port": 8080,
            })
        )
        provider = _make_provider()
        result = await provider.create_proxy_host(
            domain="new.local",
            forward_host="10.0.0.5",
            forward_port=8080,
        )

        assert result["action"] == "created"
        assert result["id"] == 5
        assert create_route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_create_proxy_host_idempotent(self) -> None:
        respx.post("http://npm.test:81/api/tokens").mock(
            return_value=httpx.Response(200, json=_auth_response())
        )
        respx.get("http://npm.test:81/api/nginx/proxy-hosts").mock(
            return_value=httpx.Response(200, json=[{
                "id": 3,
                "domain_names": ["exists.local"],
                "forward_host": "10.0.0.3",
                "forward_port": 80,
                "forward_scheme": "http",
            }])
        )
        provider = _make_provider()
        result = await provider.create_proxy_host(
            domain="exists.local",
            forward_host="10.0.0.3",
            forward_port=80,
        )

        assert result["action"] == "already_exists"

    @pytest.mark.asyncio
    @respx.mock
    async def test_create_proxy_host_conflict(self) -> None:
        respx.post("http://npm.test:81/api/tokens").mock(
            return_value=httpx.Response(200, json=_auth_response())
        )
        respx.get("http://npm.test:81/api/nginx/proxy-hosts").mock(
            return_value=httpx.Response(200, json=[{
                "id": 3,
                "domain_names": ["conflict.local"],
                "forward_host": "10.0.0.3",
                "forward_port": 80,
                "forward_scheme": "http",
            }])
        )
        provider = _make_provider()
        with pytest.raises(NpmError, match="already exists but with different settings"):
            await provider.create_proxy_host(
                domain="conflict.local",
                forward_host="10.0.0.99",
                forward_port=9090,
            )

    @pytest.mark.asyncio
    @respx.mock
    async def test_find_proxy_host_by_domain(self) -> None:
        respx.post("http://npm.test:81/api/tokens").mock(
            return_value=httpx.Response(200, json=_auth_response())
        )
        respx.get("http://npm.test:81/api/nginx/proxy-hosts").mock(
            return_value=httpx.Response(200, json=[
                {"id": 1, "domain_names": ["find-me.local"], "forward_host": "10.0.0.1", "forward_port": 3000},
            ])
        )
        provider = _make_provider()
        found = await provider.find_proxy_host_by_domain("find-me.local")

        assert found is not None
        assert found["forward_port"] == 3000

    @pytest.mark.asyncio
    @respx.mock
    async def test_find_proxy_host_not_found(self) -> None:
        respx.post("http://npm.test:81/api/tokens").mock(
            return_value=httpx.Response(200, json=_auth_response())
        )
        respx.get("http://npm.test:81/api/nginx/proxy-hosts").mock(
            return_value=httpx.Response(200, json=[])
        )
        provider = _make_provider()
        found = await provider.find_proxy_host_by_domain("nope.local")

        assert found is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_delete_proxy_host(self) -> None:
        respx.post("http://npm.test:81/api/tokens").mock(
            return_value=httpx.Response(200, json=_auth_response())
        )
        delete_route = respx.delete("http://npm.test:81/api/nginx/proxy-hosts/7").mock(
            return_value=httpx.Response(204)
        )
        provider = _make_provider()
        await provider.delete_proxy_host(7)

        assert delete_route.called


class TestNpmTokenRetry:
    """Tests for 401 retry (token expiry)."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_retry_on_401(self) -> None:
        """First GET returns 401, provider re-auths and retries."""
        auth_route = respx.post("http://npm.test:81/api/tokens").mock(
            return_value=httpx.Response(200, json=_auth_response())
        )
        get_route = respx.get("http://npm.test:81/api/nginx/proxy-hosts").mock(
            side_effect=[
                httpx.Response(401, json={"error": "token expired"}),
                httpx.Response(200, json=[{"id": 1, "domain_names": ["retried.local"]}]),
            ]
        )
        provider = _make_provider()
        hosts = await provider.get_proxy_hosts()

        assert len(hosts) == 1
        assert hosts[0]["domain_names"] == ["retried.local"]
        # Auth called twice: initial + retry
        assert auth_route.call_count == 2
        assert get_route.call_count == 2
