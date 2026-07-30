"""Tests for config loading and validation."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from deggio_infra_mcp.config import load_config
from deggio_infra_mcp.models.errors import ConfigError

if TYPE_CHECKING:
    from pathlib import Path

MINIMAL_CONFIG = """\
proxmox:
  host: "192.168.1.100"
  port: 8006
  node: "pve"
  token_id: "test@pam!token"
  token_secret: "secret"

pihole:
  url: "http://192.168.1.53"

npm:
  url: "http://192.168.1.80:81"
"""

FULL_CONFIG = """\
proxmox:
  host: "192.168.1.100"
  port: 8006
  verify_ssl: false
  node: "pve"
  token_id: "test@pam!token"
  token_secret: "secret"

templates:
  base:
    source_vmid: 9000
    description: "Base template"
    tags: ["base"]
  gpu:
    source_vmid: 9001
    description: "GPU template"

network:
  bridge: "vmbr0"
  gateway: "192.168.1.1"
  ip_range_start: "192.168.1.200"
  ip_range_end: "192.168.1.250"

pihole:
  url: "http://192.168.1.53"
  password: "test"

npm:
  url: "http://192.168.1.80:81"
  username: "admin@test.com"
  password: "test"

domains:
  local_suffix: "deggio.local"

app:
  log_level: "DEBUG"
"""

ENV_VAR_CONFIG = """\
proxmox:
  host: "192.168.1.100"
  token_id: "${TEST_TOKEN_ID}"
  token_secret: "${TEST_TOKEN_SECRET}"

pihole:
  url: "http://192.168.1.53"
  password: "${TEST_PIHOLE_PW}"

npm:
  url: "http://192.168.1.80:81"
"""


class TestConfigLoading:
    """Tests for YAML config file loading."""

    def test_load_minimal_config(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(MINIMAL_CONFIG)
        # Override state dir so it's under tmp_path
        config = load_config(config_file)
        assert config.proxmox.host == "192.168.1.100"
        assert config.proxmox.port == 8006
        assert config.pihole.url == "http://192.168.1.53"

    def test_load_full_config(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(FULL_CONFIG)
        config = load_config(config_file)
        assert len(config.list_templates()) == 2
        assert config.get_template("base") is not None
        assert config.get_template("gpu") is not None
        assert config.domains.local_suffix == "deggio.local"
        assert config.app.log_level == "DEBUG"

    def test_missing_file_raises(self) -> None:
        with pytest.raises(ConfigError, match="not found"):
            load_config("/nonexistent/path/config.yaml")

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        config_file = tmp_path / "bad.yaml"
        config_file.write_text("{{ invalid yaml }}")
        with pytest.raises(ConfigError):
            load_config(config_file)

    def test_missing_required_fields(self, tmp_path: Path) -> None:
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("app:\n  log_level: DEBUG\n")
        with pytest.raises(ConfigError, match="validation failed"):
            load_config(config_file)


class TestEnvVarInterpolation:
    """Tests for ${VAR} substitution in config values."""

    def test_env_vars_interpolated(self, tmp_path: Path) -> None:
        os.environ["TEST_TOKEN_ID"] = "real@pam!real-token"
        os.environ["TEST_TOKEN_SECRET"] = "real-secret-123"
        os.environ["TEST_PIHOLE_PW"] = "pihole-pw"
        try:
            config_file = tmp_path / "config.yaml"
            config_file.write_text(ENV_VAR_CONFIG)
            config = load_config(config_file)
            assert config.proxmox.token_id == "real@pam!real-token"
            assert config.proxmox.token_secret == "real-secret-123"
            assert config.pihole.password == "pihole-pw"
        finally:
            del os.environ["TEST_TOKEN_ID"]
            del os.environ["TEST_TOKEN_SECRET"]
            del os.environ["TEST_PIHOLE_PW"]

    def test_unset_env_var_preserved(self, tmp_path: Path) -> None:
        """Unset env vars should remain as placeholder strings."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(ENV_VAR_CONFIG)
        # Make sure the vars aren't set
        for var in ("TEST_TOKEN_ID", "TEST_TOKEN_SECRET", "TEST_PIHOLE_PW"):
            os.environ.pop(var, None)
        config = load_config(config_file)
        assert config.proxmox.token_id == "${TEST_TOKEN_ID}"


class TestConfigDefaults:
    """Tests for default values."""

    def test_network_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(MINIMAL_CONFIG)
        config = load_config(config_file)
        assert config.network.bridge == "vmbr0"
        assert config.network.cidr == 24
        assert config.app.log_level == "INFO"

    def test_log_level_normalised(self, tmp_path: Path) -> None:
        config_text = MINIMAL_CONFIG + "\napp:\n  log_level: debug\n"
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_text)
        config = load_config(config_file)
        assert config.app.log_level == "DEBUG"
