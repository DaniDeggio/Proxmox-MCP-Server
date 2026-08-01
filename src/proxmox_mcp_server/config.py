"""Application configuration — loads YAML config with env var interpolation.

Configuration is split into typed Pydantic models, one per concern.
The top-level ``load_config`` helper reads a YAML file, interpolates
``${ENV_VAR}`` references, and returns a validated ``AppConfig`` instance.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from proxmox_mcp_server.models.errors import ConfigError
from proxmox_mcp_server.models.templates import TemplateInfo

# ---------------------------------------------------------------------------
# Env-var interpolation helper
# ---------------------------------------------------------------------------

_ENV_RE = re.compile(r"\$\{(\w+)(?::([^}]*))?\}")


def _interpolate_env(value: Any) -> Any:
    """Recursively replace ``${VAR}`` or ``${VAR:default}`` in strings."""
    if isinstance(value, str):
        def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
            var_name = str(m.group(1))
            default = m.group(2)
            if default is not None:
                default = str(default)
            env_val = os.environ.get(var_name)
            if env_val is not None:
                return env_val  # type: ignore[no-any-return]
            if default is not None:
                return str(default)
            return str(m.group(0))  # leave unresolved placeholder as-is

        return _ENV_RE.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Config section models
# ---------------------------------------------------------------------------


class SshConfig(BaseModel):
    host: str = ""
    port: int = 22
    user: str = "root"
    key_file: str = ""


class ProxmoxConfig(BaseModel):
    host: str
    port: int = 8006
    verify_ssl: bool = False
    node: str = "pve"
    token_id: str = ""
    token_secret: str = ""
    ssh: SshConfig = Field(default_factory=SshConfig)


class TemplatesConfig(BaseModel):
    """Dict of template_key -> TemplateInfo, built from raw YAML dicts."""

    templates: dict[str, TemplateInfo] = Field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> TemplatesConfig:
        templates: dict[str, TemplateInfo] = {}
        for key, val in raw.items():
            if isinstance(val, dict):
                templates[key] = TemplateInfo(key=key, **val)
        return cls(templates=templates)


class NetworkConfig(BaseModel):
    bridge: str = "vmbr0"
    gateway: str = "192.168.1.1"
    cidr: int = 24
    ip_range_start: str = "192.168.1.200"
    ip_range_end: str = "192.168.1.250"
    nameserver: str = "192.168.1.53"
    state_file: str = "state/ip_reservations.json"


class PiHoleConfig(BaseModel):
    url: str
    password: str = ""
    verify_ssl: bool = False


class NpmDefaultsConfig(BaseModel):
    access_list_id: int = 0
    certificate_id: int = 0
    ssl_forced: bool = False
    allow_websocket_upgrade: bool = True
    block_exploits: bool = True
    http2_support: bool = False


class NpmConfig(BaseModel):
    url: str
    username: str = ""
    password: str = ""
    verify_ssl: bool = False
    defaults: NpmDefaultsConfig = Field(default_factory=NpmDefaultsConfig)


class DomainsConfig(BaseModel):
    local_suffix: str = "homelab.local"


class AgyConfig(BaseModel):
    command: str = "agy"
    default_user: str = "root"
    timeout_seconds: int = 600
    working_dir: str = "/root"
    skip_permissions: bool = True


class AppSettings(BaseModel):
    log_level: str = "INFO"
    log_format: str = "console"
    state_dir: str = "state"
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, v: str) -> str:
        return v.upper()

    @field_validator("transport")
    @classmethod
    def _normalise_transport(cls, v: str) -> str:
        v = v.lower()
        if v not in {"stdio", "http", "sse", "streamable-http"}:
            raise ValueError(
                f"Unknown transport: {v}. Must be one of stdio, http, sse, streamable-http"
            )
        return v



# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------


class AppConfig(BaseModel):
    """Top-level application configuration."""

    proxmox: ProxmoxConfig
    templates: TemplatesConfig = Field(default_factory=TemplatesConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    pihole: PiHoleConfig
    npm: NpmConfig
    domains: DomainsConfig = Field(default_factory=DomainsConfig)
    agy: AgyConfig = Field(default_factory=AgyConfig)
    app: AppSettings = Field(default_factory=AppSettings)

    def get_template(self, key: str) -> TemplateInfo | None:
        """Return a template by key, or ``None``."""
        return self.templates.templates.get(key)

    def list_templates(self) -> list[TemplateInfo]:
        """Return all configured templates."""
        return list(self.templates.templates.values())


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load and validate the YAML configuration file.

    Args:
        path: Explicit config path.  Falls back to ``PROXMOX_MCP_CONFIG``
              env var, then ``config/config.yaml``.

    Returns:
        Validated ``AppConfig`` instance.

    Raises:
        ConfigError: If the file is missing, unreadable, or fails validation.
    """
    if path is None:
        path = os.environ.get("PROXMOX_MCP_CONFIG", "config/config.yaml")

    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Configuration file not found: {config_path}")

    try:
        raw_text = config_path.read_text(encoding="utf-8")
        raw = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {config_path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Cannot read {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Expected a YAML mapping at top level in {config_path}")

    # Interpolate env vars throughout the tree
    raw = _interpolate_env(raw)

    # Build templates from the raw 'templates' section
    templates_raw = raw.pop("templates", {})
    templates_cfg = TemplatesConfig.from_raw(templates_raw) if templates_raw else TemplatesConfig()

    try:
        config = AppConfig(templates=templates_cfg, **raw)
    except Exception as exc:
        raise ConfigError(f"Configuration validation failed: {exc}") from exc

    # Ensure state directory exists
    state_dir = Path(config.app.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    return config
