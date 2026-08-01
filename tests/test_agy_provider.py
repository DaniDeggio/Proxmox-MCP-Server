"""Tests for the Agy provider."""

from __future__ import annotations

from typing import Any

import pytest

from proxmox_mcp_server.config import AgyConfig
from proxmox_mcp_server.models.errors import AgentExecutionError
from proxmox_mcp_server.models.service import CommandResult
from proxmox_mcp_server.providers import BaseProxmoxProvider
from proxmox_mcp_server.providers.agy import AgyProvider


class FakeProxmoxForAgy(BaseProxmoxProvider):
    """Minimal Proxmox mock that only implements execute_command."""

    def __init__(self, result: CommandResult | None = None, error: Exception | None = None) -> None:
        self._result = result or CommandResult(exit_code=0, stdout="OK", stderr="", duration_seconds=1.0)
        self._error = error
        self.last_command: str = ""
        self.last_vmid: int = 0
        self.last_timeout: int = 0

    async def clone_container(self, source_vmid: int, new_vmid: int, hostname: str, **kwargs: Any) -> dict[str, Any]:
        return {}

    async def configure_container(self, vmid: int, **kwargs: Any) -> dict[str, Any]:
        return {}

    async def start_container(self, vmid: int, **kwargs: Any) -> dict[str, Any]:
        return {}

    async def stop_container(self, vmid: int, **kwargs: Any) -> dict[str, Any]:
        return {}

    async def get_container_status(self, vmid: int, **kwargs: Any) -> dict[str, Any]:
        return {}

    async def execute_command(self, vmid: int, command: str, **kwargs: Any) -> CommandResult:
        self.last_vmid = vmid
        self.last_command = command
        self.last_timeout = kwargs.get("timeout", 60)
        if self._error:
            raise self._error
        return self._result

    async def execute_host_command(self, command: str, **kwargs: Any) -> CommandResult:
        self.last_command = command
        self.last_timeout = kwargs.get("timeout", 60)
        if self._error:
            raise self._error
        return self._result

    async def get_next_vmid(self) -> int:
        return 100

    async def create_snapshot(self, vmid: int, name: str, **kwargs: Any) -> dict[str, Any]:
        return {"vmid": vmid, "snapshot_name": name, "action": "created"}

    async def list_snapshots(self, vmid: int, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def rollback_snapshot(self, vmid: int, name: str, **kwargs: Any) -> dict[str, Any]:
        return {"vmid": vmid, "snapshot_name": name, "action": "rolled_back"}

    async def list_containers(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def get_storage_status(self, storage: str, **kwargs: Any) -> dict[str, Any]:
        return {"storage": storage, "total_gb": 100.0, "used_gb": 40.0, "avail_gb": 60.0, "used_pct": 40.0}

    async def resize_disk(self, vmid: int, size_gb: int, **kwargs: Any) -> dict[str, Any]:
        return {"vmid": vmid, "new_size_gb": size_gb, "action": "resized"}

    async def get_task_status(self, upid: str, **kwargs: Any) -> dict[str, Any]:
        return {"upid": upid, "status": "stopped", "exitstatus": "OK"}

    async def get_task_log(self, upid: str, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"n": 1, "t": "done"}]



class TestAgyBootstrap:
    """Tests for Agy bootstrap execution."""

    @pytest.mark.asyncio
    async def test_successful_bootstrap(self) -> None:
        proxmox = FakeProxmoxForAgy(
            result=CommandResult(exit_code=0, stdout="Done", stderr="", duration_seconds=3.5)
        )
        agy = AgyProvider(AgyConfig(command="agy", timeout_seconds=600), proxmox=proxmox)

        result = await agy.run_bootstrap(vmid=200, prompt="Install nginx")

        assert result.exit_code == 0
        assert result.stdout == "Done"
        assert proxmox.last_vmid == 200
        assert "Install nginx" in proxmox.last_command
        assert "agy" in proxmox.last_command

    @pytest.mark.asyncio
    async def test_custom_working_dir(self) -> None:
        proxmox = FakeProxmoxForAgy()
        agy = AgyProvider(AgyConfig(command="agy"), proxmox=proxmox)

        await agy.run_bootstrap(vmid=201, prompt="hello", working_dir="/opt/app")

        assert "cd /opt/app" in proxmox.last_command

    @pytest.mark.asyncio
    async def test_default_working_dir(self) -> None:
        proxmox = FakeProxmoxForAgy()
        agy = AgyProvider(AgyConfig(command="agy", working_dir="/srv"), proxmox=proxmox)

        await agy.run_bootstrap(vmid=202, prompt="hello")

        assert "cd /srv" in proxmox.last_command

    @pytest.mark.asyncio
    async def test_nonzero_exit_raises(self) -> None:
        proxmox = FakeProxmoxForAgy(
            result=CommandResult(exit_code=1, stdout="", stderr="Error", duration_seconds=1.0)
        )
        agy = AgyProvider(AgyConfig(command="agy"), proxmox=proxmox)

        with pytest.raises(AgentExecutionError, match="exited with code 1"):
            await agy.run_bootstrap(vmid=203, prompt="fail")

    @pytest.mark.asyncio
    async def test_execution_error_wrapped(self) -> None:
        proxmox = FakeProxmoxForAgy(error=RuntimeError("SSH connection refused"))
        agy = AgyProvider(AgyConfig(command="agy"), proxmox=proxmox)

        with pytest.raises(AgentExecutionError, match="SSH connection refused"):
            await agy.run_bootstrap(vmid=204, prompt="fail")

    @pytest.mark.asyncio
    async def test_timeout_passed_to_proxmox(self) -> None:
        proxmox = FakeProxmoxForAgy()
        agy = AgyProvider(AgyConfig(command="agy", timeout_seconds=120), proxmox=proxmox)

        await agy.run_bootstrap(vmid=205, prompt="slow task")

        assert proxmox.last_timeout == 120

    @pytest.mark.asyncio
    async def test_custom_command(self) -> None:
        proxmox = FakeProxmoxForAgy()
        agy = AgyProvider(AgyConfig(command="/usr/local/bin/my-agy"), proxmox=proxmox)

        await agy.run_bootstrap(vmid=206, prompt="test")

        assert "/usr/local/bin/my-agy" in proxmox.last_command
