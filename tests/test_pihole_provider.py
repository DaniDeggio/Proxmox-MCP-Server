"""Tests for Pi-hole provider conflict handling."""

from __future__ import annotations

import pytest

from tests.conftest import MockPiHoleProvider


class TestPiHoleIdempotency:
    """Tests for DNS record idempotency and conflict handling."""

    @pytest.fixture
    def pihole(self) -> MockPiHoleProvider:
        return MockPiHoleProvider()

    @pytest.mark.asyncio
    async def test_add_new_record(self, pihole: MockPiHoleProvider) -> None:
        result = await pihole.add_dns_record("app.deggio.local", "192.168.1.200")
        assert result["action"] == "created"

    @pytest.mark.asyncio
    async def test_add_duplicate_is_idempotent(self, pihole: MockPiHoleProvider) -> None:
        await pihole.add_dns_record("app.deggio.local", "192.168.1.200")
        result = await pihole.add_dns_record("app.deggio.local", "192.168.1.200")
        assert result["action"] == "already_exists"

    @pytest.mark.asyncio
    async def test_record_exists_check(self, pihole: MockPiHoleProvider) -> None:
        assert await pihole.record_exists("app.deggio.local", "192.168.1.200") is False
        await pihole.add_dns_record("app.deggio.local", "192.168.1.200")
        assert await pihole.record_exists("app.deggio.local", "192.168.1.200") is True

    @pytest.mark.asyncio
    async def test_delete_record(self, pihole: MockPiHoleProvider) -> None:
        await pihole.add_dns_record("temp.deggio.local", "192.168.1.201")
        result = await pihole.delete_dns_record("temp.deggio.local", "192.168.1.201")
        assert result["action"] == "deleted"
        assert await pihole.record_exists("temp.deggio.local", "192.168.1.201") is False

    @pytest.mark.asyncio
    async def test_list_records(self, pihole: MockPiHoleProvider) -> None:
        await pihole.add_dns_record("a.local", "10.0.0.1")
        await pihole.add_dns_record("b.local", "10.0.0.2")
        records = await pihole.get_dns_records()
        assert len(records) == 2

    @pytest.mark.asyncio
    async def test_different_ip_same_domain(self, pihole: MockPiHoleProvider) -> None:
        """Adding the same domain with a different IP should create a new record."""
        await pihole.add_dns_record("app.deggio.local", "192.168.1.200")
        result = await pihole.add_dns_record("app.deggio.local", "192.168.1.201")
        assert result["action"] == "created"
        records = await pihole.get_dns_records()
        assert len(records) == 2
