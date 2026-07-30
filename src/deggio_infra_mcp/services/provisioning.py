"""Provisioning service — the orchestration engine.

Implements the ``create_service`` flow that sequences all steps from
template selection through Agy bootstrap.  Each step is tracked via
``StepResult`` objects so partial failures are fully inspectable.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

import structlog

from deggio_infra_mcp.logging import get_logger
from deggio_infra_mcp.models.errors import ServiceProvisioningError
from deggio_infra_mcp.models.service import (
    ServiceRequest,
    ServiceResult,
    StepResult,
    StepStatus,
)
from deggio_infra_mcp.services.prompt_generator import generate_agy_prompt
from deggio_infra_mcp.utils.network import wait_for_port

if TYPE_CHECKING:
    from deggio_infra_mcp.config import AppConfig
    from deggio_infra_mcp.models.templates import TemplateInfo
    from deggio_infra_mcp.providers import (
        BaseAgyProvider,
        BaseNpmProvider,
        BasePiHoleProvider,
        BaseProxmoxProvider,
    )
    from deggio_infra_mcp.services.ipam import IpamService

log = get_logger("services.provisioning")


class ProvisioningService:
    """Orchestrates full service provisioning on Proxmox LXC containers."""

    def __init__(
        self,
        config: AppConfig,
        proxmox: BaseProxmoxProvider,
        pihole: BasePiHoleProvider,
        npm: BaseNpmProvider,
        agy: BaseAgyProvider,
        ipam: IpamService,
    ) -> None:
        self._config = config
        self._proxmox = proxmox
        self._pihole = pihole
        self._npm = npm
        self._agy = agy
        self._ipam = ipam

    # ------------------------------------------------------------------
    # Template helpers
    # ------------------------------------------------------------------

    def list_templates(self) -> list[TemplateInfo]:
        """Return all configured templates."""
        return self._config.list_templates()

    def get_template(self, key: str) -> TemplateInfo | None:
        """Look up a template by key."""
        return self._config.get_template(key)

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    async def create_service(self, request: ServiceRequest) -> ServiceResult:
        """Execute the full service provisioning flow.

        Steps:
        1. Validate input & select template
        2. Allocate IP
        3. Clone LXC from template
        4. Configure hostname + network
        5. Start container
        6. Wait for container readiness
        7. Add Pi-hole DNS record
        8. Create NPM proxy host
        9. Generate Agy prompt
        10. Run Agy bootstrap

        Each step is tracked independently.  If a step fails, the result
        preserves all completed steps and the failure point.
        """
        correlation_id = str(uuid.uuid4())[:12]
        bound_log = log.bind(
            correlation_id=correlation_id,
            service_name=request.service_name,
        )

        # Also bind to structlog contextvars for downstream loggers
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        result = ServiceResult(
            correlation_id=correlation_id,
            started_at=datetime.now(),
        )

        hostname = request.service_name.lower().replace(" ", "-").replace("_", "-")
        domain = f"{hostname}.{self._config.domains.local_suffix}"
        result.hostname = hostname
        result.domain = domain
        result.template_key = request.template_key

        bound_log.info("provisioning_started", domain=domain)

        try:
            # Step 1: Validate + select template
            step = StepResult(name="validate_template")
            result.steps.append(step)
            step.mark_running()
            template = self._validate_and_select_template(request.template_key)
            result.template_key = template.key
            step.mark_completed(
                f"Template '{template.key}' selected (VMID {template.source_vmid})",
                data={"source_vmid": template.source_vmid},
            )

            # Step 2: Allocate IP
            step = StepResult(name="allocate_ip")
            result.steps.append(step)
            step.mark_running()
            ip = self._ipam.allocate_ip(hostname, vmid=request.vmid)
            result.ip = ip
            step.mark_completed(f"Allocated IP {ip}", data={"ip": ip})

            # Step 3: Determine VMID and clone
            step = StepResult(name="clone_container")
            result.steps.append(step)
            step.mark_running()
            vmid = request.vmid or await self._proxmox.get_next_vmid()
            result.vmid = vmid

            await self._proxmox.clone_container(
                source_vmid=template.source_vmid,
                new_vmid=vmid,
                hostname=hostname,
                storage=template.storage,
            )
            step.mark_completed(
                f"Cloned template {template.source_vmid} → VMID {vmid}",
                data={"vmid": vmid},
            )

            # Step 4: Configure network
            step = StepResult(name="configure_container")
            result.steps.append(step)
            step.mark_running()
            net = self._config.network
            # Merge template tags with request tags
            all_tags = list(template.tags) + list(request.tags)
            await self._proxmox.configure_container(
                vmid,
                hostname=hostname,
                ip=ip,
                cidr=net.cidr,
                gateway=net.gateway,
                nameserver=net.nameserver,
                bridge=net.bridge,
                cores=template.default_cores,
                memory_mb=template.default_memory_mb,
                tags=all_tags or None,
            )
            step.mark_completed(
                f"Configured VMID {vmid}: {ip}/{net.cidr}, gw {net.gateway}"
            )

            # Step 5: Start container
            step = StepResult(name="start_container")
            result.steps.append(step)
            step.mark_running()
            await self._proxmox.start_container(vmid)
            step.mark_completed(f"Started VMID {vmid}")

            # Step 6: Wait for readiness
            step = StepResult(name="wait_for_container")
            result.steps.append(step)
            step.mark_running()
            reachable = await wait_for_port(ip, port=22, timeout_seconds=300)
            if not reachable:
                step.mark_failed(f"Container {vmid} ({ip}) not reachable after 300s")
                raise ServiceProvisioningError(
                    f"Container VMID {vmid} not reachable on SSH after 300s",
                    failed_step="wait_for_container",
                    completed_steps=result.completed_steps,
                )
            step.mark_completed(f"Container {vmid} reachable at {ip}:22")

            # Step 7: Pi-hole DNS
            if not request.skip_dns:
                step = StepResult(name="add_dns_record")
                result.steps.append(step)
                step.mark_running()
                dns_result = await self._pihole.add_dns_record(domain, ip)
                step.mark_completed(
                    f"DNS: {domain} → {ip} ({dns_result.get('action', 'done')})",
                    data=dns_result,
                )

            # Step 8: NPM proxy host
            if not request.skip_proxy:
                step = StepResult(name="create_npm_proxy_host")
                result.steps.append(step)
                step.mark_running()
                proxy_result = await self._npm.create_proxy_host(
                    domain=domain,
                    forward_host=ip,
                    forward_port=request.forward_port,
                    forward_scheme=request.forward_scheme,
                )
                proxy_target = f"{request.forward_scheme}://{ip}:{request.forward_port}"
                result.proxy_target = proxy_target
                step.mark_completed(
                    f"Proxy: {domain} → {proxy_target} ({proxy_result.get('action', 'done')})",
                    data=proxy_result,
                )

            # Step 9–10: Agy bootstrap
            if not request.skip_agy:
                # Generate prompt
                step = StepResult(name="generate_agy_prompt")
                result.steps.append(step)
                step.mark_running()
                prompt = generate_agy_prompt(
                    service_name=request.service_name,
                    service_type=request.service_type.value,
                    hostname=hostname,
                    ip=ip,
                    repo_urls=request.repo_urls,
                    docs_urls=request.docs_urls,
                    extra_requirements=request.extra_requirements,
                )
                step.mark_completed(
                    f"Generated Agy prompt ({len(prompt)} chars)",
                    data={"prompt_preview": prompt[:300]},
                )

                # Execute bootstrap
                step = StepResult(name="run_agy_bootstrap")
                result.steps.append(step)
                step.mark_running()
                agy_result = await self._agy.run_bootstrap(
                    vmid=vmid,
                    prompt=prompt,
                )
                step.mark_completed(
                    f"Agy bootstrap completed (exit={agy_result.exit_code}, "
                    f"{agy_result.duration_seconds}s)",
                    data={
                        "exit_code": agy_result.exit_code,
                        "duration": agy_result.duration_seconds,
                        "stdout_preview": agy_result.stdout[:500],
                    },
                )

            # All done
            result.success = True
            result.completed_at = datetime.now()
            bound_log.info(
                "provisioning_completed",
                vmid=vmid,
                ip=ip,
                domain=domain,
                steps_completed=len(result.completed_steps),
            )

        except ServiceProvisioningError:
            result.success = False
            result.completed_at = datetime.now()
            raise
        except Exception as exc:
            # Capture the failure point from the last step
            failed_steps = [
                s for s in result.steps if s.status in (StepStatus.RUNNING, StepStatus.FAILED)
            ]
            failed_step_name = failed_steps[-1].name if failed_steps else "unknown"

            # Mark any running step as failed
            for s in result.steps:
                if s.status == StepStatus.RUNNING:
                    s.mark_failed(str(exc))

            result.success = False
            result.failure_point = failed_step_name
            result.error_message = str(exc)
            result.completed_at = datetime.now()

            bound_log.error(
                "provisioning_failed",
                failed_step=failed_step_name,
                error=str(exc),
                completed_steps=result.completed_steps,
            )
            raise ServiceProvisioningError(
                f"Service provisioning failed at step '{failed_step_name}': {exc}",
                failed_step=failed_step_name,
                completed_steps=result.completed_steps,
                partial_result=result.to_summary(),
            ) from exc
        finally:
            structlog.contextvars.unbind_contextvars("correlation_id")

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_and_select_template(self, template_key: str) -> TemplateInfo:
        """Validate and return the requested template."""
        template = self.get_template(template_key)
        if template is None:
            available = [t.key for t in self.list_templates()]
            raise ServiceProvisioningError(
                f"Template '{template_key}' not found. "
                f"Available templates: {available}",
                failed_step="validate_template",
            )
        return template

    # ------------------------------------------------------------------
    # Individual operations (for standalone MCP tools)
    # ------------------------------------------------------------------

    async def allocate_ip(
        self, hostname: str, vmid: int | None = None
    ) -> dict[str, Any]:
        """Allocate an IP for standalone tool use."""
        ip = self._ipam.allocate_ip(hostname, vmid=vmid)
        return {"ip": ip, "hostname": hostname, "vmid": vmid}

    async def start_container(self, vmid: int) -> dict[str, Any]:
        """Start a container for standalone tool use."""
        return await self._proxmox.start_container(vmid)

    async def wait_for_container(
        self, vmid: int, timeout_seconds: int = 300
    ) -> dict[str, Any]:
        """Wait for a container to become reachable."""
        # Try IPAM first — it's the most reliable source
        ip = self._ipam.find_ip_by_vmid(vmid)

        # Fall back to Proxmox status
        if not ip:
            status = await self._proxmox.get_container_status(vmid)
            ip = _extract_ip_from_status(status)

        if not ip:
            return {
                "vmid": vmid,
                "reachable": False,
                "message": "Could not determine container IP from IPAM or Proxmox status",
            }

        reachable = await wait_for_port(ip, port=22, timeout_seconds=timeout_seconds)
        return {
            "vmid": vmid,
            "ip": ip,
            "reachable": reachable,
            "message": "Container is reachable" if reachable else "Timed out",
        }

    async def create_lxc_from_template(
        self,
        template_key: str,
        hostname: str,
        ip: str,
        vmid: int | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Clone a template and configure the new container."""
        template = self._validate_and_select_template(template_key)
        actual_vmid = vmid or await self._proxmox.get_next_vmid()

        await self._proxmox.clone_container(
            source_vmid=template.source_vmid,
            new_vmid=actual_vmid,
            hostname=hostname,
            storage=template.storage,
        )

        net = self._config.network
        all_tags = list(template.tags) + (tags or [])
        await self._proxmox.configure_container(
            actual_vmid,
            hostname=hostname,
            ip=ip,
            cidr=net.cidr,
            gateway=net.gateway,
            nameserver=net.nameserver,
            bridge=net.bridge,
            cores=template.default_cores,
            memory_mb=template.default_memory_mb,
            tags=all_tags or None,
        )

        return {
            "vmid": actual_vmid,
            "hostname": hostname,
            "ip": ip,
            "template_key": template_key,
            "status": "created",
        }

    # ------------------------------------------------------------------
    # Public delegates for standalone MCP tools
    # ------------------------------------------------------------------

    async def stop_container(self, vmid: int) -> dict[str, Any]:
        """Stop a container for standalone tool use."""
        return await self._proxmox.stop_container(vmid)

    async def get_container_status(self, vmid: int) -> dict[str, Any]:
        """Return the current status of a container."""
        return await self._proxmox.get_container_status(vmid)

    async def add_dns_record(self, domain: str, target_ip: str) -> dict[str, Any]:
        """Add a Pi-hole DNS record (delegate)."""
        return await self._pihole.add_dns_record(domain, target_ip)

    async def delete_dns_record(self, domain: str, target_ip: str) -> dict[str, Any]:
        """Delete a Pi-hole DNS record (delegate)."""
        return await self._pihole.delete_dns_record(domain, target_ip)

    async def get_dns_records(self) -> list[dict[str, str]]:
        """List all Pi-hole DNS records (delegate)."""
        return await self._pihole.get_dns_records()

    async def create_proxy_host(
        self,
        domain: str,
        forward_host: str,
        forward_port: int,
        forward_scheme: str = "http",
    ) -> dict[str, Any]:
        """Create an NPM proxy host (delegate)."""
        return await self._npm.create_proxy_host(
            domain=domain,
            forward_host=forward_host,
            forward_port=forward_port,
            forward_scheme=forward_scheme,
        )

    async def get_proxy_hosts(self) -> list[dict[str, Any]]:
        """List all NPM proxy hosts (delegate)."""
        return await self._npm.get_proxy_hosts()

    async def delete_proxy_host(self, host_id: int) -> None:
        """Delete an NPM proxy host by ID (delegate)."""
        await self._npm.delete_proxy_host(host_id)

    async def run_agy_bootstrap(
        self,
        vmid: int,
        prompt: str,
        working_dir: str | None = None,
    ) -> Any:
        """Run an Agy bootstrap session (delegate)."""
        return await self._agy.run_bootstrap(
            vmid=vmid,
            prompt=prompt,
            working_dir=working_dir,
        )

    def get_ip_reservations(self) -> list[dict[str, Any]]:
        """List all IPAM reservations."""
        return self._ipam.get_reservations()

    def release_ip(self, ip: str) -> bool:
        """Release an IPAM reservation."""
        return self._ipam.release_ip(ip)


def _extract_ip_from_status(status: dict[str, Any]) -> str | None:
    """Best-effort IP extraction from a Proxmox container status dict."""
    # Proxmox may return network info in different formats
    # Try common patterns
    for key in ("ip", "net0"):
        val = status.get(key, "")
        if isinstance(val, str) and "." in val:
            # Extract IP from strings like "ip=192.168.1.200/24,gw=..."
            for part in val.split(","):
                if "=" in part:
                    _, v = part.split("=", 1)
                    if "/" in v:
                        v = v.split("/")[0]
                    if _is_ipv4(v):
                        return v
                elif _is_ipv4(part):
                    return part
    return None


def _is_ipv4(s: str) -> bool:
    """Quick check if a string looks like an IPv4 address."""
    parts = s.strip().split(".")
    if len(parts) != 4:
        return False
    return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)
