.PHONY: setup test data history validate review backup clean

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

DATA = $(or $(GETGOOD_DATA),data)

data:  ## Download, check and load IMDb's latest files, without the archive
	uv run getgood sync --no-history

history:  ## The same, then fill the history from the Internet Archive (hours the first time)
	uv run getgood sync

validate:  ## Score verdicts and bombs against the labels in validation/, on local data
	uv run python -m getgood.validation

review:  ## Draw review-bomb events into validation/reviewed_events.yaml to mark by hand
	uv run python -m getgood.validation review

# Copies only: a backup never loses a file because the history lost it. Restoring is safe
# too, as a day already in its month's file keeps the copy it has.
backup:  ## Copy the history to BACKUP_DIR, e.g. make backup BACKUP_DIR=/Volumes/Drive/getgood
	@test -n "$(BACKUP_DIR)" || { echo "Say where: make backup BACKUP_DIR=/Volumes/Drive/getgood"; exit 2; }
	@find "$(DATA)/history" -name "*.parquet" 2>/dev/null | grep -q . || { echo "$(DATA)/history/ holds no history yet."; exit 2; }
	mkdir -p "$(BACKUP_DIR)/history"
	rsync -a "$(DATA)/history/" "$(BACKUP_DIR)/history/"
	@echo "Backed up. To restore: rsync -a \"$(BACKUP_DIR)/history/\" $(DATA)/history/"

clean:  ## Delete caches and build output, never data/
	rm -rf .pytest_cache .ruff_cache .hypothesis dist build
	find src tests -name __pycache__ -type d -prune -exec rm -rf {} +
