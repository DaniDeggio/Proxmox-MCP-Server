"""Tests for the real PiHoleProvider using respx to mock httpx."""

from __future__ import annotations

import httpx
import pytest
import respx

from deggio_infra_mcp.config import PiHoleConfig
from deggio_infra_mcp.models.errors import PiHoleError
from deggio_infra_mcp.providers.pihole import PiHoleProvider


def _make_provider(base_url: str = "http://pihole.test") -> PiHoleProvider:
    return PiHoleProvider(PiHoleConfig(url=base_url, password="test-pw"))


def _auth_response() -> dict:
    return {"session": {"sid": "test-sid-123", "csrf": "csrf-token-456"}}


def _hosts_response(hosts: list[str] | None = None) -> dict:
    return {"config": {"dns": {"hosts": hosts or []}}}


class TestPiHoleAuth:
    """Tests for Pi-hole authentication flow."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_sends_password(self) -> None:
        route = respx.post("http://pihole.test/api/auth").mock(
            return_value=httpx.Response(200, json=_auth_response())
        )
        respx.get("http://pihole.test/api/config/dns/hosts").mock(
            return_value=httpx.Response(200, json=_hosts_response())
        )
        provider = _make_provider()
        await provider.get_dns_records()

        assert route.called
        request_body = route.calls[0].request.content
        assert b"test-pw" in request_body

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_failure_raises(self) -> None:
        respx.post("http://pihole.test/api/auth").mock(
            return_value=httpx.Response(401, json={"error": "bad password"})
        )
        provider = _make_provider()
        with pytest.raises(PiHoleError, match="authentication failed"):
            await provider.get_dns_records()

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_no_sid_raises(self) -> None:
        respx.post("http://pihole.test/api/auth").mock(
            return_value=httpx.Response(200, json={"session": {}})
        )
        provider = _make_provider()
        with pytest.raises(PiHoleError, match="no session ID"):
            await provider.get_dns_records()


class TestPiHoleDnsRecords:
    """Tests for DNS record CRUD via HTTP."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_dns_records(self) -> None:
        respx.post("http://pihole.test/api/auth").mock(
            return_value=httpx.Response(200, json=_auth_response())
        )
        respx.get("http://pihole.test/api/config/dns/hosts").mock(
            return_value=httpx.Response(200, json=_hosts_response([
                "192.168.1.200 app.local",
                "192.168.1.201 db.local",
            ]))
        )
        provider = _make_provider()
        records = await provider.get_dns_records()

        assert len(records) == 2
        assert records[0] == {"ip": "192.168.1.200", "domain": "app.local"}
        assert records[1] == {"ip": "192.168.1.201", "domain": "db.local"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_add_dns_record(self) -> None:
        respx.post("http://pihole.test/api/auth").mock(
            return_value=httpx.Response(200, json=_auth_response())
        )
        respx.get("http://pihole.test/api/config/dns/hosts").mock(
            return_value=httpx.Response(200, json=_hosts_response())
        )
        put_route = respx.put(url__regex=r".*/api/config/dns/hosts/.*").mock(
            return_value=httpx.Response(201, json={})
        )
        provider = _make_provider()
        result = await provider.add_dns_record("new.local", "10.0.0.1")

        assert result["action"] == "created"
        assert put_route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_add_dns_record_idempotent(self) -> None:
        respx.post("http://pihole.test/api/auth").mock(
            return_value=httpx.Response(200, json=_auth_response())
        )
        respx.get("http://pihole.test/api/config/dns/hosts").mock(
            return_value=httpx.Response(200, json=_hosts_response([
                "10.0.0.1 existing.local",
            ]))
        )
        provider = _make_provider()
        result = await provider.add_dns_record("existing.local", "10.0.0.1")

        assert result["action"] == "already_exists"

    @pytest.mark.asyncio
    @respx.mock
    async def test_delete_dns_record(self) -> None:
        respx.post("http://pihole.test/api/auth").mock(
            return_value=httpx.Response(200, json=_auth_response())
        )
        delete_route = respx.delete(url__regex=r".*/api/config/dns/hosts/.*").mock(
            return_value=httpx.Response(204)
        )
        provider = _make_provider()
        result = await provider.delete_dns_record("old.local", "10.0.0.2")

        assert result["action"] == "deleted"
        assert delete_route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_record_exists_true(self) -> None:
        respx.post("http://pihole.test/api/auth").mock(
            return_value=httpx.Response(200, json=_auth_response())
        )
        respx.get("http://pihole.test/api/config/dns/hosts").mock(
            return_value=httpx.Response(200, json=_hosts_response([
                "10.0.0.5 check.local",
            ]))
        )
        provider = _make_provider()
        assert await provider.record_exists("check.local", "10.0.0.5") is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_record_exists_false(self) -> None:
        respx.post("http://pihole.test/api/auth").mock(
            return_value=httpx.Response(200, json=_auth_response())
        )
        respx.get("http://pihole.test/api/config/dns/hosts").mock(
            return_value=httpx.Response(200, json=_hosts_response())
        )
        provider = _make_provider()
        assert await provider.record_exists("nope.local", "10.0.0.5") is False


class TestPiHoleSessionRetry:
    """Tests for 401 retry (session expiry)."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_retry_on_401(self) -> None:
        """First GET returns 401, provider re-auths and retries."""
        auth_route = respx.post("http://pihole.test/api/auth").mock(
            return_value=httpx.Response(200, json=_auth_response())
        )
        # First call → 401, second call → success
        get_route = respx.get("http://pihole.test/api/config/dns/hosts").mock(
            side_effect=[
                httpx.Response(401, json={"error": "session expired"}),
                httpx.Response(200, json=_hosts_response(["10.0.0.1 retried.local"])),
            ]
        )
        provider = _make_provider()
        records = await provider.get_dns_records()

        assert len(records) == 1
        assert records[0]["domain"] == "retried.local"
        # Auth called twice: initial + retry
        assert auth_route.call_count == 2
        assert get_route.call_count == 2
