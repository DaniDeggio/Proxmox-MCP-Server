"""Tests for the IPAM service."""

from __future__ import annotations

import pytest

from proxmox_mcp_server.models.errors import IpAllocationError
from proxmox_mcp_server.services.ipam import IpamService


class TestIpamAllocation:
    """Tests for IP allocation from a configured range."""

    def test_allocate_first_ip(self, ipam_service: IpamService) -> None:
        ip = ipam_service.allocate_ip("test-host-1")
        assert ip == "192.168.1.200"

    def test_allocate_sequential(self, ipam_service: IpamService) -> None:
        ip1 = ipam_service.allocate_ip("host-1")
        ip2 = ipam_service.allocate_ip("host-2")
        ip3 = ipam_service.allocate_ip("host-3")
        assert ip1 == "192.168.1.200"
        assert ip2 == "192.168.1.201"
        assert ip3 == "192.168.1.202"

    def test_allocate_idempotent_for_hostname(self, ipam_service: IpamService) -> None:
        """Same hostname should return the same IP without allocating a new one."""
        ip1 = ipam_service.allocate_ip("my-service")
        ip2 = ipam_service.allocate_ip("my-service")
        assert ip1 == ip2
        assert len(ipam_service.get_reservations()) == 1

    def test_allocate_with_vmid(self, ipam_service: IpamService) -> None:
        ip = ipam_service.allocate_ip("test-host", vmid=100)
        reservations = ipam_service.get_reservations()
        assert len(reservations) == 1
        assert reservations[0]["vmid"] == 100
        assert reservations[0]["ip"] == ip

    def test_allocate_preferred_ip(self, ipam_service: IpamService) -> None:
        ip = ipam_service.allocate_ip("specific-host", preferred_ip="192.168.1.205")
        assert ip == "192.168.1.205"

    def test_allocate_preferred_ip_taken(self, ipam_service: IpamService) -> None:
        ipam_service.allocate_ip("first-host", preferred_ip="192.168.1.205")
        with pytest.raises(IpAllocationError, match="already reserved"):
            ipam_service.allocate_ip("second-host", preferred_ip="192.168.1.205")

    def test_allocate_preferred_ip_out_of_range(self, ipam_service: IpamService) -> None:
        with pytest.raises(IpAllocationError, match="outside the configured range"):
            ipam_service.allocate_ip("bad-host", preferred_ip="10.0.0.1")

    def test_allocate_exhaustion(self, ipam_service: IpamService) -> None:
        """Range 192.168.1.200–210 has 11 IPs — the 12th should fail."""
        for i in range(11):
            ipam_service.allocate_ip(f"host-{i}")
        with pytest.raises(IpAllocationError, match="exhausted"):
            ipam_service.allocate_ip("one-too-many")


class TestIpamRelease:
    """Tests for IP release."""

    def test_release_existing(self, ipam_service: IpamService) -> None:
        ip = ipam_service.allocate_ip("temp-host")
        released = ipam_service.release_ip(ip)
        assert released is True
        assert len(ipam_service.get_reservations()) == 0

    def test_release_nonexistent(self, ipam_service: IpamService) -> None:
        released = ipam_service.release_ip("192.168.1.199")
        assert released is False

    def test_release_and_reallocate(self, ipam_service: IpamService) -> None:
        ip = ipam_service.allocate_ip("temp-host")
        ipam_service.release_ip(ip)
        new_ip = ipam_service.allocate_ip("new-host")
        assert new_ip == ip  # Should reuse the released IP


class TestIpamAvailability:
    """Tests for IP availability checks."""

    def test_available_in_range(self, ipam_service: IpamService) -> None:
        assert ipam_service.is_ip_available("192.168.1.200") is True

    def test_not_available_after_allocation(self, ipam_service: IpamService) -> None:
        ipam_service.allocate_ip("taken-host")
        assert ipam_service.is_ip_available("192.168.1.200") is False

    def test_not_available_outside_range(self, ipam_service: IpamService) -> None:
        assert ipam_service.is_ip_available("10.0.0.1") is False


class TestIpamPersistence:
    """Tests that state survives service recreation."""

    def test_state_persisted(self, test_network_config) -> None:  # type: ignore[no-untyped-def]
        service1 = IpamService(test_network_config)
        service1.allocate_ip("persist-test")

        service2 = IpamService(test_network_config)
        reservations = service2.get_reservations()
        assert len(reservations) == 1
        assert reservations[0]["hostname"] == "persist-test"
