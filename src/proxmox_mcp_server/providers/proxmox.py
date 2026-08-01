"""Proxmox provider — uses ``proxmoxer`` directly (same library ProxmoxMCP-Plus
wraps) for LXC container operations.

Integration notes
-----------------
ProxmoxMCP-Plus is *not* imported as a library.  Its internal modules are
tightly coupled to their own config loader and MCP transport.  Using
``proxmoxer`` directly gives us the same Proxmox REST-API surface with
zero version coupling.

If you later run ProxmoxMCP-Plus as a *separate* MCP server alongside this
one, they will coexist without conflict — both use Proxmox API tokens.
"""

from __future__ import annotations

import asyncio
import time
from functools import partial
from typing import TYPE_CHECKING, Any

from proxmoxer import ProxmoxAPI

from proxmox_mcp_server.logging import get_logger
from proxmox_mcp_server.models.errors import ProxmoxOperationError
from proxmox_mcp_server.models.service import CommandResult
from proxmox_mcp_server.providers import BaseProxmoxProvider

if TYPE_CHECKING:
    from proxmox_mcp_server.config import ProxmoxConfig

log = get_logger("providers.proxmox")


class ProxmoxProvider(BaseProxmoxProvider):
    """Concrete Proxmox adapter using ``proxmoxer.ProxmoxAPI``."""

    def __init__(self, config: ProxmoxConfig) -> None:
        self._config = config
        self._node = config.node

        # Parse token_id into user and token_name
        # Expected format: "user@realm!token-name"
        token_parts = config.token_id.split("!")
        if len(token_parts) != 2:
            raise ProxmoxOperationError(
                f"Invalid token_id format '{config.token_id}'. "
                "Expected 'user@realm!token-name'.",
                operation="init",
            )

        self._api = ProxmoxAPI(
            config.host,
            port=config.port,
            user=token_parts[0],
            token_name=token_parts[1],
            token_value=config.token_secret,
            verify_ssl=config.verify_ssl,
            backend="https",
        )
        log.info(
            "proxmox_connected",
            host=config.host,
            port=config.port,
            node=config.node,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _run_sync(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a synchronous proxmoxer call in a thread so we stay async."""
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(None, partial(func, *args, **kwargs))

    def _node_name(self, node: str | None) -> str:
        return node or self._node

    async def _wait_for_task(
        self,
        node: str,
        upid: str,
        timeout: int = 300,
        poll: float = 3.0,
    ) -> dict[str, Any]:
        """Poll a Proxmox task UPID until completion or timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = await self._run_sync(
                self._api.nodes(node).tasks(upid).status.get
            )
            if isinstance(status, dict) and status.get("status") == "stopped":
                if status.get("exitstatus") == "OK":
                    return status
                raise ProxmoxOperationError(
                    f"Task {upid} failed: {status.get('exitstatus')}",
                    operation="wait_task",
                    details={"upid": upid, "status": status},
                )
            await asyncio.sleep(poll)
        raise ProxmoxOperationError(
            f"Task {upid} timed out after {timeout}s",
            operation="wait_task",
            details={"upid": upid},
        )

    # ------------------------------------------------------------------
    # Contract implementation
    # ------------------------------------------------------------------

    async def clone_container(
        self,
        source_vmid: int,
        new_vmid: int,
        hostname: str,
        *,
        node: str | None = None,
        storage: str | None = None,
        full_clone: bool = True,
    ) -> dict[str, Any]:
        n = self._node_name(node)
        log.info(
            "cloning_container",
            source_vmid=source_vmid,
            new_vmid=new_vmid,
            hostname=hostname,
            node=n,
        )
        try:
            params: dict[str, Any] = {
                "newid": new_vmid,
                "hostname": hostname,
                "full": 1 if full_clone else 0,
            }
            if storage:
                params["storage"] = storage

            upid = await self._run_sync(
                self._api.nodes(n).lxc(source_vmid).clone.post, **params
            )
            # clone returns a UPID string — wait for it
            if isinstance(upid, str):
                await self._wait_for_task(n, upid)
            log.info("clone_completed", new_vmid=new_vmid)
            return {"vmid": new_vmid, "hostname": hostname, "status": "cloned"}
        except ProxmoxOperationError:
            raise
        except Exception as exc:
            raise ProxmoxOperationError(
                f"Failed to clone VMID {source_vmid} → {new_vmid}: {exc}",
                vmid=source_vmid,
                operation="clone",
            ) from exc

    async def configure_container(
        self,
        vmid: int,
        *,
        hostname: str | None = None,
        ip: str | None = None,
        cidr: int = 24,
        gateway: str | None = None,
        nameserver: str | None = None,
        bridge: str = "vmbr0",
        cores: int | None = None,
        memory_mb: int | None = None,
        tags: list[str] | None = None,
        node: str | None = None,
    ) -> dict[str, Any]:
        n = self._node_name(node)
        log.info("configuring_container", vmid=vmid, node=n, ip=ip, hostname=hostname)
        try:
            params: dict[str, Any] = {}
            if hostname:
                params["hostname"] = hostname
            if ip and gateway:
                params["net0"] = (
                    f"name=eth0,bridge={bridge},"
                    f"ip={ip}/{cidr},gw={gateway}"
                )
            if nameserver:
                params["nameserver"] = nameserver
            if cores:
                params["cores"] = cores
            if memory_mb:
                params["memory"] = memory_mb
            if tags:
                params["tags"] = ";".join(tags)

            if params:
                await self._run_sync(
                    self._api.nodes(n).lxc(vmid).config.put, **params
                )
            return {"vmid": vmid, "configured": True, "params": params}
        except Exception as exc:
            raise ProxmoxOperationError(
                f"Failed to configure VMID {vmid}: {exc}",
                vmid=vmid,
                operation="configure",
            ) from exc

    async def start_container(self, vmid: int, *, node: str | None = None) -> dict[str, Any]:
        n = self._node_name(node)
        log.info("starting_container", vmid=vmid, node=n)
        try:
            upid = await self._run_sync(
                self._api.nodes(n).lxc(vmid).status.start.post
            )
            if isinstance(upid, str):
                await self._wait_for_task(n, upid)
            return {"vmid": vmid, "status": "started"}
        except ProxmoxOperationError:
            raise
        except Exception as exc:
            raise ProxmoxOperationError(
                f"Failed to start VMID {vmid}: {exc}",
                vmid=vmid,
                operation="start",
            ) from exc

    async def stop_container(self, vmid: int, *, node: str | None = None) -> dict[str, Any]:
        n = self._node_name(node)
        log.info("stopping_container", vmid=vmid, node=n)
        try:
            upid = await self._run_sync(
                self._api.nodes(n).lxc(vmid).status.stop.post
            )
            if isinstance(upid, str):
                await self._wait_for_task(n, upid)
            return {"vmid": vmid, "status": "stopped"}
        except ProxmoxOperationError:
            raise
        except Exception as exc:
            raise ProxmoxOperationError(
                f"Failed to stop VMID {vmid}: {exc}",
                vmid=vmid,
                operation="stop",
            ) from exc

    async def get_container_status(
        self, vmid: int, *, node: str | None = None
    ) -> dict[str, Any]:
        n = self._node_name(node)
        try:
            raw = await self._run_sync(
                self._api.nodes(n).lxc(vmid).status.current.get
            )
            if isinstance(raw, dict):
                return raw
            return {"raw": raw}
        except Exception as exc:
            raise ProxmoxOperationError(
                f"Failed to get status for VMID {vmid}: {exc}",
                vmid=vmid,
                operation="status",
            ) from exc

    async def execute_command(
        self,
        vmid: int,
        command: str,
        *,
        node: str | None = None,
        timeout: int = 60,
    ) -> CommandResult:
        """Execute a command inside the container via SSH.

        Uses Proxmox host SSH → ``pct exec <vmid> -- <command>`` because
        the Proxmox REST API does not provide a reliable exec endpoint
        for LXC containers (unlike QEMU guest agent).
        """
        n = self._node_name(node)
        log.info("executing_command", vmid=vmid, node=n, command=command[:80])
        ssh_cfg = self._config.ssh

        if not ssh_cfg.host:
            raise ProxmoxOperationError(
                "SSH config not set — cannot execute commands in containers",
                vmid=vmid,
                operation="exec",
            )

        start = time.monotonic()
        try:
            import paramiko

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connect_kwargs: dict[str, Any] = {
                "hostname": ssh_cfg.host,
                "port": ssh_cfg.port,
                "username": ssh_cfg.user,
                "timeout": 10,
            }
            if ssh_cfg.key_file:
                connect_kwargs["key_filename"] = ssh_cfg.key_file
            client.connect(**connect_kwargs)

            full_cmd = f"pct exec {vmid} -- bash -c {_shell_quote(command)}"
            _, stdout_ch, stderr_ch = client.exec_command(full_cmd, timeout=timeout)
            exit_code = stdout_ch.channel.recv_exit_status()
            stdout = stdout_ch.read().decode(errors="replace")
            stderr = stderr_ch.read().decode(errors="replace")
            client.close()

            duration = time.monotonic() - start
            return CommandResult(
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=round(duration, 2),
            )
        except Exception as exc:
            duration = time.monotonic() - start
            raise ProxmoxOperationError(
                f"Command execution failed in VMID {vmid}: {exc}",
                vmid=vmid,
                operation="exec",
            ) from exc


    async def execute_host_command(
        self,
        command: str,
        *,
        node: str | None = None,
        timeout: int = 60,
    ) -> CommandResult:
        """Execute a command directly on the Proxmox host via SSH."""
        n = self._node_name(node)
        log.info("executing_host_command", node=n, command=command[:80])
        ssh_cfg = self._config.ssh

        if not ssh_cfg.host:
            raise ProxmoxOperationError(
                "SSH config not set — cannot execute commands on Proxmox host",
                operation="exec_host",
            )

        start = time.monotonic()
        try:
            import paramiko

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connect_kwargs: dict[str, Any] = {
                "hostname": ssh_cfg.host,
                "port": ssh_cfg.port,
                "username": ssh_cfg.user,
                "timeout": 10,
            }
            if ssh_cfg.key_file:
                connect_kwargs["key_filename"] = ssh_cfg.key_file
            client.connect(**connect_kwargs)

            full_cmd = f"bash -c {_shell_quote(command)}"
            _, stdout_ch, stderr_ch = client.exec_command(full_cmd, timeout=timeout)
            exit_code = stdout_ch.channel.recv_exit_status()
            stdout = stdout_ch.read().decode(errors="replace")
            stderr = stderr_ch.read().decode(errors="replace")
            client.close()

            duration = time.monotonic() - start
            return CommandResult(
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=round(duration, 2),
            )
        except Exception as exc:
            duration = time.monotonic() - start
            raise ProxmoxOperationError(
                f"Host command execution failed: {exc}",
                operation="exec_host",
            ) from exc

    async def get_next_vmid(self) -> int:
        """Ask Proxmox for the next free VMID."""
        try:
            vmid = await self._run_sync(self._api.cluster.nextid.get)
            return int(vmid)
        except Exception as exc:
            raise ProxmoxOperationError(
                f"Failed to get next VMID: {exc}",
                operation="nextid",
            ) from exc

    # ------------------------------------------------------------------
    # Snapshot management
    # ------------------------------------------------------------------

    async def create_snapshot(
        self,
        vmid: int,
        name: str,
        *,
        description: str = "",
        node: str | None = None,
    ) -> dict[str, Any]:
        """Create a snapshot of an LXC container."""
        n = self._node_name(node)
        log.info("creating_snapshot", vmid=vmid, name=name, node=n)
        try:
            params: dict[str, Any] = {"snapname": name}
            if description:
                params["description"] = description
            upid = await self._run_sync(
                self._api.nodes(n).lxc(vmid).snapshot.post, **params
            )
            if isinstance(upid, str):
                await self._wait_for_task(n, upid)
            log.info("snapshot_created", vmid=vmid, name=name)
            return {"vmid": vmid, "snapshot_name": name, "action": "created"}
        except ProxmoxOperationError:
            raise
        except Exception as exc:
            raise ProxmoxOperationError(
                f"Failed to create snapshot '{name}' for VMID {vmid}: {exc}",
                vmid=vmid,
                operation="create_snapshot",
            ) from exc

    async def list_snapshots(
        self,
        vmid: int,
        *,
        node: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all snapshots of an LXC container."""
        n = self._node_name(node)
        try:
            raw = await self._run_sync(
                self._api.nodes(n).lxc(vmid).snapshot.get
            )
            if isinstance(raw, list):
                # Filter out the 'current' pseudo-snapshot Proxmox always returns
                return [s for s in raw if s.get("name") != "current"]
            return []
        except Exception as exc:
            raise ProxmoxOperationError(
                f"Failed to list snapshots for VMID {vmid}: {exc}",
                vmid=vmid,
                operation="list_snapshots",
            ) from exc

    async def rollback_snapshot(
        self,
        vmid: int,
        name: str,
        *,
        node: str | None = None,
    ) -> dict[str, Any]:
        """Rollback an LXC container to a named snapshot.

        Note: The container must be stopped before rolling back.
        The caller is responsible for stopping it first.
        """
        n = self._node_name(node)
        log.info("rolling_back_snapshot", vmid=vmid, name=name, node=n)
        try:
            upid = await self._run_sync(
                self._api.nodes(n).lxc(vmid).snapshot(name).rollback.post
            )
            if isinstance(upid, str):
                await self._wait_for_task(n, upid)
            log.info("snapshot_rolled_back", vmid=vmid, name=name)
            return {"vmid": vmid, "snapshot_name": name, "action": "rolled_back"}
        except ProxmoxOperationError:
            raise
        except Exception as exc:
            raise ProxmoxOperationError(
                f"Failed to rollback to snapshot '{name}' for VMID {vmid}: {exc}",
                vmid=vmid,
                operation="rollback_snapshot",
            ) from exc

    # ------------------------------------------------------------------
    # Infrastructure inspection
    # ------------------------------------------------------------------

    async def list_containers(
        self,
        *,
        node: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all LXC containers on the node."""
        n = self._node_name(node)
        try:
            raw = await self._run_sync(self._api.nodes(n).lxc.get)
            if isinstance(raw, list):
                return raw
            return []
        except Exception as exc:
            raise ProxmoxOperationError(
                f"Failed to list containers on node {n}: {exc}",
                operation="list_containers",
            ) from exc

    async def get_storage_status(
        self,
        storage: str,
        *,
        node: str | None = None,
    ) -> dict[str, Any]:
        """Return usage statistics for a Proxmox storage pool."""
        n = self._node_name(node)
        try:
            raw = await self._run_sync(
                self._api.nodes(n).storage(storage).status.get
            )
            if not isinstance(raw, dict):
                return {"storage": storage, "raw": raw}
            # Convert bytes to GB for human-readability
            total_bytes = raw.get("total", 0)
            used_bytes = raw.get("used", 0)
            avail_bytes = raw.get("avail", 0)
            _gb = 1024 ** 3
            return {
                "storage": storage,
                "total_gb": round(total_bytes / _gb, 2),
                "used_gb": round(used_bytes / _gb, 2),
                "avail_gb": round(avail_bytes / _gb, 2),
                "used_pct": round(used_bytes / total_bytes * 100, 1) if total_bytes else 0,
                "type": raw.get("type"),
                "enabled": raw.get("enabled", True),
            }
        except ProxmoxOperationError:
            raise
        except Exception as exc:
            raise ProxmoxOperationError(
                f"Failed to get storage status for '{storage}' on node {n}: {exc}",
                operation="storage_status",
            ) from exc

    # ------------------------------------------------------------------
    # Resource management
    # ------------------------------------------------------------------

    async def resize_disk(
        self,
        vmid: int,
        size_gb: int,
        *,
        disk: str = "rootfs",
        node: str | None = None,
    ) -> dict[str, Any]:
        """Resize an LXC container disk (grow only).

        Proxmox does not support shrinking disks, so we only allow
        increasing the size. The caller should validate that size_gb
        is larger than the current disk before calling this method.
        """
        n = self._node_name(node)
        log.info("resizing_disk", vmid=vmid, disk=disk, size_gb=size_gb, node=n)
        try:
            await self._run_sync(
                self._api.nodes(n).lxc(vmid).resize.put,
                disk=disk,
                size=f"{size_gb}G",
            )
            log.info("disk_resized", vmid=vmid, disk=disk, size_gb=size_gb)
            return {
                "vmid": vmid,
                "disk": disk,
                "new_size_gb": size_gb,
                "action": "resized",
            }
        except Exception as exc:
            raise ProxmoxOperationError(
                f"Failed to resize disk '{disk}' for VMID {vmid} to {size_gb}G: {exc}",
                vmid=vmid,
                operation="resize_disk",
            ) from exc

    # ------------------------------------------------------------------
    # Task tracking (expose internal _wait_for_task primitives)
    # ------------------------------------------------------------------

    async def get_task_status(
        self,
        upid: str,
        *,
        node: str | None = None,
    ) -> dict[str, Any]:
        """Return the current status of a Proxmox task by UPID."""
        n = self._node_name(node)
        try:
            raw = await self._run_sync(
                self._api.nodes(n).tasks(upid).status.get
            )
            if isinstance(raw, dict):
                return raw
            return {"upid": upid, "raw": raw}
        except Exception as exc:
            raise ProxmoxOperationError(
                f"Failed to get status for task {upid}: {exc}",
                operation="task_status",
            ) from exc

    async def get_task_log(
        self,
        upid: str,
        *,
        limit: int = 50,
        node: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return the log lines of a Proxmox task by UPID."""
        n = self._node_name(node)
        try:
            raw = await self._run_sync(
                self._api.nodes(n).tasks(upid).log.get,
                limit=limit,
            )
            if isinstance(raw, list):
                return raw
            return []
        except Exception as exc:
            raise ProxmoxOperationError(
                f"Failed to get log for task {upid}: {exc}",
                operation="task_log",
            ) from exc


def _shell_quote(s: str) -> str:
    """Minimally quote a string for bash -c."""
    return "'" + s.replace("'", "'\\''") + "'"
