# Developer convenience targets. The platform runs keyless by default, so every
# target here works with no credentials and no network access.

PY ?= .venv/bin/python
PIP ?= $(PY) -m pip

.PHONY: help venv install dev lint fmt typecheck test cov diagrams demo clean

help:
	@echo "Targets"
	@echo "  venv       create a local virtual environment in .venv"
	@echo "  install    install the package"
	@echo "  dev        install the package with dev and analysis extras"
	@echo "  lint       run ruff"
	@echo "  fmt        autoformat with ruff"
	@echo "  typecheck  run mypy"
	@echo "  test       run the keyless test suite"
	@echo "  cov        run tests with coverage"
	@echo "  demo       run the end to end synthetic backtest"
	@echo "  clean      remove caches and the local store"

venv:
	python3 -m venv .venv
	$(PIP) install --upgrade pip

install:
	$(PIP) install -e .

dev:
	$(PIP) install -e ".[dev,stats,analysis]"

lint:
	$(PY) -m ruff check src tests

fmt:
	$(PY) -m ruff check --fix src tests
	$(PY) -m ruff format src tests

typecheck:
	$(PY) -m mypy src

test:
	$(PY) -m pytest

cov:
	$(PY) -m pytest --cov=ombench --cov-report=term-missing

diagrams:
	plantuml -tsvg docs/diagrams/*.puml

demo:
	$(PY) -m ombench.cli.main demo

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	rm -rf .ombench
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
