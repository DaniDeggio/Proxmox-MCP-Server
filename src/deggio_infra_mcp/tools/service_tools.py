"""MCP tool registrations — thin wrappers that connect the FastMCP
transport layer to the service layer.

Each function is registered via ``@mcp.tool`` and delegates to
``ProvisioningService`` public methods.  The tools themselves
contain no business logic — they validate MCP inputs and format outputs.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from deggio_infra_mcp.models.service import ServiceRequest, ServiceType
from deggio_infra_mcp.services.prompt_generator import generate_agy_prompt

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from deggio_infra_mcp.services.provisioning import ProvisioningService


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
            domain: The domain name (e.g. 'myservice.deggio.local').
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
        )

        result = await service.create_service(request)
        return json.dumps(result.to_summary(), indent=2, default=str)
