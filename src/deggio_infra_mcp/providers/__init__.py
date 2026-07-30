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
    from deggio_infra_mcp.models.service import CommandResult


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
    async def get_next_vmid(self) -> int:
        """Return the next free VMID from Proxmox."""


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


class BaseAgyProvider(ABC):
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
