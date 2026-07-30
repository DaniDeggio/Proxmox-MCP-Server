"""Shared test fixtures and mock providers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from deggio_infra_mcp.config import (
    AgyConfig,
    AppConfig,
    AppSettings,
    DomainsConfig,
    NetworkConfig,
    NpmConfig,
    PiHoleConfig,
    ProxmoxConfig,
    SshConfig,
    TemplatesConfig,
)
from deggio_infra_mcp.models.service import CommandResult
from deggio_infra_mcp.models.templates import TemplateInfo
from deggio_infra_mcp.providers import (
    BaseAgyProvider,
    BaseNpmProvider,
    BasePiHoleProvider,
    BaseProxmoxProvider,
)
from deggio_infra_mcp.services.ipam import IpamService
from deggio_infra_mcp.services.provisioning import ProvisioningService

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Mock providers
# ---------------------------------------------------------------------------


class MockProxmoxProvider(BaseProxmoxProvider):
    """In-memory mock for Proxmox operations."""

    def __init__(self) -> None:
        self.containers: dict[int, dict[str, Any]] = {}
        self._next_vmid = 200

    async def clone_container(
        self, source_vmid: int, new_vmid: int, hostname: str, **kwargs: Any
    ) -> dict[str, Any]:
        self.containers[new_vmid] = {
            "vmid": new_vmid,
            "hostname": hostname,
            "status": "stopped",
            "source": source_vmid,
        }
        return {"vmid": new_vmid, "hostname": hostname, "status": "cloned"}

    async def configure_container(self, vmid: int, **kwargs: Any) -> dict[str, Any]:
        if vmid in self.containers:
            self.containers[vmid].update(kwargs)
        return {"vmid": vmid, "configured": True, "params": kwargs}

    async def start_container(self, vmid: int, **kwargs: Any) -> dict[str, Any]:
        if vmid in self.containers:
            self.containers[vmid]["status"] = "running"
        return {"vmid": vmid, "status": "started"}

    async def stop_container(self, vmid: int, **kwargs: Any) -> dict[str, Any]:
        if vmid in self.containers:
            self.containers[vmid]["status"] = "stopped"
        return {"vmid": vmid, "status": "stopped"}

    async def get_container_status(self, vmid: int, **kwargs: Any) -> dict[str, Any]:
        ct = self.containers.get(vmid, {})
        return {"status": ct.get("status", "unknown"), "vmid": vmid}

    async def execute_command(
        self, vmid: int, command: str, **kwargs: Any
    ) -> CommandResult:
        return CommandResult(exit_code=0, stdout="OK", stderr="", duration_seconds=1.0)

    async def get_next_vmid(self) -> int:
        vmid = self._next_vmid
        self._next_vmid += 1
        return vmid


class MockPiHoleProvider(BasePiHoleProvider):
    """In-memory mock for Pi-hole DNS."""

    def __init__(self) -> None:
        self.records: list[dict[str, str]] = []

    async def add_dns_record(self, domain: str, target_ip: str) -> dict[str, Any]:
        if await self.record_exists(domain, target_ip):
            return {"domain": domain, "ip": target_ip, "action": "already_exists"}
        self.records.append({"domain": domain, "ip": target_ip})
        return {"domain": domain, "ip": target_ip, "action": "created"}

    async def delete_dns_record(self, domain: str, target_ip: str) -> dict[str, Any]:
        self.records = [
            r for r in self.records
            if not (r["domain"] == domain and r["ip"] == target_ip)
        ]
        return {"domain": domain, "ip": target_ip, "action": "deleted"}

    async def get_dns_records(self) -> list[dict[str, str]]:
        return list(self.records)

    async def record_exists(self, domain: str, target_ip: str) -> bool:
        return any(
            r["domain"] == domain and r["ip"] == target_ip for r in self.records
        )


class MockNpmProvider(BaseNpmProvider):
    """In-memory mock for Nginx Proxy Manager."""

    def __init__(self) -> None:
        self.hosts: list[dict[str, Any]] = []
        self._next_id = 1

    async def create_proxy_host(
        self, domain: str, forward_host: str, forward_port: int, **kwargs: Any
    ) -> dict[str, Any]:
        existing = await self.find_proxy_host_by_domain(domain)
        if existing:
            return {**existing, "action": "already_exists"}
        host = {
            "id": self._next_id,
            "domain_names": [domain],
            "forward_host": forward_host,
            "forward_port": forward_port,
            "forward_scheme": kwargs.get("forward_scheme", "http"),
            "action": "created",
        }
        self.hosts.append(host)
        self._next_id += 1
        return host

    async def get_proxy_hosts(self) -> list[dict[str, Any]]:
        return list(self.hosts)

    async def find_proxy_host_by_domain(self, domain: str) -> dict[str, Any] | None:
        for host in self.hosts:
            if domain in host.get("domain_names", []):
                return host
        return None

    async def delete_proxy_host(self, host_id: int) -> None:
        self.hosts = [h for h in self.hosts if h.get("id") != host_id]


class MockAgyProvider(BaseAgyProvider):
    """In-memory mock for Agy."""

    async def run_bootstrap(
        self, vmid: int, prompt: str, **kwargs: Any
    ) -> CommandResult:
        return CommandResult(
            exit_code=0,
            stdout="Bootstrap completed successfully",
            stderr="",
            duration_seconds=5.0,
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_state_dir(tmp_path: Path) -> Path:
    """Create a temporary state directory."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    return state_dir


