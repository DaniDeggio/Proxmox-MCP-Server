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
