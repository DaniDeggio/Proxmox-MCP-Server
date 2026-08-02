"""Tests for Agy prompt generation."""

from __future__ import annotations

from proxmox_mcp_server.services.prompt_generator import generate_agy_prompt


class TestPromptGeneration:
    """Tests for deterministic prompt output."""

    def test_generate_agy_prompt_minimal(self) -> None:
        """works with minimal fields."""
        prompt = generate_agy_prompt(
            service_name="my-api",
            service_type="api_service",
        )
        assert "# Bootstrap: my-api" in prompt
        assert "api_service" in prompt
        assert "apt update" in prompt

    def test_generate_agy_prompt_with_all_fields(self) -> None:
        """includes all provided fields."""
        prompt = generate_agy_prompt(
            service_name="full-svc",
            service_type="web_app",
            hostname="full-svc-host",
            ip="192.168.1.210",
            repo_urls=["https://github.com/user/repo1", "https://github.com/user/repo2"],
            docs_urls=["https://docs.example.com/setup"],
            extra_requirements="Must use PostgreSQL 16 and Redis 7.",
        )
        assert "# Bootstrap: full-svc" in prompt
        assert "full-svc-host" in prompt
        assert "192.168.1.210" in prompt
        assert "https://github.com/user/repo1" in prompt
        assert "https://github.com/user/repo2" in prompt
        assert "https://docs.example.com/setup" in prompt
        assert "PostgreSQL 16" in prompt

    def test_generate_agy_prompt_deterministic(self) -> None:
        """same inputs produce same output."""
        kwargs = {
            "service_name": "det-test",
            "service_type": "web_app",
            "hostname": "det-host",
            "ip": "192.168.1.200",
            "repo_urls": ["https://github.com/x/y"],
            "extra_requirements": "Use Python 3.12",
        }
        prompt1 = generate_agy_prompt(**kwargs)
        prompt2 = generate_agy_prompt(**kwargs)
        assert prompt1 == prompt2

    def test_prompt_completion_criteria(self) -> None:
        prompt = generate_agy_prompt(service_name="any", service_type="web_app")
        assert "Completion criteria" in prompt
        assert "health checks" in prompt
