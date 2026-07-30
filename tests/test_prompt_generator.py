"""Tests for Agy prompt generation."""

from __future__ import annotations

from deggio_infra_mcp.services.prompt_generator import generate_agy_prompt


class TestPromptGeneration:
    """Tests for deterministic prompt output."""

    def test_basic_prompt(self) -> None:
        prompt = generate_agy_prompt(
            service_name="my-api",
            service_type="api_service",
        )
        assert "# Bootstrap: my-api" in prompt
        assert "api_service" in prompt
        assert "apt update" in prompt

    def test_prompt_with_repos(self) -> None:
        prompt = generate_agy_prompt(
            service_name="web-app",
            service_type="web_app",
            repo_urls=["https://github.com/user/repo1", "https://github.com/user/repo2"],
        )
        assert "https://github.com/user/repo1" in prompt
        assert "https://github.com/user/repo2" in prompt
        assert "Clone and set up" in prompt

    def test_prompt_with_docs(self) -> None:
        prompt = generate_agy_prompt(
            service_name="worker",
            service_type="worker",
            docs_urls=["https://docs.example.com/setup"],
        )
        assert "Reference documentation" in prompt
        assert "https://docs.example.com/setup" in prompt

    def test_prompt_with_extra_requirements(self) -> None:
        prompt = generate_agy_prompt(
            service_name="custom-svc",
            service_type="custom",
            extra_requirements="Must use PostgreSQL 16 and Redis 7.",
        )
        assert "Additional requirements" in prompt
        assert "PostgreSQL 16" in prompt

    def test_prompt_with_host_info(self) -> None:
        prompt = generate_agy_prompt(
            service_name="hosted-svc",
            service_type="web_app",
            hostname="hosted-svc",
            ip="192.168.1.200",
        )
        assert "hosted-svc" in prompt
        assert "192.168.1.200" in prompt

    def test_prompt_deterministic(self) -> None:
        """Same inputs should produce identical output."""
        kwargs = {
            "service_name": "det-test",
            "service_type": "web_app",
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
