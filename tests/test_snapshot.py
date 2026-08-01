from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from proxmox_mcp_server.models.errors import SnapshotError

if TYPE_CHECKING:
    from proxmox_mcp_server.services.provisioning import ProvisioningService


@pytest.mark.asyncio
async def test_create_snapshot_success(provisioning_service: ProvisioningService, mock_proxmox):
    """create_lxc_snapshot returns correct result dict."""
    # First create a container to snapshot
    await mock_proxmox.clone_container(9000, 200, "my-service")
    result = await provisioning_service.create_lxc_snapshot(200, "pre-update", "before update")
    assert result["vmid"] == 200
    assert result["snapshot_name"] == "pre-update"
    assert result["action"] == "created"


@pytest.mark.asyncio
async def test_create_snapshot_no_description(provisioning_service: ProvisioningService, mock_proxmox):
    """create_lxc_snapshot works without a description."""
    await mock_proxmox.clone_container(9000, 201, "svc2")
    result = await provisioning_service.create_lxc_snapshot(201, "snap1")
    assert result["snapshot_name"] == "snap1"
    assert result["action"] == "created"


@pytest.mark.asyncio
async def test_list_snapshots_empty(provisioning_service: ProvisioningService, mock_proxmox):
    """list_lxc_snapshots returns empty list when no snapshots exist."""
    await mock_proxmox.clone_container(9000, 202, "empty-svc")
    snapshots = await provisioning_service.list_lxc_snapshots(202)
    assert isinstance(snapshots, list)
    assert len(snapshots) == 0


@pytest.mark.asyncio
async def test_list_snapshots_after_create(provisioning_service: ProvisioningService, mock_proxmox):
    """list_lxc_snapshots returns created snapshots."""
    await mock_proxmox.clone_container(9000, 203, "svc3")
    await provisioning_service.create_lxc_snapshot(203, "snap-a", "first snapshot")
    await provisioning_service.create_lxc_snapshot(203, "snap-b", "second snapshot")
    snapshots = await provisioning_service.list_lxc_snapshots(203)
    assert len(snapshots) == 2
    names = {s["name"] for s in snapshots}
    assert "snap-a" in names
    assert "snap-b" in names


@pytest.mark.asyncio
async def test_rollback_snapshot_stopped_container(provisioning_service: ProvisioningService, mock_proxmox):
    """rollback_lxc_snapshot works on a stopped container."""
    await mock_proxmox.clone_container(9000, 204, "svc4")
    await provisioning_service.create_lxc_snapshot(204, "initial")
    result = await provisioning_service.rollback_lxc_snapshot(204, "initial")
    assert result["vmid"] == 204
    assert result["snapshot_name"] == "initial"
    assert result["action"] == "rolled_back"
    assert result["was_running"] is False


@pytest.mark.asyncio
async def test_rollback_snapshot_running_container_stops_it(
    provisioning_service: ProvisioningService, mock_proxmox
):
    """rollback_lxc_snapshot stops a running container before rollback when stop_if_running=True."""
    await mock_proxmox.clone_container(9000, 205, "svc5")
    await provisioning_service.create_lxc_snapshot(205, "pre-change")
    # Simulate running container
    mock_proxmox.containers[205]["status"] = "running"

    result = await provisioning_service.rollback_lxc_snapshot(205, "pre-change", stop_if_running=True)
    assert result["was_running"] is True
    assert result["action"] == "rolled_back"
    # Container should have been stopped (mock stop sets status to stopped)
    assert mock_proxmox.containers[205]["status"] == "stopped"


@pytest.mark.asyncio
async def test_rollback_snapshot_running_container_raises_when_not_allowed(
    provisioning_service: ProvisioningService, mock_proxmox
):
    """rollback_lxc_snapshot raises SnapshotError if container is running and stop_if_running=False."""
    await mock_proxmox.clone_container(9000, 206, "svc6")
    await provisioning_service.create_lxc_snapshot(206, "snap1")
    mock_proxmox.containers[206]["status"] = "running"

    with pytest.raises(SnapshotError) as exc_info:
        await provisioning_service.rollback_lxc_snapshot(206, "snap1", stop_if_running=False)
    assert "stop_if_running=True" in str(exc_info.value)
    assert exc_info.value.vmid == 206
