"""Tests for Proxmox host operations: exec_host_command and run_host_agy."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from proxmox_mcp_server.services.provisioning import ProvisioningService


# ------------------------------------------------------------------
# exec_host_command
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exec_host_command_success(
    provisioning_service: ProvisioningService,
) -> None:
    """exec_host_command returns structured dict with exit_code and stdout."""
    result = await provisioning_service.exec_host_command("pveversion")
    assert result["command"] == "pveversion"
    assert result["exit_code"] == 0
    assert "stdout" in result
    assert "stderr" in result
    assert "duration_seconds" in result


@pytest.mark.asyncio
async def test_exec_host_command_custom_timeout(
    provisioning_service: ProvisioningService,
) -> None:
    """exec_host_command accepts custom timeout."""
    result = await provisioning_service.exec_host_command("zpool status", timeout=120)
    assert result["command"] == "zpool status"
    assert result["exit_code"] == 0


# ------------------------------------------------------------------
# run_host_agy
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_host_agy_success(
    provisioning_service: ProvisioningService,
) -> None:
    """run_host_agy returns structured execution metadata."""
    prompt = "Check storage pools and alert on high usage"
    result = await provisioning_service.run_host_agy(prompt=prompt)
    assert result["action"] == "run_host_agy"
    assert result["exit_code"] == 0
    assert "stdout" in result
    assert "stderr" in result
    assert "duration_seconds" in result


@pytest.mark.asyncio
async def test_run_host_agy_custom_working_dir(
    provisioning_service: ProvisioningService,
) -> None:
    """run_host_agy passes working_dir to the Agy provider."""
    result = await provisioning_service.run_host_agy(
        prompt="List backup files",
        working_dir="/var/lib/vz/dump",
    )
    assert result["exit_code"] == 0
