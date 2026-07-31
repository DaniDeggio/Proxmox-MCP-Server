"""Tests for the provisioning orchestration service."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from proxmox_mcp_server.models.errors import ServiceProvisioningError
from proxmox_mcp_server.models.service import ServiceRequest, ServiceType, StepStatus

if TYPE_CHECKING:
    from proxmox_mcp_server.services.provisioning import ProvisioningService
    from tests.conftest import MockProxmoxProvider


class TestCreateService:
    """Tests for the full create_service orchestration flow."""

    @pytest.mark.asyncio
    @patch("proxmox_mcp_server.services.provisioning.wait_for_port", return_value=True)
    async def test_full_flow_success(
        self, mock_wait: AsyncMock, provisioning_service: ProvisioningService
    ) -> None:
        request = ServiceRequest(
            service_name="test-app",
            service_type=ServiceType.WEB_APP,
            template_key="base",
            forward_port=8080,
        )

        result = await provisioning_service.create_service(request)

        assert result.success is True
        assert result.hostname == "test-app"
        assert result.domain == "test-app.homelab.local"
        assert result.ip == "192.168.1.200"
        assert result.vmid is not None
        assert result.template_key == "base"
        assert "validate_template" in result.completed_steps
        assert "allocate_ip" in result.completed_steps
        assert "clone_container" in result.completed_steps
        assert "start_container" in result.completed_steps

    @pytest.mark.asyncio
    @patch("proxmox_mcp_server.services.provisioning.wait_for_port", return_value=True)
    async def test_skip_optional_steps(
        self, mock_wait: AsyncMock, provisioning_service: ProvisioningService
    ) -> None:
        request = ServiceRequest(
            service_name="minimal-svc",
            skip_dns=True,
            skip_proxy=True,
            skip_agy=True,
        )

        result = await provisioning_service.create_service(request)

        assert result.success is True
        assert "add_dns_record" not in result.completed_steps
        assert "create_npm_proxy_host" not in result.completed_steps
        assert "run_agy_bootstrap" not in result.completed_steps

    @pytest.mark.asyncio
    async def test_invalid_template(
        self, provisioning_service: ProvisioningService
    ) -> None:
        request = ServiceRequest(
            service_name="bad-template",
            template_key="nonexistent",
        )

        with pytest.raises(ServiceProvisioningError, match="not found"):
            await provisioning_service.create_service(request)

    @pytest.mark.asyncio
    @patch("proxmox_mcp_server.services.provisioning.wait_for_port", return_value=False)
    async def test_container_unreachable(
        self, mock_wait: AsyncMock, provisioning_service: ProvisioningService
    ) -> None:
        request = ServiceRequest(
            service_name="unreachable-svc",
            skip_dns=True,
            skip_proxy=True,
            skip_agy=True,
        )

        with pytest.raises(ServiceProvisioningError, match="not reachable"):
            await provisioning_service.create_service(request)

    @pytest.mark.asyncio
    @patch("proxmox_mcp_server.services.provisioning.wait_for_port", return_value=True)
    async def test_step_tracking(
        self, mock_wait: AsyncMock, provisioning_service: ProvisioningService
    ) -> None:
        request = ServiceRequest(
            service_name="tracked-svc",
            skip_agy=True,
        )

        result = await provisioning_service.create_service(request)

        # All steps should be completed
        for step in result.steps:
            assert step.status == StepStatus.COMPLETED
            assert step.started_at is not None
            assert step.completed_at is not None

    @pytest.mark.asyncio
    @patch("proxmox_mcp_server.services.provisioning.wait_for_port", return_value=True)
    async def test_correlation_id_set(
        self, mock_wait: AsyncMock, provisioning_service: ProvisioningService
    ) -> None:
        request = ServiceRequest(service_name="corr-test", skip_agy=True)
        result = await provisioning_service.create_service(request)
        assert result.correlation_id
        assert len(result.correlation_id) > 0


class TestTemplateManagement:
    """Tests for template listing and lookup."""

    def test_list_templates(self, provisioning_service: ProvisioningService) -> None:
        templates = provisioning_service.list_templates()
        assert len(templates) == 2
        keys = {t.key for t in templates}
        assert "base" in keys
        assert "gpu" in keys

    def test_get_template(self, provisioning_service: ProvisioningService) -> None:
        template = provisioning_service.get_template("base")
        assert template is not None
        assert template.source_vmid == 9000

    def test_get_nonexistent_template(
        self, provisioning_service: ProvisioningService
    ) -> None:
        assert provisioning_service.get_template("nonexistent") is None


class TestIndividualOperations:
    """Tests for standalone tool operations."""

    @pytest.mark.asyncio
    async def test_allocate_ip(
        self, provisioning_service: ProvisioningService
    ) -> None:
        result = await provisioning_service.allocate_ip("standalone-host")
        assert result["ip"] == "192.168.1.200"
        assert result["hostname"] == "standalone-host"

    @pytest.mark.asyncio
    async def test_start_container(
        self, provisioning_service: ProvisioningService, mock_proxmox: MockProxmoxProvider
    ) -> None:
        mock_proxmox.containers[100] = {"vmid": 100, "status": "stopped"}
        result = await provisioning_service.start_container(100)
        assert result["status"] == "started"

    @pytest.mark.asyncio
    async def test_create_lxc_from_template(
        self, provisioning_service: ProvisioningService
    ) -> None:
        result = await provisioning_service.create_lxc_from_template(
            template_key="base",
            hostname="direct-clone",
            ip="192.168.1.205",
            vmid=150,
        )
        assert result["vmid"] == 150
        assert result["hostname"] == "direct-clone"
        assert result["status"] == "created"
