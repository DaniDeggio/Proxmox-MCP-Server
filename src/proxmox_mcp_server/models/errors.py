"""Domain-specific exceptions for proxmox_mcp_server.

Each exception maps to a clear failure domain so callers can handle
errors precisely without catching overly broad exception types.
"""

from __future__ import annotations

from typing import Any


class ProxmoxMcpError(Exception):
    """Base exception for all proxmox_mcp_server errors."""

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        resource_type: str | None = None,
        resource_id: str | int | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.details = details or {}
        self.retryable = retryable


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
        resource_type: str | None = None,
        resource_id: str | int | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            message,
            operation=operation or "proxmox_operation",
            resource_type=resource_type or "vmid",
            resource_id=resource_id if resource_id is not None else vmid,
            details=details,
            retryable=retryable,
        )
        self.vmid = vmid


class IpAllocationError(ProxmoxMcpError):
    """IP allocation or release failed (exhausted range, conflict, etc.)."""

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = "allocate_ip",
        resource_type: str | None = "ip",
        resource_id: str | int | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            message,
            operation=operation,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            retryable=retryable,
        )


class PiHoleError(ProxmoxMcpError):
    """Pi-hole API call failed."""

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = "pihole_dns",
        resource_type: str | None = "domain",
        resource_id: str | int | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            message,
            operation=operation,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            retryable=retryable,
        )


class NpmError(ProxmoxMcpError):
    """Nginx Proxy Manager API call failed."""

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = "npm_proxy",
        resource_type: str | None = "domain",
        resource_id: str | int | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            message,
            operation=operation,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            retryable=retryable,
        )


class SnapshotError(ProxmoxMcpError):
    """A snapshot or rollback operation failed."""

    def __init__(
        self,
        message: str,
        *,
        vmid: int | None = None,
        snapshot_name: str | None = None,
        operation: str | None = "snapshot_operation",
        resource_type: str | None = "snapshot",
        resource_id: str | int | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            message,
            operation=operation,
            resource_type=resource_type,
            resource_id=resource_id if resource_id is not None else snapshot_name,
            details=details,
            retryable=retryable,
        )
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
        operation: str | None = "agent_bootstrap",
        resource_type: str | None = "vmid",
        resource_id: str | int | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            message,
            operation=operation,
            resource_type=resource_type,
            resource_id=resource_id if resource_id is not None else vmid,
            details=details,
            retryable=retryable,
        )
        self.vmid = vmid
        self.exit_code = exit_code


class ServiceProvisioningError(ProxmoxMcpError):
    """The create_service orchestration flow failed.

    Carries partial results and rollback state so callers can inspect what succeeded.
    """

    def __init__(
        self,
        message: str,
        *,
        failed_step: str | None = None,
        completed_steps: list[str] | None = None,
        partial_result: dict[str, Any] | None = None,
        rollback_performed: bool = False,
        manual_cleanup_required: bool = False,
        partial_resources: dict[str, Any] | None = None,
        operation: str | None = "create_service",
        resource_type: str | None = "service",
        resource_id: str | int | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            message,
            operation=operation,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            retryable=retryable,
        )
        self.failed_step = failed_step
        self.completed_steps = completed_steps or []
        self.partial_result = partial_result or {}
        self.rollback_performed = rollback_performed
        self.manual_cleanup_required = manual_cleanup_required
        self.partial_resources = partial_resources or {}


class PartialProvisioningError(ServiceProvisioningError):
    """Specialized ServiceProvisioningError raised when partial failure occurs and rollback is triggered."""
