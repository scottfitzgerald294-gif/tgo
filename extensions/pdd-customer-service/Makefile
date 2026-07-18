SHELL := /bin/sh
.DEFAULT_GOAL := help

POETRY ?= poetry

.PHONY: help run format lint test test-unit test-integration security-check

help:
	@echo "PDD customer service development commands"
	@echo "  make run"
	@echo "  make format"
	@echo "  make lint"
	@echo "  make test"
	@echo "  make test-unit"
	@echo "  make test-integration"
	@echo "  make security-check"

run:
	$(POETRY) run uvicorn app.main:app --host 127.0.0.1 --port 8091

format:
	$(POETRY) run ruff format app tests

lint:
	$(POETRY) run ruff format --check app tests
	$(POETRY) run ruff check app tests
	$(POETRY) run mypy app tests

test:
	$(POETRY) run python -m pytest

test-unit:
	$(POETRY) run python -m pytest tests/unit

test-integration:
	$(POETRY) run python -m pytest tests/integration

security-check:
	$(POETRY) run bandit -q -r app
	$(POETRY) run pip-audit
	git check-ignore -q .env
