.PHONY: install lint typecheck test

install:
	uv venv
	uv pip install -e ".[dev,postgres]"

lint:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

typecheck:
	uv run mypy src/ tests/

test:
	uv run pytest
