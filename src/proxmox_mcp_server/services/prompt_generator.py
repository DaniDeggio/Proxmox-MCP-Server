"""Agy prompt generator — builds structured bootstrap prompts.

The generated prompt tells Agy what to set up inside a freshly
provisioned LXC container.  It is deterministic given the same inputs
so results can be compared and reproduced.
"""

from __future__ import annotations


def generate_agy_prompt(
    service_name: str,
    service_type: str,
    *,
    hostname: str = "",
    ip: str = "",
    repo_urls: list[str] | None = None,
    docs_urls: list[str] | None = None,
    extra_requirements: str = "",
) -> str:
    """Generate a detailed Agy bootstrap prompt.

    Args:
        service_name: Human name of the service.
        service_type: Category (web_app, api_service, etc.).
        hostname: Container hostname.
        ip: Container IP.
        repo_urls: Git repositories for Agy to clone and set up.
        docs_urls: Documentation links for Agy to reference.
        extra_requirements: Free-text extra instructions.

    Returns:
        A multi-line string suitable for passing to Agy as a bootstrap prompt.
    """
    repo_urls = repo_urls or []
    docs_urls = docs_urls or []

    sections: list[str] = [
        f"# Bootstrap: {service_name}",
        "",
        "## Context",
        f"You are setting up a new service called **{service_name}** "
        f"(type: {service_type}) inside a Debian/Ubuntu LXC container.",
    ]

    if hostname or ip:
        sections.append("")
        sections.append("## Container details")
        if hostname:
            sections.append(f"- Hostname: `{hostname}`")
        if ip:
            sections.append(f"- IP: `{ip}`")

    sections.extend([
        "",
        "## Instructions",
        "",
        "1. Update the system packages (`apt update && apt upgrade -y`).",
        "2. Install any required system dependencies for the service.",
    ])

    step = 3
    if repo_urls:
        sections.append(f"{step}. Clone and set up the following repositories:")
        for url in repo_urls:
            sections.append(f"   - `{url}`")
        step += 1

    sections.append(
        f"{step}. Configure the service to start automatically (systemd service or equivalent)."
    )
    step += 1
    sections.append(
        f"{step}. Verify the service is running and accessible on the expected port."
    )
    step += 1

    if docs_urls:
        sections.append("")
        sections.append("## Reference documentation")
        for url in docs_urls:
            sections.append(f"- {url}")

    if extra_requirements:
        sections.append("")
        sections.append("## Additional requirements")
        sections.append(extra_requirements)

    sections.extend([
        "",
        "## Completion criteria",
        "- All packages installed and configured.",
        "- Service running and responding to health checks.",
        "- Firewall rules set if needed (only the service port should be exposed).",
        "- A brief summary of what was done printed to stdout.",
    ])

    return "\n".join(sections)


def generate_host_agy_prompt(
    task_description: str,
    task_category: str = "maintenance",
    *,
    extra_requirements: str = "",
    docs_urls: list[str] | None = None,
) -> str:
    """Generate a safety-aware Agy prompt for Proxmox host operations.

    Args:
        task_description: Description of the host administration task.
        task_category: One of maintenance, template, storage, network, custom.
        extra_requirements: Additional constraints or requirements.
        docs_urls: Reference URLs for documentation.

    Returns:
        A multi-line structured prompt string for Agy on the Proxmox host.
    """
    docs_urls = docs_urls or []

    category_notes: dict[str, str] = {
        "maintenance": "Focus on system health, package updates, cleanups, and diagnostics.",
        "template": "Focus on managing or customizing LXC container templates (pveam, pct).",
        "storage": "Focus on storage pools, ZFS datasets, LVM, and Proxmox storage configuration.",
        "network": "Focus on network bridges (vmbr), VLANs, routing, and firewall rules.",
        "custom": "Execute the custom host administration task safely.",
    }

    cat_desc = category_notes.get(task_category, category_notes["custom"])

    sections: list[str] = [
        f"# Host Task: {task_description}",
        "",
        "## Context",
        "You are operating directly on a **Proxmox VE hypervisor host**. "
        "This machine runs the Proxmox Virtual Environment and manages all VMs and LXC containers.",
        f"Category ({task_category}): {cat_desc}",
        "",
        "## Safety Rules",
        "- NEVER remove packages matching `proxmox-*`, `pve-*`, `ceph-*`, or `corosync`.",
        "- NEVER modify `/etc/pve/` files directly unless explicitly instructed.",
        "- ALWAYS back up configuration files before modifying them: `cp <file> <file>.bak.$(date +%s)`.",
        "- ALWAYS verify changes are safe with dry-run flags when available.",
        "- If unsure about a destructive operation, print a warning and STOP.",
        "",
        "## Available Tools & Commands",
        "You have access to Proxmox VE administration tools including `pveam`, `pct`, `qm`, `pvecm`, `zpool`, `zfs`, and standard Linux utilities.",
        "",
        "## Instructions",
        f"1. {task_description}",
    ]

    if docs_urls:
        sections.append("")
        sections.append("## Reference documentation")
        for url in docs_urls:
            sections.append(f"- {url}")

    if extra_requirements:
        sections.append("")
        sections.append("## Additional requirements")
        sections.append(extra_requirements)

    sections.extend([
        "",
        "## Completion criteria",
        "- Task completed safely without disrupting hypervisor or running containers.",
        "- Any modified configuration files have backups.",
        "- A clear summary of changes and verification steps printed to stdout.",
    ])

    return "\n".join(sections)

