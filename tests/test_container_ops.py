"""Tests for container operations: exec, logs, infra inspection, resource management, task tracking."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from proxmox_mcp_server.services.provisioning import ProvisioningService


# ------------------------------------------------------------------
# exec_lxc_command
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exec_lxc_command_success(provisioning_service: ProvisioningService, mock_proxmox):
    """exec_lxc_command returns structured dict with exit_code and stdout."""
    await mock_proxmox.clone_container(9000, 200, "svc")
    result = await provisioning_service.exec_lxc_command(200, "echo hello")
    assert result["vmid"] == 200
    assert result["command"] == "echo hello"
    assert result["exit_code"] == 0
    assert "stdout" in result
    assert "stderr" in result
    assert "duration_seconds" in result


@pytest.mark.asyncio
async def test_exec_lxc_command_includes_command_in_output(
    provisioning_service: ProvisioningService, mock_proxmox
):
    """exec_lxc_command echoes the command back in result for traceability."""
    await mock_proxmox.clone_container(9000, 201, "svc2")
    cmd = "systemctl status nginx"
    result = await provisioning_service.exec_lxc_command(201, cmd)
    assert result["command"] == cmd


# ------------------------------------------------------------------
# get_lxc_service_logs
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_lxc_service_logs_success(provisioning_service: ProvisioningService, mock_proxmox):
    """get_lxc_service_logs returns structured dict with logs and exit_code."""
    await mock_proxmox.clone_container(9000, 202, "svc3")
    result = await provisioning_service.get_lxc_service_logs(202, "nginx", lines=20)
    assert result["vmid"] == 202
    assert result["service_name"] == "nginx"
    assert "logs" in result
    assert "exit_code" in result


# ------------------------------------------------------------------
# list_containers
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_containers_empty(provisioning_service: ProvisioningService):
    """list_containers returns empty list when no containers exist."""
    containers = await provisioning_service.list_containers()
    assert isinstance(containers, list)
    assert len(containers) == 0


@pytest.mark.asyncio
async def test_list_containers_after_clone(provisioning_service: ProvisioningService, mock_proxmox):
    """list_containers returns all containers including manually-created ones."""
    await mock_proxmox.clone_container(9000, 200, "svc-a")
    await mock_proxmox.clone_container(9000, 201, "svc-b")
    containers = await provisioning_service.list_containers()
    assert len(containers) == 2
    vmids = {c["vmid"] for c in containers}
    assert 200 in vmids
    assert 201 in vmids


@pytest.mark.asyncio
async def test_list_containers_has_expected_fields(provisioning_service: ProvisioningService, mock_proxmox):
    """list_containers output includes required fields."""
    await mock_proxmox.clone_container(9000, 200, "my-svc")
    containers = await provisioning_service.list_containers()
    assert len(containers) == 1
    ct = containers[0]
    assert "vmid" in ct
    assert "name" in ct
    assert "status" in ct


# ------------------------------------------------------------------
# get_storage_status
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_storage_status_returns_gb_fields(provisioning_service: ProvisioningService):
    """get_storage_status returns human-readable GB fields."""
    result = await provisioning_service.get_storage_status("local-lvm")
    assert result["storage"] == "local-lvm"
    assert "total_gb" in result
    assert "used_gb" in result
    assert "avail_gb" in result
    assert "used_pct" in result
    assert isinstance(result["total_gb"], (int, float))


@pytest.mark.asyncio
async def test_get_storage_status_custom_storage(provisioning_service: ProvisioningService):
    """get_storage_status uses the provided storage pool name."""
    result = await provisioning_service.get_storage_status("local")
    assert result["storage"] == "local"


# ------------------------------------------------------------------
# resize_lxc_disk
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resize_lxc_disk_success(provisioning_service: ProvisioningService, mock_proxmox):
    """resize_lxc_disk returns correct result dict."""
    await mock_proxmox.clone_container(9000, 200, "svc")
    result = await provisioning_service.resize_lxc_disk(200, 40)
    assert result["vmid"] == 200
    assert result["new_size_gb"] == 40
    assert result["disk"] == "rootfs"
    assert result["action"] == "resized"


@pytest.mark.asyncio
async def test_resize_lxc_disk_custom_disk(provisioning_service: ProvisioningService, mock_proxmox):
    """resize_lxc_disk uses the provided disk identifier."""
    await mock_proxmox.clone_container(9000, 201, "svc2")
    result = await provisioning_service.resize_lxc_disk(201, 100, "mp0")
    assert result["disk"] == "mp0"
    assert result["new_size_gb"] == 100


@pytest.mark.asyncio
async def test_resize_lxc_disk_rejects_zero(provisioning_service: ProvisioningService, mock_proxmox):
    """resize_lxc_disk raises ValueError for size_gb <= 0."""
    await mock_proxmox.clone_container(9000, 202, "svc3")
    with pytest.raises(ValueError, match="positive integer"):
        await provisioning_service.resize_lxc_disk(202, 0)


@pytest.mark.asyncio
async def test_resize_lxc_disk_rejects_negative(provisioning_service: ProvisioningService, mock_proxmox):
    """resize_lxc_disk raises ValueError for negative size_gb."""
    await mock_proxmox.clone_container(9000, 203, "svc4")
    with pytest.raises(ValueError):
        await provisioning_service.resize_lxc_disk(203, -10)


# ------------------------------------------------------------------
# update_lxc_resources
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_lxc_resources_cores_only(provisioning_service: ProvisioningService, mock_proxmox):
    """update_lxc_resources updates cores when only cores is provided."""
    await mock_proxmox.clone_container(9000, 200, "svc")
    result = await provisioning_service.update_lxc_resources(200, cores=4)
    assert result["vmid"] == 200
    assert result["action"] == "updated"
    assert result["updated_params"]["cores"] == 4


@pytest.mark.asyncio
async def test_update_lxc_resources_memory_only(provisioning_service: ProvisioningService, mock_proxmox):
    """update_lxc_resources updates memory when only memory_mb is provided."""
    await mock_proxmox.clone_container(9000, 201, "svc2")
    result = await provisioning_service.update_lxc_resources(201, memory_mb=4096)
    assert result["updated_params"]["memory_mb"] == 4096


@pytest.mark.asyncio
async def test_update_lxc_resources_all_params(provisioning_service: ProvisioningService, mock_proxmox):
    """update_lxc_resources accepts cores, memory_mb, and swap_mb together."""
    await mock_proxmox.clone_container(9000, 202, "svc3")
    result = await provisioning_service.update_lxc_resources(202, cores=2, memory_mb=2048, swap_mb=512)
    assert result["updated_params"]["cores"] == 2
    assert result["updated_params"]["memory_mb"] == 2048
    assert result["updated_params"]["swap_mb"] == 512


@pytest.mark.asyncio
async def test_update_lxc_resources_no_params_returns_no_change(
    provisioning_service: ProvisioningService, mock_proxmox
):
    """update_lxc_resources returns no_change when no params provided."""
    await mock_proxmox.clone_container(9000, 203, "svc4")
    result = await provisioning_service.update_lxc_resources(203)
    assert result["action"] == "no_change"
    assert result["updated_params"] == {}


# ------------------------------------------------------------------
# get_task_status and get_task_log
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_task_status_returns_status_dict(provisioning_service: ProvisioningService):
    """get_task_status returns a dict with status and exitstatus fields."""
    result = await provisioning_service.get_task_status("UPID:pve:00001234:test::")
    assert "status" in result
    assert "exitstatus" in result


@pytest.mark.asyncio
async def test_get_task_log_returns_list(provisioning_service: ProvisioningService):
    """get_task_log returns a list of log line dicts."""
    log_lines = await provisioning_service.get_task_log("UPID:pve:00001234:test::")
    assert isinstance(log_lines, list)
    assert len(log_lines) > 0
    assert "n" in log_lines[0]
    assert "t" in log_lines[0]


@pytest.mark.asyncio
async def test_get_task_log_respects_limit(provisioning_service: ProvisioningService):
    """get_task_log passes limit to the provider."""
    # Mock returns 1 line regardless; just verify no error with various limits
    log_lines = await provisioning_service.get_task_log("UPID:pve:00001234:test::", limit=10)
    assert isinstance(log_lines, list)
