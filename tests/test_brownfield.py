"""Tests for brownfield LXC adoption via import_existing_lxc."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from proxmox_mcp_server.services.provisioning import ProvisioningService


def _make_container_with_ip(mock_proxmox, vmid: int, hostname: str, ip: str) -> None:
    """Helper: create a container in the mock with a net0 IP."""
    mock_proxmox.containers[vmid] = {
        "vmid": vmid,
        "hostname": hostname,
        "status": "running",
        # Simulate Proxmox net0 format with embedded IP
        "net0": f"ip={ip}/24,gw=192.168.1.1",
    }


@pytest.mark.asyncio
async def test_import_existing_lxc_in_range_registers_ipam(
    provisioning_service: ProvisioningService, mock_proxmox
):
    """import_existing_lxc registers the IP in IPAM when it's within the configured range."""
    _make_container_with_ip(mock_proxmox, 300, "legacy-app", "192.168.1.205")

    result = await provisioning_service.import_existing_lxc(
        vmid=300,
        service_name="legacy-app",
        register_dns=False,
        register_proxy=False,
    )

    assert result["success"] is True
    assert result["vmid"] == 300
    assert result["ip"] == "192.168.1.205"
    assert result["registered_in_ipam"] in ("registered", "already_registered")
    assert result["out_of_range"] is False


@pytest.mark.asyncio
async def test_import_existing_lxc_dns_registered_by_default(
    provisioning_service: ProvisioningService, mock_proxmox, mock_pihole
):
    """import_existing_lxc adds a DNS record by default (register_dns=True)."""
    _make_container_with_ip(mock_proxmox, 301, "my-wiki", "192.168.1.206")

    result = await provisioning_service.import_existing_lxc(
        vmid=301,
        service_name="my-wiki",
    )

    assert result["success"] is True
    assert result["dns_action"] in ("created", "already_exists")


@pytest.mark.asyncio
async def test_import_existing_lxc_skip_dns(
    provisioning_service: ProvisioningService, mock_proxmox
):
    """import_existing_lxc skips DNS when register_dns=False."""
    _make_container_with_ip(mock_proxmox, 302, "no-dns", "192.168.1.207")

    result = await provisioning_service.import_existing_lxc(
        vmid=302,
        service_name="no-dns",
        register_dns=False,
    )

    assert result["dns_action"] == "skipped"


@pytest.mark.asyncio
async def test_import_existing_lxc_with_proxy(
    provisioning_service: ProvisioningService, mock_proxmox
):
    """import_existing_lxc creates NPM proxy host when register_proxy=True."""
    _make_container_with_ip(mock_proxmox, 303, "proxied-app", "192.168.1.208")

    result = await provisioning_service.import_existing_lxc(
        vmid=303,
        service_name="proxied-app",
        register_dns=False,
        register_proxy=True,
        forward_port=3000,
    )

    assert result["success"] is True
    assert result["proxy_action"] in ("created", "already_exists")


@pytest.mark.asyncio
async def test_import_existing_lxc_no_proxy_by_default(
    provisioning_service: ProvisioningService, mock_proxmox
):
    """import_existing_lxc skips proxy by default (register_proxy=False)."""
    _make_container_with_ip(mock_proxmox, 304, "no-proxy", "192.168.1.209")

    result = await provisioning_service.import_existing_lxc(
        vmid=304,
        service_name="no-proxy",
    )

    assert result["proxy_action"] == "skipped"


@pytest.mark.asyncio
async def test_import_existing_lxc_domain_format(
    provisioning_service: ProvisioningService, mock_proxmox
):
    """import_existing_lxc generates domain using the configured local_suffix."""
    _make_container_with_ip(mock_proxmox, 305, "gitea-server", "192.168.1.210")

    result = await provisioning_service.import_existing_lxc(
        vmid=305,
        service_name="gitea-server",
        register_dns=False,
    )

    assert result["hostname"] == "gitea-server"
    assert result["domain"] == "gitea-server.homelab.local"


@pytest.mark.asyncio
async def test_import_existing_lxc_normalizes_service_name(
    provisioning_service: ProvisioningService, mock_proxmox
):
    """import_existing_lxc converts spaces and underscores to dashes in hostname."""
    _make_container_with_ip(mock_proxmox, 306, "my_app", "192.168.1.200")

    result = await provisioning_service.import_existing_lxc(
        vmid=306,
        service_name="my app service",
        register_dns=False,
    )

    assert result["hostname"] == "my-app-service"


@pytest.mark.asyncio
async def test_import_existing_lxc_no_ip_returns_failure(
    provisioning_service: ProvisioningService, mock_proxmox
):
    """import_existing_lxc returns a failure dict when IP cannot be determined."""
    # Container with no IP information
    mock_proxmox.containers[307] = {
        "vmid": 307,
        "hostname": "no-ip-svc",
        "status": "running",
        # No net0, no ip field
    }

    result = await provisioning_service.import_existing_lxc(
        vmid=307,
        service_name="no-ip-svc",
        register_dns=False,
    )

    assert result["success"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_import_existing_lxc_idempotent_on_second_call(
    provisioning_service: ProvisioningService, mock_proxmox
):
    """import_existing_lxc is idempotent: second import returns already_registered."""
    _make_container_with_ip(mock_proxmox, 308, "idempotent-svc", "192.168.1.202")

    result1 = await provisioning_service.import_existing_lxc(
        vmid=308, service_name="idempotent-svc", register_dns=False
    )
    result2 = await provisioning_service.import_existing_lxc(
        vmid=308, service_name="idempotent-svc", register_dns=False
    )

    assert result1["success"] is True
    assert result2["success"] is True
    assert result2["registered_in_ipam"] == "already_registered"
