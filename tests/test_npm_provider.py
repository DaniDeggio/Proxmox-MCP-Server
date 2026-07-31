"""Tests for NPM provider idempotency logic."""

from __future__ import annotations

import pytest

from tests.conftest import MockNpmProvider


class TestNpmIdempotency:
    """Tests for proxy host creation idempotency."""

    @pytest.fixture
    def npm(self) -> MockNpmProvider:
        return MockNpmProvider()

    @pytest.mark.asyncio
    async def test_create_new_host(self, npm: MockNpmProvider) -> None:
        result = await npm.create_proxy_host(
            domain="app.homelab.local",
            forward_host="192.168.1.200",
            forward_port=8080,
        )
        assert result["action"] == "created"
        assert "app.homelab.local" in result["domain_names"]

    @pytest.mark.asyncio
    async def test_create_duplicate_returns_existing(self, npm: MockNpmProvider) -> None:
        await npm.create_proxy_host(
            domain="app.homelab.local",
            forward_host="192.168.1.200",
            forward_port=8080,
        )
        result = await npm.create_proxy_host(
            domain="app.homelab.local",
            forward_host="192.168.1.200",
            forward_port=8080,
        )
        assert result["action"] == "already_exists"

    @pytest.mark.asyncio
    async def test_find_existing_host(self, npm: MockNpmProvider) -> None:
        await npm.create_proxy_host(
            domain="find-me.homelab.local",
            forward_host="192.168.1.201",
            forward_port=3000,
        )
        found = await npm.find_proxy_host_by_domain("find-me.homelab.local")
        assert found is not None
        assert found["forward_port"] == 3000

    @pytest.mark.asyncio
    async def test_find_nonexistent_host(self, npm: MockNpmProvider) -> None:
        found = await npm.find_proxy_host_by_domain("nope.homelab.local")
        assert found is None

    @pytest.mark.asyncio
    async def test_delete_host(self, npm: MockNpmProvider) -> None:
        result = await npm.create_proxy_host(
            domain="temp.homelab.local",
            forward_host="192.168.1.202",
            forward_port=80,
        )
        host_id = result["id"]
        await npm.delete_proxy_host(host_id)
        assert await npm.find_proxy_host_by_domain("temp.homelab.local") is None

    @pytest.mark.asyncio
    async def test_list_hosts(self, npm: MockNpmProvider) -> None:
        await npm.create_proxy_host("a.local", "10.0.0.1", 80)
        await npm.create_proxy_host("b.local", "10.0.0.2", 80)
        hosts = await npm.get_proxy_hosts()
        assert len(hosts) == 2
