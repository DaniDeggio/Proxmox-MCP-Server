"""Pydantic models for service provisioning requests and results."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ServiceType(StrEnum):
    """Broad classification of the service being provisioned."""

    WEB_APP = "web_app"
    API_SERVICE = "api_service"
    DATABASE = "database"
    MONITORING = "monitoring"
    WORKER = "worker"
    CUSTOM = "custom"


class StepStatus(StrEnum):
    """Outcome of an individual orchestration step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepResult(BaseModel):
    """Tracks the outcome of a single orchestration step."""

    name: str
    status: StepStatus = StepStatus.PENDING
    message: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    data: dict | None = None

    def mark_running(self) -> None:
        self.status = StepStatus.RUNNING
        self.started_at = datetime.now()

    def mark_completed(self, message: str = "", data: dict | None = None) -> None:
        self.status = StepStatus.COMPLETED
        self.message = message
        self.completed_at = datetime.now()
        if data:
            self.data = data

    def mark_failed(self, message: str, data: dict | None = None) -> None:
        self.status = StepStatus.FAILED
        self.message = message
        self.completed_at = datetime.now()
        if data:
            self.data = data


class ServiceRequest(BaseModel):
    """Input parameters for the create_service orchestration tool."""

    service_name: str = Field(description="Name of the service (used for hostname, DNS, etc.)")
    service_type: ServiceType = Field(default=ServiceType.WEB_APP)
    template_key: str = Field(default="base", description="Template identifier from config")
    vmid: int | None = Field(default=None, description="Explicit VMID, or auto-select if None")
    tags: list[str] = Field(default_factory=list, description="Extra tags for the container")
    forward_port: int = Field(default=80, description="Port the service listens on inside the LXC")
    forward_scheme: str = Field(default="http", description="http or https")
    # Agy bootstrap
    repo_urls: list[str] = Field(default_factory=list, description="Git repos for Agy to clone")
    docs_urls: list[str] = Field(default_factory=list, description="Documentation URLs for Agy")
    extra_requirements: str = Field(
        default="", description="Free-text requirements for Agy prompt"
    )
    skip_dns: bool = Field(default=False, description="Skip Pi-hole DNS record creation")
    skip_proxy: bool = Field(default=False, description="Skip NPM proxy host creation")
    skip_agy: bool = Field(default=False, description="Skip Agy bootstrap execution")


class ServiceResult(BaseModel):
    """Structured output from the create_service orchestration flow."""

    success: bool = False
    correlation_id: str = ""
    vmid: int | None = None
    hostname: str = ""
    domain: str = ""
    ip: str = ""
    template_key: str = ""
    proxy_target: str = ""
    steps: list[StepResult] = Field(default_factory=list)
    failure_point: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def completed_steps(self) -> list[str]:
        return [s.name for s in self.steps if s.status == StepStatus.COMPLETED]

    def to_summary(self) -> dict:
        """Return a concise dict for MCP tool response."""
        return {
            "success": self.success,
            "correlation_id": self.correlation_id,
            "vmid": self.vmid,
            "hostname": self.hostname,
            "domain": self.domain,
            "ip": self.ip,
            "template_key": self.template_key,
            "proxy_target": self.proxy_target,
            "completed_steps": self.completed_steps,
            "failure_point": self.failure_point,
            "error_message": self.error_message,
        }


class CommandResult(BaseModel):
    """Result of a command execution inside a container."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
