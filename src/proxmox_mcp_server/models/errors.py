"""Domain-specific exceptions for proxmox_mcp_server.

Each exception maps to a clear failure domain so callers can handle
errors precisely without catching overly broad exception types.
"""

from __future__ import annotations


class ProxmoxMcpError(Exception):
    """Base exception for all proxmox_mcp_server errors."""

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ConfigError(ProxmoxMcpError):
    """Configuration loading or validation failure."""


class ProxmoxOperationError(ProxmoxMcpError):
    """A Proxmox API call failed."""

    def __init__(
        self,
        message: str,
        *,
        vmid: int | None = None,
        operation: str | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.vmid = vmid
        self.operation = operation


class IpAllocationError(ProxmoxMcpError):
    """IP allocation or release failed (exhausted range, conflict, etc.)."""


class PiHoleError(ProxmoxMcpError):
    """Pi-hole API call failed."""


class NpmError(ProxmoxMcpError):
    """Nginx Proxy Manager API call failed."""


class SnapshotError(ProxmoxMcpError):
    """A snapshot or rollback operation failed."""

    def __init__(
        self,
        message: str,
        *,
        vmid: int | None = None,
        snapshot_name: str | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.vmid = vmid
        self.snapshot_name = snapshot_name


class AgentExecutionError(ProxmoxMcpError):
    """Agy bootstrap execution failed inside a container."""

    def __init__(
        self,
        message: str,
        *,
        vmid: int | None = None,
        exit_code: int | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.vmid = vmid
        self.exit_code = exit_code


class ServiceProvisioningError(ProxmoxMcpError):
    """The create_service orchestration flow failed.

    Carries partial results so the caller can inspect what succeeded.
    """

    def __init__(
        self,
        message: str,
        *,
        failed_step: str | None = None,
        completed_steps: list[str] | None = None,
        partial_result: dict | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.failed_step = failed_step
        self.completed_steps = completed_steps or []
        self.partial_result = partial_result or {}
