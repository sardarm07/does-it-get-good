.PHONY: setup test validate clean

setup:  ## Install the Python dependencies and the pre-commit hooks
	uv sync
	uv run pre-commit install

test:  ## Lint, type-check and test
	uv run ruff check
	uv run ruff format --check
	uv run pyright
	uv run pytest

validate:  ## Score the verdicts against validation/turning_points.yaml on local data
	uv run python -m getgood.validation

clean:  ## Delete caches and build output, never data/
	rm -rf .pytest_cache .ruff_cache .hypothesis dist build
	find src tests -name __pycache__ -type d -prune -exec rm -rf {} +
