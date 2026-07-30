"""Network utility helpers."""

from __future__ import annotations

import asyncio
import socket

from deggio_infra_mcp.logging import get_logger

log = get_logger("utils.network")


async def wait_for_port(
    host: str,
    port: int = 22,
    timeout_seconds: float = 300,
    poll_interval: float = 5.0,
) -> bool:
    """Wait until a TCP port is reachable on *host*.

    Args:
        host: Target hostname or IP.
        port: TCP port to probe (default 22 for SSH).
        timeout_seconds: Total wait time before giving up.
        poll_interval: Seconds between probe attempts.

    Returns:
        ``True`` if the port became reachable, ``False`` on timeout.
    """
    deadline = asyncio.get_event_loop().time() + timeout_seconds

    while asyncio.get_event_loop().time() < deadline:
        if _tcp_probe(host, port, connect_timeout=3.0):
            log.info("port_reachable", host=host, port=port)
            return True
        await asyncio.sleep(poll_interval)

    log.warning("port_timeout", host=host, port=port, timeout=timeout_seconds)
    return False


def _tcp_probe(host: str, port: int, connect_timeout: float = 3.0) -> bool:
    """Return ``True`` if we can open a TCP connection."""
    try:
        with socket.create_connection((host, port), timeout=connect_timeout):
            return True
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False
