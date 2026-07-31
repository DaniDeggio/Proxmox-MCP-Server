"""IPAM — IP Address Management service.

Manages a configured IP range using a local JSON state file for
reservations.  Designed for single-server homelab use where a
full-blown DHCP/IPAM system would be overkill.

Thread/process safety is handled via file locking on write.
"""

from __future__ import annotations

import fcntl
import ipaddress
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from proxmox_mcp_server.logging import get_logger
from proxmox_mcp_server.models.errors import IpAllocationError

if TYPE_CHECKING:
    from proxmox_mcp_server.config import NetworkConfig

log = get_logger("services.ipam")


class IpReservation:
    """A single IP reservation record."""

    def __init__(
        self,
        ip: str,
        hostname: str,
        vmid: int | None = None,
        allocated_at: str | None = None,
    ) -> None:
        self.ip = ip
        self.hostname = hostname
        self.vmid = vmid
        self.allocated_at = allocated_at or datetime.now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ip": self.ip,
            "hostname": self.hostname,
            "vmid": self.vmid,
            "allocated_at": self.allocated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IpReservation:
        return cls(
            ip=data["ip"],
            hostname=data.get("hostname", ""),
            vmid=data.get("vmid"),
            allocated_at=data.get("allocated_at"),
        )


class IpamService:
    """Simple file-backed IPAM for a contiguous IP range."""

    def __init__(self, config: NetworkConfig) -> None:
        self._config = config
        self._state_file = Path(config.state_file)
        self._range_start = ipaddress.IPv4Address(config.ip_range_start)
        self._range_end = ipaddress.IPv4Address(config.ip_range_end)

        # Ensure the state file directory exists
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

        # Create the state file if it doesn't exist
        if not self._state_file.exists():
            self._write_state({"reservations": []})

    # ------------------------------------------------------------------
    # State I/O
    # ------------------------------------------------------------------

    def _read_state(self) -> dict[str, Any]:
        """Read the reservations state file."""
        try:
            text = self._state_file.read_text(encoding="utf-8")
            data = json.loads(text)
            if not isinstance(data, dict):
                return {"reservations": []}
            return data
        except (json.JSONDecodeError, FileNotFoundError):
            return {"reservations": []}

    def _write_state(self, state: dict[str, Any]) -> None:
        """Write the state file atomically with file locking."""
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._state_file.with_suffix(".tmp")
        content = json.dumps(state, indent=2)
        with open(tmp_path, "w", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(content)
            f.flush()
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        tmp_path.replace(self._state_file)

    def _get_reservations(self) -> list[IpReservation]:
        state = self._read_state()
        return [
            IpReservation.from_dict(r) for r in state.get("reservations", [])
        ]

    def _save_reservations(self, reservations: list[IpReservation]) -> None:
        self._write_state({"reservations": [r.to_dict() for r in reservations]})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_reservations(self) -> list[dict[str, Any]]:
        """Return all current reservations as dicts."""
        return [r.to_dict() for r in self._get_reservations()]

    def is_ip_available(self, ip: str) -> bool:
        """Check whether an IP is within range and not reserved."""
        addr = ipaddress.IPv4Address(ip)
        if addr < self._range_start or addr > self._range_end:
            return False
        reserved_ips = {r.ip for r in self._get_reservations()}
        return ip not in reserved_ips

    def find_ip_by_vmid(self, vmid: int) -> str | None:
        """Look up the IP reserved for a given VMID, or ``None``."""
        for r in self._get_reservations():
            if r.vmid == vmid:
                return r.ip
        return None

    def find_ip_by_hostname(self, hostname: str) -> str | None:
        """Look up the IP reserved for a given hostname, or ``None``."""
        for r in self._get_reservations():
            if r.hostname == hostname:
                return r.ip
        return None

    def allocate_ip(
        self,
        hostname: str,
        vmid: int | None = None,
        preferred_ip: str | None = None,
    ) -> str:
        """Allocate the next free IP from the configured range.

        Args:
            hostname: The hostname this IP is for (tracking only).
            vmid: Optional VMID to associate.
            preferred_ip: Request a specific IP if available.

        Returns:
            The allocated IP address string.

        Raises:
            IpAllocationError: If the range is exhausted or preferred IP is taken.
        """
        reservations = self._get_reservations()
        reserved_ips = {r.ip for r in reservations}

        # Check if hostname already has an allocation
        for r in reservations:
            if r.hostname == hostname:
                log.info("ipam_already_allocated", hostname=hostname, ip=r.ip)
                return r.ip

        if preferred_ip:
            addr = ipaddress.IPv4Address(preferred_ip)
            if addr < self._range_start or addr > self._range_end:
                raise IpAllocationError(
                    f"Preferred IP {preferred_ip} is outside the configured "
                    f"range {self._range_start}–{self._range_end}"
                )
            if preferred_ip in reserved_ips:
                raise IpAllocationError(
                    f"Preferred IP {preferred_ip} is already reserved"
                )
            allocated = preferred_ip
        else:
            # Scan the range for the first free address
            allocated = None
            current = self._range_start
            while current <= self._range_end:
                if str(current) not in reserved_ips:
                    allocated = str(current)
                    break
                current = ipaddress.IPv4Address(int(current) + 1)

            if allocated is None:
                raise IpAllocationError(
                    f"IP range exhausted ({self._range_start}–{self._range_end}). "
                    f"{len(reserved_ips)} addresses reserved."
                )

        assert allocated is not None
        reservation = IpReservation(
            ip=allocated,
            hostname=hostname,
            vmid=vmid,
        )
        reservations.append(reservation)
        self._save_reservations(reservations)
        log.info("ipam_allocated", ip=allocated, hostname=hostname, vmid=vmid)
        return allocated

    def release_ip(self, ip: str) -> bool:
        """Release a previously allocated IP.

        Returns:
            ``True`` if the IP was found and released, ``False`` if not found.
        """
        reservations = self._get_reservations()
        new_reservations = [r for r in reservations if r.ip != ip]
        if len(new_reservations) == len(reservations):
            log.warning("ipam_release_not_found", ip=ip)
            return False
        self._save_reservations(new_reservations)
        log.info("ipam_released", ip=ip)
        return True