@pytest.fixture
def test_network_config(tmp_state_dir: Path) -> NetworkConfig:
    """Network config pointing at the temp state dir."""
    return NetworkConfig(
        bridge="vmbr0",
        gateway="192.168.1.1",
        cidr=24,
        ip_range_start="192.168.1.200",
        ip_range_end="192.168.1.210",
        nameserver="192.168.1.53",
        state_file=str(tmp_state_dir / "ip_reservations.json"),
    )


@pytest.fixture
def test_templates_config() -> TemplatesConfig:
    return TemplatesConfig(
        templates={
            "base": TemplateInfo(
                key="base",
                source_vmid=9000,
                description="Base template",
                tags=["base"],
                default_cores=2,
                default_memory_mb=2048,
                default_disk_gb=20,
                storage="local-lvm",
            ),
            "gpu": TemplateInfo(
                key="gpu",
                source_vmid=9001,
                description="GPU template",
                tags=["gpu"],
                default_cores=4,
                default_memory_mb=8192,
                default_disk_gb=50,
                storage="local-lvm",
            ),
        }
    )


@pytest.fixture
def test_config(
    test_network_config: NetworkConfig,
    test_templates_config: TemplatesConfig,
    tmp_state_dir: Path,
) -> AppConfig:
    """Full test config with all sections populated."""
    return AppConfig(
        proxmox=ProxmoxConfig(
            host="192.168.1.100",
            port=8006,
            node="pve",
            token_id="test@pam!test-token",
            token_secret="fake-secret",
            ssh=SshConfig(host="192.168.1.100"),
        ),
        templates=test_templates_config,
        network=test_network_config,
        pihole=PiHoleConfig(url="http://192.168.1.53", password="test"),
        npm=NpmConfig(url="http://192.168.1.80:81", username="admin@test.com", password="test"),
        domains=DomainsConfig(local_suffix="deggio.local"),
        agy=AgyConfig(command="agy"),
        app=AppSettings(log_level="DEBUG", state_dir=str(tmp_state_dir)),
    )


@pytest.fixture
def mock_proxmox() -> MockProxmoxProvider:
    return MockProxmoxProvider()


@pytest.fixture
def mock_pihole() -> MockPiHoleProvider:
    return MockPiHoleProvider()


@pytest.fixture
def mock_npm() -> MockNpmProvider:
    return MockNpmProvider()


@pytest.fixture
def mock_agy() -> MockAgyProvider:
    return MockAgyProvider()


@pytest.fixture
def ipam_service(test_network_config: NetworkConfig) -> IpamService:
    return IpamService(test_network_config)


@pytest.fixture
def provisioning_service(
    test_config: AppConfig,
    mock_proxmox: MockProxmoxProvider,
    mock_pihole: MockPiHoleProvider,
    mock_npm: MockNpmProvider,
    mock_agy: MockAgyProvider,
    ipam_service: IpamService,
) -> ProvisioningService:
    return ProvisioningService(
        config=test_config,
        proxmox=mock_proxmox,
        pihole=mock_pihole,
        npm=mock_npm,
        agy=mock_agy,
        ipam=ipam_service,
    )
