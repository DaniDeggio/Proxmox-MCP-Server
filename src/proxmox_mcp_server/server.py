"""Proxmox MCP Server — entry point.

Wires configuration, providers, services, and MCP tools together.
Supports stdio transport (default) with the architecture structured
so HTTP/streamable transport can be added with minimal changes.
"""

from __future__ import annotations

import argparse
import sys

from fastmcp import FastMCP

from proxmox_mcp_server.config import AppConfig, load_config
from proxmox_mcp_server.logging import setup_logging
from proxmox_mcp_server.providers.agy import AgyProvider
from proxmox_mcp_server.providers.npm import NpmProvider
from proxmox_mcp_server.providers.pihole import PiHoleProvider
from proxmox_mcp_server.providers.proxmox import ProxmoxProvider
from proxmox_mcp_server.services.ipam import IpamService
from proxmox_mcp_server.services.provisioning import ProvisioningService
from proxmox_mcp_server.tools.service_tools import register_tools


def build_server(config: AppConfig | None = None) -> FastMCP:
    """Construct the fully-wired MCP server.

    This is separated from ``main()`` so tests and alternative transports
    can build the server without running the stdio loop.

    Args:
        config: Pre-loaded config.  If ``None``, loads from the default path.

    Returns:
        A configured ``FastMCP`` instance with all tools registered.
    """
    if config is None:
        config = load_config()

    # Logging
    log = setup_logging(level=config.app.log_level, fmt=config.app.log_format)
    log.info("server_starting", version="0.1.0")

    # Providers
    proxmox = ProxmoxProvider(config.proxmox)
    pihole = PiHoleProvider(config.pihole)
    npm = NpmProvider(config.npm)
    agy = AgyProvider(config.agy, proxmox=proxmox)

    # Services
    ipam = IpamService(config.network)
    provisioning = ProvisioningService(
        config=config,
        proxmox=proxmox,
        pihole=pihole,
        npm=npm,
        agy=agy,
        ipam=ipam,
    )

    # MCP server
    mcp = FastMCP(
        name="proxmox-mcp-server",
        instructions=(
            "Homelab infrastructure provisioning MCP server. "
            "Orchestrates service deployment on Proxmox LXC containers "
            "with Pi-hole DNS, Nginx Proxy Manager, and Agy bootstrap."
        ),
    )

    # Register tools
    register_tools(mcp, provisioning)

    log.info(
        "server_ready",
        templates=len(config.list_templates()),
        ip_range=f"{config.network.ip_range_start}–{config.network.ip_range_end}",
        transport=config.app.transport,
    )

    return mcp


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for server configuration and transport."""
    parser = argparse.ArgumentParser(description="Proxmox MCP Server")
    parser.add_argument(
        "--config",
        "-c",
        help="Path to configuration YAML file",
    )
    parser.add_argument(
        "--transport",
        "-t",
        choices=["stdio", "http", "sse", "streamable-http"],
        help="Transport protocol to use (default: from config or stdio)",
    )
    parser.add_argument(
        "--host",
        help="Host interface to bind HTTP/SSE server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        help="Port for HTTP/SSE server (default: 8000)",
    )
    return parser.parse_args()


def main() -> None:
    """CLI entry point — runs the MCP server over stdio or HTTP streaming."""
    args = parse_args()
    try:
        config = load_config(args.config) if args.config else load_config()
        mcp = build_server(config)

        transport = args.transport or config.app.transport or "stdio"
        host = args.host or config.app.host or "127.0.0.1"
        port = args.port or config.app.port or 8000

        if transport == "stdio":
            mcp.run(transport="stdio")
        else:
            mcp.run(transport=transport, host=host, port=port)
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        print(f"Fatal: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

