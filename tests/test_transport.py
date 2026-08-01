"""Tests for server transport settings and HTTP streaming support."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from proxmox_mcp_server.config import AppConfig, AppSettings
from proxmox_mcp_server.server import build_server, parse_args


def test_app_settings_default_transport() -> None:
    """Default transport is stdio on 127.0.0.1:8000."""
    settings = AppSettings()
    assert settings.transport == "stdio"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000


def test_app_settings_valid_transports() -> None:
    """Validates transport choices: stdio, http, sse, streamable-http."""
    for trans in ("stdio", "http", "sse", "streamable-http"):
        settings = AppSettings(transport=trans)
        assert settings.transport == trans


def test_app_settings_invalid_transport() -> None:
    """Invalid transport choice raises ValidationError."""
    with pytest.raises(ValidationError):
        AppSettings(transport="grpc")


def test_parse_args_defaults() -> None:
    """CLI arguments default to None so config values take precedence."""
    with patch.object(sys, "argv", ["proxmox-mcp-server"]):
        args = parse_args()
        assert args.transport is None
        assert args.host is None
        assert args.port is None
        assert args.config is None


def test_parse_args_custom_transport() -> None:
    """CLI arguments override transport, host, port, and config path."""
    with patch.object(
        sys,
        "argv",
        [
            "proxmox-mcp-server",
            "--transport",
            "streamable-http",
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--config",
            "/path/to/config.yaml",
        ],
    ):
        args = parse_args()
        assert args.transport == "streamable-http"
        assert args.host == "0.0.0.0"
        assert args.port == 9000
        assert args.config == "/path/to/config.yaml"


def test_build_server_supports_http_app() -> None:
    """build_server creates a FastMCP instance capable of returning an ASGI HTTP app."""
    config = AppConfig.model_validate({
        "proxmox": {
            "host": "test.local",
            "token_id": "user@pve!token",
            "token_secret": "secret",
        },
        "pihole": {"url": "http://pihole.local"},
        "npm": {"url": "http://npm.local"},
        "app": {"transport": "streamable-http", "host": "0.0.0.0", "port": 8080},
    })
    mcp = build_server(config)
    assert mcp.name == "proxmox-mcp-server"

    # FastMCP exposes .http_app() for ASGI servers (Uvicorn, Starlette, etc.)
    app = mcp.http_app()
    assert app is not None
