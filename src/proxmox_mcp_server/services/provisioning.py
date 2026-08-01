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

from proxmox_mcp_server.logging import get_logger
from proxmox_mcp_server.models.errors import ServiceProvisioningError
from proxmox_mcp_server.models.service import (
    ServiceRequest,
    ServiceResult,
    StepResult,
    StepStatus,
)
from proxmox_mcp_server.services.prompt_generator import generate_agy_prompt
from proxmox_mcp_server.utils.network import wait_for_port

if TYPE_CHECKING:
    from proxmox_mcp_server.config import AppConfig
    from proxmox_mcp_server.models.templates import TemplateInfo
    from proxmox_mcp_server.providers import (
        BaseAgentProvider,
        BaseNpmProvider,
        BasePiHoleProvider,
        BaseProxmoxProvider,
    )
    from proxmox_mcp_server.services.ipam import IpamService

log = get_logger("services.provisioning")


class ProvisioningService:
    """Orchestrates full service provisioning on Proxmox LXC containers."""

    def __init__(
        self,
        config: AppConfig,
        proxmox: BaseProxmoxProvider,
        pihole: BasePiHoleProvider,
        npm: BaseNpmProvider,
        agy: BaseAgentProvider,
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

    # ------------------------------------------------------------------
    # Snapshot management delegates
    # ------------------------------------------------------------------

    async def create_lxc_snapshot(
        self,
        vmid: int,
        name: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Create a snapshot of an LXC container."""
        return await self._proxmox.create_snapshot(vmid, name, description=description)

    async def list_lxc_snapshots(self, vmid: int) -> list[dict[str, Any]]:
        """List all snapshots of an LXC container."""
        return await self._proxmox.list_snapshots(vmid)

    async def rollback_lxc_snapshot(
        self,
        vmid: int,
        name: str,
        stop_if_running: bool = True,
    ) -> dict[str, Any]:
        """Rollback an LXC container to a named snapshot.

        If ``stop_if_running`` is True and the container is running, it will
        be stopped before the rollback and NOT restarted automatically.
        If ``stop_if_running`` is False and the container is running, raises
        an error to prevent accidental data loss.
        """
        from proxmox_mcp_server.models.errors import SnapshotError

        status = await self._proxmox.get_container_status(vmid)
        was_running = status.get("status") == "running"

        if was_running:
            if not stop_if_running:
                raise SnapshotError(
                    f"Container VMID {vmid} is running. "
                    "Set stop_if_running=True to stop it automatically before rollback.",
                    vmid=vmid,
                    snapshot_name=name,
                )
            await self._proxmox.stop_container(vmid)

        result = await self._proxmox.rollback_snapshot(vmid, name)
        result["was_running"] = was_running
        return result

    # ------------------------------------------------------------------
    # Command execution & diagnostics delegates
    # ------------------------------------------------------------------

    async def exec_lxc_command(
        self,
        vmid: int,
        command: str,
        timeout: int = 60,
    ) -> dict[str, Any]:
        """Execute a command inside a running LXC container via SSH."""
        result = await self._proxmox.execute_command(vmid, command, timeout=timeout)
        return {
            "vmid": vmid,
            "command": command,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_seconds": result.duration_seconds,
        }

    async def get_lxc_service_logs(
        self,
        vmid: int,
        service_name: str,
        lines: int = 50,
    ) -> dict[str, Any]:
        """Read systemd journal logs for a service running inside a container."""
        command = f"journalctl -u {service_name} -n {lines} --no-pager 2>&1"
        result = await self._proxmox.execute_command(vmid, command, timeout=30)
        return {
            "vmid": vmid,
            "service_name": service_name,
            "logs": result.stdout or result.stderr,
            "exit_code": result.exit_code,
        }

    # ------------------------------------------------------------------
    # Infrastructure inspection delegates
    # ------------------------------------------------------------------

    async def list_containers(self) -> list[dict[str, Any]]:
        """List all LXC containers on the configured Proxmox node."""
        return await self._proxmox.list_containers()

    async def get_storage_status(self, storage: str = "local-lvm") -> dict[str, Any]:
        """Return usage statistics for a Proxmox storage pool."""
        return await self._proxmox.get_storage_status(storage)

    # ------------------------------------------------------------------
    # Resource management delegates
    # ------------------------------------------------------------------

    async def resize_lxc_disk(
        self,
        vmid: int,
        size_gb: int,
        disk: str = "rootfs",
    ) -> dict[str, Any]:
        """Grow an LXC container disk to the specified size in GB.

        Raises ValueError if size_gb is not a positive integer.
        Note: Proxmox does not allow shrinking disks.
        """
        if size_gb <= 0:
            raise ValueError(f"size_gb must be a positive integer, got {size_gb}")
        return await self._proxmox.resize_disk(vmid, size_gb, disk=disk)

    async def update_lxc_resources(
        self,
        vmid: int,
        cores: int | None = None,
        memory_mb: int | None = None,
        swap_mb: int | None = None,
    ) -> dict[str, Any]:
        """Update CPU, memory, and swap resources for an LXC container.

        Changes take effect immediately without requiring a container restart
        (Proxmox supports hot-plug for CPU and memory on LXC).
        """
        params: dict[str, Any] = {}
        if cores is not None:
            params["cores"] = cores
        if memory_mb is not None:
            params["memory_mb"] = memory_mb
        if swap_mb is not None:
            params["swap_mb"] = swap_mb

        if not params:
            return {"vmid": vmid, "updated_params": {}, "action": "no_change"}

        result = await self._proxmox.configure_container(
            vmid,
            cores=cores,
            memory_mb=memory_mb,
        )
        return {
            "vmid": vmid,
            "updated_params": params,
            "action": "updated",
            "configured": result.get("configured", True),
        }

    # ------------------------------------------------------------------
    # Task tracking delegates
    # ------------------------------------------------------------------

    async def get_task_status(self, upid: str) -> dict[str, Any]:
        """Return the current status of a Proxmox task by UPID."""
        return await self._proxmox.get_task_status(upid)

    async def get_task_log(self, upid: str, limit: int = 50) -> list[dict[str, Any]]:
        """Return log lines for a Proxmox task by UPID."""
        return await self._proxmox.get_task_log(upid, limit=limit)

    # ------------------------------------------------------------------
    # Brownfield adoption
    # ------------------------------------------------------------------

    async def import_existing_lxc(
        self,
        vmid: int,
        service_name: str,
        register_dns: bool = True,
        register_proxy: bool = False,
        forward_port: int = 80,
        forward_scheme: str = "http",
    ) -> dict[str, Any]:
        """Adopt an existing LXC container into this MCP server's management.

        Steps:
        1. Verify the container exists and is running on Proxmox.
        2. Extract its current IP from Proxmox config.
        3. Register the IP in the local IPAM (with out_of_range flag if applicable).
        4. Optionally add a Pi-hole DNS record.
        5. Optionally create an NPM proxy host.
        """
        hostname = service_name.lower().replace(" ", "-").replace("_", "-")
        domain = f"{hostname}.{self._config.domains.local_suffix}"

        # Step 1: Verify container exists
        status = await self._proxmox.get_container_status(vmid)
        container_status = status.get("status", "unknown")

        # Step 2: Extract current IP from Proxmox
        ip = _extract_ip_from_status(status)
        if not ip:
            # Try reading raw config
            return {
                "vmid": vmid,
                "error": (
                    f"Could not determine IP for container {vmid}. "
                    "Ensure the container is configured with a static IP."
                ),
                "success": False,
            }

        # Step 3: Register in IPAM (idempotent)
        net = self._config.network
        import ipaddress as _ipaddress
        range_start = _ipaddress.IPv4Address(net.ip_range_start)
        range_end = _ipaddress.IPv4Address(net.ip_range_end)
        addr = _ipaddress.IPv4Address(ip)
        out_of_range = not (range_start <= addr <= range_end)

        existing_ip = self._ipam.find_ip_by_vmid(vmid) or self._ipam.find_ip_by_hostname(hostname)
        if existing_ip:
            registered_in_ipam = "already_registered"
        else:
            try:
                if out_of_range:
                    # Direct-write reservation bypassing range check
                    from proxmox_mcp_server.services.ipam import IpReservation
                    reservations = self._ipam._get_reservations()
                    reservations.append(IpReservation(ip=ip, hostname=hostname, vmid=vmid))
                    self._ipam._save_reservations(reservations)
                    registered_in_ipam = "registered_out_of_range"
                else:
                    self._ipam.allocate_ip(hostname, vmid=vmid)
                    registered_in_ipam = "registered"
            except Exception:
                registered_in_ipam = "registration_failed"

        result: dict[str, Any] = {
            "vmid": vmid,
            "hostname": hostname,
            "domain": domain,
            "ip": ip,
            "container_status": container_status,
            "registered_in_ipam": registered_in_ipam,
            "out_of_range": out_of_range,
            "dns_action": "skipped",
            "proxy_action": "skipped",
            "success": True,
        }

        # Step 4: DNS
        if register_dns:
            try:
                dns_result = await self._pihole.add_dns_record(domain, ip)
                result["dns_action"] = dns_result.get("action", "done")
            except Exception as exc:
                result["dns_action"] = f"failed: {exc}"

        # Step 5: Proxy
        if register_proxy:
            try:
                proxy_result = await self._npm.create_proxy_host(
                    domain=domain,
                    forward_host=ip,
                    forward_port=forward_port,
                    forward_scheme=forward_scheme,
                )
                result["proxy_action"] = proxy_result.get("action", "done")
            except Exception as exc:
                result["proxy_action"] = f"failed: {exc}"

        return result


    # ------------------------------------------------------------------
    # Host administration delegates
    # ------------------------------------------------------------------

    async def exec_host_command(
        self,
        command: str,
        timeout: int = 60,
    ) -> dict[str, Any]:
        """Execute a command directly on the Proxmox host."""
        result = await self._proxmox.execute_host_command(command, timeout=timeout)
        return {
            "command": command,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_seconds": result.duration_seconds,
        }

    async def run_host_agy(
        self,
        prompt: str,
        working_dir: str | None = None,
        timeout: int = 600,
    ) -> dict[str, Any]:
        """Run an Agy session directly on the Proxmox host."""
        result = await self._agy.run_on_host(
            prompt=prompt,
            working_dir=working_dir,
        )
        return {
            "action": "run_host_agy",
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_seconds": result.duration_seconds,
        }



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
