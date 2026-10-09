.PHONY: setup test validate review clean

setup:  ## Install the Python dependencies and the pre-commit hooks
	uv sync
	uv run pre-commit install

ANALYSIS_COVERAGE = 90

test:  ## Lint, type-check, test, and hold analysis/ to its coverage floor
	uv run ruff check
	uv run ruff format --check
	uv run pyright
	uv run pytest --cov
	uv run coverage report --include="*/getgood/analysis/*" --fail-under=$(ANALYSIS_COVERAGE)

validate:  ## Score verdicts and bombs against the labels in validation/, on local data
	uv run python -m getgood.validation

review:  ## Draw review-bomb events into validation/reviewed_events.yaml to mark by hand
	uv run python -m getgood.validation review

clean:  ## Delete caches and build output, never data/
	rm -rf .pytest_cache .ruff_cache .hypothesis dist build
	find src tests -name __pycache__ -type d -prune -exec rm -rf {} +
