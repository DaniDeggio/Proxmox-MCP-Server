"""Tests for the Proxmox host Agy prompt generator."""

from __future__ import annotations

from proxmox_mcp_server.services.prompt_generator import generate_host_agy_prompt


def test_generate_host_agy_prompt_contains_guardrails() -> None:
    """The generated prompt must contain explicit Proxmox safety guardrails."""
    prompt = generate_host_agy_prompt(
        task_description="Clean up old ISO images",
        task_category="maintenance",
    )
    assert "NEVER remove packages matching `proxmox-*`" in prompt
    assert "NEVER modify `/etc/pve/` files directly" in prompt
    assert "ALWAYS back up configuration files before modifying them" in prompt
    assert "Clean up old ISO images" in prompt


def test_generate_host_agy_prompt_categories() -> None:
    """The prompt includes specific notes for different task categories."""
    p_storage = generate_host_agy_prompt(
        task_description="Configure ZFS scrub cron",
        task_category="storage",
    )
    assert "storage pools, ZFS datasets, LVM" in p_storage

    p_network = generate_host_agy_prompt(
        task_description="Add VLAN 20 to bridge",
        task_category="network",
    )
    assert "network bridges (vmbr), VLANs" in p_network

    p_template = generate_host_agy_prompt(
        task_description="Download Debian 12 template",
        task_category="template",
    )
    assert "LXC container templates (pveam, pct)" in p_template


def test_generate_host_agy_prompt_with_docs_and_requirements() -> None:
    """The prompt formats docs URLs and extra requirements when provided."""
    prompt = generate_host_agy_prompt(
        task_description="Setup custom backup retention",
        task_category="maintenance",
        extra_requirements="Do not touch existing dump/ folder",
        docs_urls=["https://pve.proxmox.com/wiki/Backup_and_Restore"],
    )
    assert "## Reference documentation" in prompt
    assert "https://pve.proxmox.com/wiki/Backup_and_Restore" in prompt
    assert "## Additional requirements" in prompt
    assert "Do not touch existing dump/ folder" in prompt


def test_generate_host_agy_prompt_default_category() -> None:
    """Unknown or default category falls back safely."""
    prompt = generate_host_agy_prompt(
        task_description="Custom task",
        task_category="unknown_cat",
    )
    assert "Execute the custom host administration task safely" in prompt
