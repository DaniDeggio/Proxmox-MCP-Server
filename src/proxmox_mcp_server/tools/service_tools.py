"""MCP tool registrations — thin wrappers that connect the FastMCP
transport layer to the service layer.

Each function is registered via ``@mcp.tool`` and delegates to
``ProvisioningService`` public methods.  The tools themselves
contain no business logic — they validate MCP inputs and format outputs.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from proxmox_mcp_server.models.service import ServiceRequest, ServiceType
from proxmox_mcp_server.services.prompt_generator import (
    generate_agy_prompt,
)
from proxmox_mcp_server.services.prompt_generator import (
    generate_host_agy_prompt as _generate_host_agy_prompt,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from proxmox_mcp_server.services.provisioning import ProvisioningService


def register_tools(mcp: FastMCP, service: ProvisioningService) -> None:
    """Register all MCP tools against the given FastMCP server instance."""

    # ------------------------------------------------------------------
    # Template tools
    # ------------------------------------------------------------------

    @mcp.tool
    async def list_templates() -> str:
        """List all configured LXC templates with their descriptions and capabilities.

        Returns a JSON array of template objects including key, source VMID,
        description, tags, and default resources.
        """
        templates = service.list_templates()
        return json.dumps(
            [t.model_dump() for t in templates],
            indent=2,
        )

    # ------------------------------------------------------------------
    # IPAM tools
    # ------------------------------------------------------------------

    @mcp.tool
    async def allocate_ip(hostname: str, vmid: int | None = None) -> str:
        """Allocate the next free IP address from the configured range.

        Args:
            hostname: Hostname to associate with the IP reservation.
            vmid: Optional VMID to link to the reservation.

        Returns a JSON object with the allocated IP, hostname, and VMID.
        Idempotent: if hostname already has an allocation, returns that IP.
        """
        result = await service.allocate_ip(hostname, vmid=vmid)
        return json.dumps(result, indent=2)

    @mcp.tool
    async def list_ip_reservations() -> str:
        """List all current IP reservations from the IPAM state.

        Returns a JSON array of reservation objects with ip, hostname,
        vmid, and allocated_at.
        """
        reservations = service.get_ip_reservations()
        return json.dumps(reservations, indent=2)

    @mcp.tool
    async def release_ip(ip: str) -> str:
        """Release a previously allocated IP address.

        Args:
            ip: The IP address to release (e.g. '192.168.1.200').

        Returns a JSON object indicating whether the release succeeded.
        """
        released = service.release_ip(ip)
        return json.dumps(
            {"ip": ip, "released": released},
            indent=2,
        )

    # ------------------------------------------------------------------
    # Container lifecycle tools
    # ------------------------------------------------------------------

    @mcp.tool
    async def create_lxc_from_template(
        template_key: str,
        hostname: str,
        ip: str,
        vmid: int | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Clone an LXC template and configure the new container.

        Uses the Proxmox provider to clone the selected template,
        then applies hostname, IP, gateway, and resource settings.

        Args:
            template_key: Key of the template to clone (e.g. 'base', 'gpu').
            hostname: Hostname for the new container.
            ip: IP address to assign.
            vmid: Explicit VMID, or auto-select if None.
            tags: Optional extra tags for the container.

        Returns a JSON object with vmid, hostname, ip, template_key, and status.
        """
        result = await service.create_lxc_from_template(
            template_key=template_key,
            hostname=hostname,
            ip=ip,
            vmid=vmid,
            tags=tags,
        )
        return json.dumps(result, indent=2)

    @mcp.tool
    async def start_container(vmid: int) -> str:
        """Start an LXC container by VMID.

        Args:
            vmid: The container VMID to start.

        Returns a JSON object with vmid and status.
        """
        result = await service.start_container(vmid)
        return json.dumps(result, indent=2)

    @mcp.tool
    async def stop_container(vmid: int) -> str:
        """Stop a running LXC container by VMID.

        Args:
            vmid: The container VMID to stop.

        Returns a JSON object with vmid and status.
        """
        result = await service.stop_container(vmid)
        return json.dumps(result, indent=2)

    @mcp.tool
    async def get_container_status(vmid: int) -> str:
        """Get the current status of an LXC container.

        Returns Proxmox container status including running state,
        resource usage, and configuration details.

        Args:
            vmid: The container VMID to query.

        Returns a JSON object with the container status.
        """
        result = await service.get_container_status(vmid)
        return json.dumps(result, indent=2, default=str)

    @mcp.tool
    async def wait_for_container(vmid: int, timeout_seconds: int = 300) -> str:
        """Wait until a container is reachable via SSH (port 22).

        Polls the container's IP with TCP probes until it responds
        or the timeout is reached.  Looks up the IP from IPAM first,
        falling back to Proxmox container status.

        Args:
            vmid: The container VMID to wait for.
            timeout_seconds: Maximum seconds to wait (default 300).

        Returns a JSON object with vmid, ip, reachable status, and message.
        """
        result = await service.wait_for_container(vmid, timeout_seconds)
        return json.dumps(result, indent=2)

    # ------------------------------------------------------------------
    # Pi-hole DNS tools
    # ------------------------------------------------------------------

    @mcp.tool
    async def add_pihole_dns_record(domain: str, target_ip: str) -> str:
        """Add a local DNS A record in Pi-hole.

        Idempotent: if the exact record already exists, returns success
        without modification.

        Args:
            domain: The domain name (e.g. 'myservice.homelab.local').
            target_ip: The IP address to point the domain to.

        Returns a JSON object with domain, ip, and action taken.
        """
        result = await service.add_dns_record(domain, target_ip)
        return json.dumps(result, indent=2)

    @mcp.tool
    async def delete_pihole_dns_record(domain: str, target_ip: str) -> str:
        """Remove a local DNS A record from Pi-hole.

        Args:
            domain: The domain name to remove.
            target_ip: The IP address of the record to remove.

        Returns a JSON object with domain, ip, and action taken.
        """
        result = await service.delete_dns_record(domain, target_ip)
        return json.dumps(result, indent=2)

    @mcp.tool
    async def list_pihole_dns_records() -> str:
        """List all custom local DNS records in Pi-hole.

        Returns a JSON array of record objects with domain and ip fields.
        """
        records = await service.get_dns_records()
        return json.dumps(records, indent=2)

    # ------------------------------------------------------------------
    # Nginx Proxy Manager tools
    # ------------------------------------------------------------------

    @mcp.tool
    async def create_npm_proxy_host(
        domain: str,
        forward_host: str,
        forward_port: int,
        scheme: str = "http",
    ) -> str:
        """Create a reverse proxy host in Nginx Proxy Manager.

        Idempotent: if the host already exists with matching settings,
        returns success. If it exists but with conflicting settings,
        raises a clear error.

        Args:
            domain: The domain name for the proxy host.
            forward_host: IP or hostname to forward traffic to.
            forward_port: Port number to forward to.
            scheme: Forward scheme ('http' or 'https').

        Returns a JSON object with the proxy host details and action taken.
        """
        result = await service.create_proxy_host(
            domain=domain,
            forward_host=forward_host,
            forward_port=forward_port,
            forward_scheme=scheme,
        )
        return json.dumps(result, indent=2, default=str)

    @mcp.tool
    async def list_npm_proxy_hosts() -> str:
        """List all proxy hosts configured in Nginx Proxy Manager.

        Returns a JSON array of proxy host objects.
        """
        hosts = await service.get_proxy_hosts()
        return json.dumps(hosts, indent=2, default=str)

    @mcp.tool
    async def delete_npm_proxy_host(host_id: int) -> str:
        """Delete a proxy host from Nginx Proxy Manager by its ID.

        Args:
            host_id: The NPM proxy host ID to delete.

        Returns a JSON object confirming the deletion.
        """
        await service.delete_proxy_host(host_id)
        return json.dumps({"host_id": host_id, "action": "deleted"}, indent=2)

    # ------------------------------------------------------------------
    # Agy bootstrap tools
    # ------------------------------------------------------------------

    @mcp.tool
    async def run_agy_bootstrap(
        vmid: int,
        prompt: str,
        working_dir: str | None = None,
    ) -> str:
        """Execute an Agy bootstrap session inside a container.

        Runs the Agy agent with the given prompt inside the specified
        LXC container. Returns execution metadata including exit code,
        stdout preview, and duration.

        Args:
            vmid: The container VMID to run Agy in.
            prompt: The bootstrap prompt for Agy.
            working_dir: Working directory inside the container (default: /root).

        Returns a JSON object with exit_code, stdout preview, stderr preview,
        and duration.
        """
        result = await service.run_agy_bootstrap(
            vmid=vmid,
            prompt=prompt,
            working_dir=working_dir,
        )
        return json.dumps(result.model_dump(), indent=2)

    @mcp.tool
    async def generate_agy_prompt_tool(
        service_name: str,
        service_type: str = "web_app",
        repo_urls: list[str] | None = None,
        docs_urls: list[str] | None = None,
        extra_requirements: str = "",
    ) -> str:
        """Generate a detailed setup prompt for Agy.

        Creates a deterministic, reusable bootstrap prompt based on the
        service parameters. The prompt can be reviewed before being passed
        to run_agy_bootstrap.

        Args:
            service_name: Name of the service.
            service_type: Type of service (web_app, api_service, database, etc.).
            repo_urls: Git repository URLs for Agy to clone.
            docs_urls: Documentation URLs for reference.
            extra_requirements: Additional free-text requirements.

        Returns the generated prompt as a string.
        """
        prompt = generate_agy_prompt(
            service_name=service_name,
            service_type=service_type,
            repo_urls=repo_urls,
            docs_urls=docs_urls,
            extra_requirements=extra_requirements,
        )
        return prompt

    # ------------------------------------------------------------------
    # Full orchestration
    # ------------------------------------------------------------------

    @mcp.tool
    async def create_service(
        service_name: str,
        service_type: str = "web_app",
        template_key: str = "base",
        vmid: int | None = None,
        tags: list[str] | None = None,
        forward_port: int = 80,
        forward_scheme: str = "http",
        repo_urls: list[str] | None = None,
        docs_urls: list[str] | None = None,
        extra_requirements: str = "",
        skip_dns: bool = False,
        skip_proxy: bool = False,
        skip_agy: bool = False,
        dry_run: bool = False,
    ) -> str:
        """Create a new service — full orchestration flow.

        This is the key high-level tool that performs the entire provisioning:
        1. Validate input and select template
        2. Allocate IP from configured range
        3. Clone LXC template
        4. Configure hostname and network
        5. Start the container
        6. Wait until reachable
        7. Add Pi-hole DNS record
        8. Create NPM reverse proxy host
        9. Generate Agy bootstrap prompt
        10. Execute Agy bootstrap

        Returns a structured JSON result including vmid, hostname, domain,
        IP, template used, proxy target, each completed step, and any
        failure point.

        Args:
            service_name: Name of the service (used for hostname, DNS).
            service_type: Service category (web_app, api_service, etc.).
            template_key: Template to use (base, gpu, gpu_docker).
            vmid: Explicit VMID or auto-select.
            tags: Extra tags for the container.
            forward_port: Port the service listens on inside the LXC.
            forward_scheme: 'http' or 'https'.
            repo_urls: Git repos for Agy to clone.
            docs_urls: Documentation URLs for Agy.
            extra_requirements: Free-text extra instructions for Agy.
            skip_dns: Skip Pi-hole DNS record creation.
            skip_proxy: Skip NPM proxy host creation.
            skip_agy: Skip Agy bootstrap execution.
            dry_run: Validate parameters and external dependencies without modifying state.
        """
        request = ServiceRequest(
            service_name=service_name,
            service_type=ServiceType(service_type),
            template_key=template_key,
            vmid=vmid,
            tags=tags or [],
            forward_port=forward_port,
            forward_scheme=forward_scheme,
            repo_urls=repo_urls or [],
            docs_urls=docs_urls or [],
            extra_requirements=extra_requirements,
            skip_dns=skip_dns,
            skip_proxy=skip_proxy,
            skip_agy=skip_agy,
            dry_run=dry_run,
        )

        result = await service.create_service(request)
        return json.dumps(result.to_summary(), indent=2, default=str)

    @mcp.tool
    async def create_service_dry_run(
        service_name: str,
        service_type: str = "web_app",
        template_key: str = "base",
        vmid: int | None = None,
        forward_port: int = 80,
        forward_scheme: str = "http",
        skip_dns: bool = False,
        skip_proxy: bool = False,
        skip_agy: bool = False,
    ) -> str:
        """Perform a dry-run validation for a service provisioning request without mutating any state.

        Returns a JSON object detailing IP availability, VMID assignment,
        DNS and Proxy host creation plans, and any validation warnings or errors.
        """
        request = ServiceRequest(
            service_name=service_name,
            service_type=ServiceType(service_type),
            template_key=template_key,
            vmid=vmid,
            forward_port=forward_port,
            forward_scheme=forward_scheme,
            skip_dns=skip_dns,
            skip_proxy=skip_proxy,
            skip_agy=skip_agy,
            dry_run=True,
        )

        result = await service.create_service_dry_run(request)
        return json.dumps(result.model_dump(), indent=2)

    # ------------------------------------------------------------------
    # Snapshot & Rollback tools
    # ------------------------------------------------------------------

    @mcp.tool
    async def create_lxc_snapshot(
        vmid: int,
        name: str,
        description: str = "",
    ) -> str:
        """Create a point-in-time snapshot of an LXC container.

        Useful before running Agy bootstraps or applying major config changes
        so the container can be rolled back instantly if something goes wrong.

        Args:
            vmid: The container VMID to snapshot.
            name: Snapshot name (alphanumeric and dashes, e.g. 'pre-agy-bootstrap').
            description: Optional human-readable description of the snapshot.

        Returns a JSON object with vmid, snapshot_name, and action taken.
        """
        result = await service.create_lxc_snapshot(vmid, name, description)
        return json.dumps(result, indent=2)

    @mcp.tool
    async def list_lxc_snapshots(vmid: int) -> str:
        """List all snapshots of an LXC container.

        Args:
            vmid: The container VMID to query.

        Returns a JSON array of snapshot objects with name, description,
        snaptime, and parent snapshot.
        """
        snapshots = await service.list_lxc_snapshots(vmid)
        return json.dumps(snapshots, indent=2, default=str)

    @mcp.tool
    async def rollback_lxc_snapshot(
        vmid: int,
        name: str,
        stop_if_running: bool = True,
    ) -> str:
        """Rollback an LXC container to a previously created snapshot.

        The container must be stopped before rollback. If stop_if_running
        is True (default), the container is stopped automatically. The
        container is NOT restarted after rollback — use start_container
        to bring it back up after verifying the state.

        Args:
            vmid: The container VMID to roll back.
            name: The snapshot name to restore.
            stop_if_running: If True, automatically stop a running container
                before rolling back. If False, raises an error when the
                container is running to prevent accidental data loss.

        Returns a JSON object with vmid, snapshot_name, action, and
        whether the container was_running before rollback.
        """
        result = await service.rollback_lxc_snapshot(vmid, name, stop_if_running)
        return json.dumps(result, indent=2)

    # ------------------------------------------------------------------
    # Command Execution & Diagnostics tools
    # ------------------------------------------------------------------

    @mcp.tool
    async def exec_lxc_command(
        vmid: int,
        command: str,
        timeout: int = 60,
    ) -> str:
        """Execute a shell command inside a running LXC container.

        Connects to the container via the Proxmox SSH bridge (pct exec).
        Requires SSH access to the Proxmox host configured in the server config.

        Use this for quick diagnostics: checking process status, reading files,
        or running one-off admin tasks. For complex multi-step setups, use
        run_agy_bootstrap instead.

        Args:
            vmid: The container VMID to run the command in.
            command: Shell command to execute (e.g. 'systemctl status nginx').
            timeout: Maximum seconds to wait for the command (default 60).

        Returns a JSON object with exit_code, stdout, stderr, and duration_seconds.
        """
        result = await service.exec_lxc_command(vmid, command, timeout)
        return json.dumps(result, indent=2)

    @mcp.tool
    async def get_lxc_service_logs(
        vmid: int,
        service_name: str,
        lines: int = 50,
    ) -> str:
        """Read systemd journal logs for a service running inside an LXC container.

        Equivalent to running 'journalctl -u <service> -n <lines> --no-pager'
        inside the container. Useful for diagnosing services that were deployed
        via Agy bootstrap or manually configured.

        Args:
            vmid: The container VMID to read logs from.
            service_name: Systemd service name (e.g. 'nginx', 'gitea', 'docker').
            lines: Number of recent log lines to return (default 50).

        Returns a JSON object with service_name, logs (as a string), and exit_code.
        """
        result = await service.get_lxc_service_logs(vmid, service_name, lines)
        return json.dumps(result, indent=2)

    # ------------------------------------------------------------------
    # Infrastructure Inspection tools
    # ------------------------------------------------------------------

    @mcp.tool
    async def list_containers() -> str:
        """List all LXC containers on the configured Proxmox node.

        Returns all containers — including those not created by this MCP server —
        with their VMID, name, status, CPU count, memory usage, and uptime.

        Useful as a pre-flight check before create_service, or as the starting
        point for import_existing_lxc to adopt pre-existing containers.

        Returns a JSON array of container objects.
        """
        containers = await service.list_containers()
        return json.dumps(containers, indent=2, default=str)

    @mcp.tool
    async def get_storage_status(storage: str = "local-lvm") -> str:
        """Check disk space usage for a Proxmox storage pool.

        Use this before create_service to verify there is sufficient space
        to clone a template. Also useful when resize_lxc_disk is needed.

        Args:
            storage: Storage pool identifier (default 'local-lvm').
                     Common values: 'local-lvm', 'local', 'pbs-local'.

        Returns a JSON object with total_gb, used_gb, avail_gb, used_pct, and type.
        """
        result = await service.get_storage_status(storage)
        return json.dumps(result, indent=2)

    # ------------------------------------------------------------------
    # Resource Management tools
    # ------------------------------------------------------------------

    @mcp.tool
    async def resize_lxc_disk(
        vmid: int,
        size_gb: int,
        disk: str = "rootfs",
    ) -> str:
        """Grow an LXC container disk to the specified total size in GB.

        Proxmox does not allow shrinking disks — only growing is supported.
        The size_gb value is the NEW TOTAL size, not the amount to add.
        For example, to grow a 20GB disk to 40GB, pass size_gb=40.

        Changes take effect immediately; no container restart required.

        Args:
            vmid: The container VMID whose disk to resize.
            size_gb: New total disk size in GB (must be larger than current size).
            disk: Disk identifier (default 'rootfs').

        Returns a JSON object with vmid, disk, new_size_gb, and action.
        """
        result = await service.resize_lxc_disk(vmid, size_gb, disk)
        return json.dumps(result, indent=2)

    @mcp.tool
    async def update_lxc_resources(
        vmid: int,
        cores: int | None = None,
        memory_mb: int | None = None,
        swap_mb: int | None = None,
    ) -> str:
        """Update CPU cores, RAM, and swap for an LXC container.

        Proxmox supports hot-plug for LXC resources — changes take effect
        immediately without requiring a container restart.

        At least one of cores, memory_mb, or swap_mb must be provided.

        Args:
            vmid: The container VMID to update.
            cores: New number of CPU cores (e.g. 4).
            memory_mb: New RAM allocation in megabytes (e.g. 4096 for 4GB).
            swap_mb: New swap allocation in megabytes (e.g. 512).

        Returns a JSON object with vmid, updated_params, and action.
        """
        result = await service.update_lxc_resources(vmid, cores, memory_mb, swap_mb)
        return json.dumps(result, indent=2)

    # ------------------------------------------------------------------
    # Task Tracking tools
    # ------------------------------------------------------------------

    @mcp.tool
    async def get_task_status(upid: str) -> str:
        """Get the current status of a Proxmox asynchronous task by UPID.

        Proxmox returns a UPID (Unique Process ID) string for long-running
        operations like large clones or template downloads. Use this tool
        to check if the task is still running or has completed.

        Args:
            upid: Proxmox task UPID string (e.g. 'UPID:pve:...:vzdump::root@pam:').

        Returns a JSON object with status ('running' or 'stopped'),
        exitstatus ('OK' or error string), starttime, node, and type.
        """
        result = await service.get_task_status(upid)
        return json.dumps(result, indent=2, default=str)

    @mcp.tool
    async def get_task_log(upid: str, limit: int = 50) -> str:
        """Get the log output of a Proxmox task by UPID.

        Returns structured log lines from the task execution. Useful for
        diagnosing why a task failed or inspecting its progress.

        Args:
            upid: Proxmox task UPID string.
            limit: Maximum number of log lines to return (default 50).

        Returns a JSON array of log line objects with line number (n) and text (t).
        """
        log_lines = await service.get_task_log(upid, limit)
        return json.dumps(log_lines, indent=2, default=str)

    # ------------------------------------------------------------------
    # Brownfield Adoption tools
    # ------------------------------------------------------------------

    @mcp.tool
    async def import_existing_lxc(
        vmid: int,
        service_name: str,
        register_dns: bool = True,
        register_proxy: bool = False,
        forward_port: int = 80,
        forward_scheme: str = "http",
    ) -> str:
        """Adopt an existing LXC container into this MCP server's management.

        Use this for containers that were created manually or outside of this
        MCP server's create_service workflow. After import, the container is
        tracked in the local IPAM and optionally registered in Pi-hole DNS
        and Nginx Proxy Manager.

        The container's current IP is read from its Proxmox configuration.
        If the IP is outside the configured IPAM range, it is still registered
        with an out_of_range flag so it can be managed without conflicts.

        Args:
            vmid: VMID of the existing LXC container to adopt.
            service_name: Name for the service (used for hostname and domain).
            register_dns: Add a Pi-hole DNS record (default True).
            register_proxy: Create an NPM reverse proxy host (default False).
            forward_port: Service port for the proxy host (default 80).
            forward_scheme: Proxy forward scheme, 'http' or 'https' (default 'http').

        Returns a JSON object with vmid, hostname, domain, ip, container_status,
        registered_in_ipam, out_of_range, dns_action, and proxy_action.
        """
        result = await service.import_existing_lxc(
            vmid=vmid,
            service_name=service_name,
            register_dns=register_dns,
            register_proxy=register_proxy,
            forward_port=forward_port,
            forward_scheme=forward_scheme,
        )
        return json.dumps(result, indent=2, default=str)

    # ------------------------------------------------------------------
    # Proxmox Host Operations tools
    # ------------------------------------------------------------------

    @mcp.tool
    async def exec_host_command(
        command: str,
        timeout: int = 60,
    ) -> str:
        """Execute a command directly on the Proxmox host (not inside a container).

        Runs a shell command directly on the Proxmox VE hypervisor host via SSH.
        Use this for host-level diagnostics, checking storage pools (zpool, lvm),
        inspecting cluster status (pvecm), or one-off host administration tasks.

        Args:
            command: Shell command to execute on the Proxmox host.
            timeout: Maximum seconds to wait for the command (default 60).

        Returns a JSON object with command, exit_code, stdout, stderr, and duration_seconds.
        """
        result = await service.exec_host_command(command, timeout)
        return json.dumps(result, indent=2)

    @mcp.tool
    async def run_host_agy(
        prompt: str,
        working_dir: str = "/root",
        timeout: int = 600,
    ) -> str:
        """Run an Agy session directly on the Proxmox host for host-level administration.

        Executes the Agy AI agent on the Proxmox VE host machine via SSH.
        Use this for complex host administration tasks such as configuring ZFS datasets,
        managing custom LXC templates, network configuration, or system maintenance.

        CAUTION: The Proxmox host is critical infrastructure. Ensure prompts are safety-aware
        or generate them using generate_host_agy_prompt first.

        Args:
            prompt: The task instruction prompt for Agy.
            working_dir: Working directory on the Proxmox host (default: /root).
            timeout: Maximum seconds to wait for Agy to complete (default 600).

        Returns a JSON object with action, exit_code, stdout, stderr, and duration_seconds.
        """
        result = await service.run_host_agy(prompt, working_dir, timeout)
        return json.dumps(result, indent=2)

    @mcp.tool
    async def generate_host_agy_prompt(
        task_description: str,
        task_category: str = "maintenance",
        extra_requirements: str = "",
        docs_urls: list[str] | None = None,
    ) -> str:
        """Generate a safety-aware Agy prompt for Proxmox host operations.

        Creates a structured prompt tailored for running Agy directly on the Proxmox
        hypervisor host, including explicit safety rules and guardrails (e.g. avoiding
        accidental removal of Proxmox core packages or direct /etc/pve modifications).

        Args:
            task_description: Description of the host administration task.
            task_category: Category: maintenance, template, storage, network, custom (default: maintenance).
            extra_requirements: Additional constraints or instructions.
            docs_urls: Optional reference documentation URLs.

        Returns a formatted multi-line markdown prompt ready to pass to run_host_agy.
        """
        prompt = _generate_host_agy_prompt(
            task_description=task_description,
            task_category=task_category,
            extra_requirements=extra_requirements,
            docs_urls=docs_urls,
        )
        return prompt

