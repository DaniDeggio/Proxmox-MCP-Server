.PHONY: test lint check run dev clean

test:
	uv run pytest tests/ -v --tb=short

test-cov:
	uv run pytest tests/ -v --cov=proxmox_mcp_server --cov-report=term-missing

lint:
	uv run ruff check src/ tests/
	uv run mypy src/proxmox_mcp_server/ --ignore-missing-imports

check: lint test

dev:
	./scripts/run_dev.sh

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
