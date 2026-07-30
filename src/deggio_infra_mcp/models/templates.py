"""Pydantic models for LXC template definitions."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TemplateInfo(BaseModel):
    """Describes a configured LXC template available for cloning."""

    key: str = Field(description="Short identifier for the template (e.g. 'base', 'gpu')")
    source_vmid: int = Field(description="VMID of the template container in Proxmox")
    description: str = Field(default="", description="Human-readable description")
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    default_cores: int = Field(default=2)
    default_memory_mb: int = Field(default=2048)
    default_disk_gb: int = Field(default=20)
    storage: str = Field(default="local-lvm", description="Proxmox storage target")
