.PHONY: dev build test lint format clean install sync

install sync:
	uv sync

dev:
	@echo "Define inspect eval entrypoints in a later phase." && exit 0

build:
	uv build

test:
	uv run pytest tests

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

format:
	uv run ruff check --fix src tests
	uv run ruff format src tests

clean:
	rm -rf dist build .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
