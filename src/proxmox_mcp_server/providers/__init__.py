"""Provider base classes (adapter interfaces).

Each provider defines the contract for an external service integration.
Concrete implementations live in sibling modules.  The base classes are
intentionally simple ABCs so the service layer never couples to a
particular HTTP client, library version, or API shape.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from proxmox_mcp_server.models.service import CommandResult


class BaseProxmoxProvider(ABC):
    """Adapter interface for Proxmox VE operations."""

    @abstractmethod
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
        """Clone an LXC template to a new container."""

    @abstractmethod
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
        """Apply network / resource configuration to an existing container."""

    @abstractmethod
    async def start_container(self, vmid: int, *, node: str | None = None) -> dict[str, Any]:
        """Start a stopped container."""

    @abstractmethod
    async def stop_container(self, vmid: int, *, node: str | None = None) -> dict[str, Any]:
        """Stop a running container."""

    @abstractmethod
    async def get_container_status(self, vmid: int, *, node: str | None = None) -> dict[str, Any]:
        """Return the current status dict for a container."""

    @abstractmethod
    async def execute_command(
        self,
        vmid: int,
        command: str,
        *,
        node: str | None = None,
        timeout: int = 60,
    ) -> CommandResult:
        """Execute a command inside a running container."""

    @abstractmethod
    async def execute_host_command(
        self,
        command: str,
        *,
        node: str | None = None,
        timeout: int = 60,
    ) -> CommandResult:
        """Execute a command directly on the Proxmox host (not inside a container)."""

    @abstractmethod
    async def get_next_vmid(self) -> int:
        """Return the next free VMID from Proxmox."""

    @abstractmethod
    async def create_snapshot(
        self,
        vmid: int,
        name: str,
        *,
        description: str = "",
        node: str | None = None,
    ) -> dict[str, Any]:
        """Create a snapshot of an LXC container."""

    @abstractmethod
    async def list_snapshots(
        self,
        vmid: int,
        *,
        node: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all snapshots of an LXC container."""

    @abstractmethod
    async def rollback_snapshot(
        self,
        vmid: int,
        name: str,
        *,
        node: str | None = None,
    ) -> dict[str, Any]:
        """Rollback an LXC container to a named snapshot."""

    @abstractmethod
    async def list_containers(
        self,
        *,
        node: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all LXC containers on the node."""

    @abstractmethod
    async def get_storage_status(
        self,
        storage: str,
        *,
        node: str | None = None,
    ) -> dict[str, Any]:
        """Return usage statistics for a Proxmox storage pool."""

    @abstractmethod
    async def resize_disk(
        self,
        vmid: int,
        size_gb: int,
        *,
        disk: str = "rootfs",
        node: str | None = None,
    ) -> dict[str, Any]:
        """Resize an LXC container disk (grow only)."""

    @abstractmethod
    async def get_task_status(
        self,
        upid: str,
        *,
        node: str | None = None,
    ) -> dict[str, Any]:
        """Return the current status of a Proxmox task by UPID."""

    @abstractmethod
    async def get_task_log(
        self,
        upid: str,
        *,
        limit: int = 50,
        node: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return the log lines of a Proxmox task by UPID."""

class BasePiHoleProvider(ABC):
    """Adapter interface for Pi-hole DNS management."""

    @abstractmethod
    async def add_dns_record(self, domain: str, target_ip: str) -> dict[str, Any]:
        """Create a local DNS A record.  Must be idempotent."""

    @abstractmethod
    async def delete_dns_record(self, domain: str, target_ip: str) -> dict[str, Any]:
        """Remove a local DNS record."""

    @abstractmethod
    async def get_dns_records(self) -> list[dict[str, str]]:
        """List all custom DNS records."""

    @abstractmethod
    async def record_exists(self, domain: str, target_ip: str) -> bool:
        """Return True if the exact record already exists."""


class BaseNpmProvider(ABC):
    """Adapter interface for Nginx Proxy Manager."""

    @abstractmethod
    async def create_proxy_host(
        self,
        domain: str,
        forward_host: str,
        forward_port: int,
        *,
        forward_scheme: str = "http",
    ) -> dict[str, Any]:
        """Create a proxy host.  Must be idempotent."""

    @abstractmethod
    async def get_proxy_hosts(self) -> list[dict[str, Any]]:
        """List all existing proxy hosts."""

    @abstractmethod
    async def find_proxy_host_by_domain(self, domain: str) -> dict[str, Any] | None:
        """Return the proxy host matching *domain*, or None."""

    @abstractmethod
    async def delete_proxy_host(self, host_id: int) -> None:
        """Delete a proxy host by its NPM ID."""


class BaseAgentProvider(ABC):
    """Adapter interface for running Agy bootstraps inside containers."""

    @abstractmethod
    async def run_bootstrap(
        self,
        vmid: int,
        prompt: str,
        *,
        working_dir: str | None = None,
    ) -> CommandResult:
        """Execute an Agy session inside the specified container."""

    @abstractmethod
    async def run_on_host(
        self,
        prompt: str,
        *,
        working_dir: str | None = None,
    ) -> CommandResult:
        """Execute an Agy session directly on the Proxmox host."""
