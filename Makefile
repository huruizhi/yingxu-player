PYTHON ?= python3.12
VENV := .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

.PHONY: setup lint format test test-fixtures run package install clean

setup:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	$(PY) scripts/check_libmpv.py

lint:
	$(VENV)/bin/ruff check src tests
	$(VENV)/bin/isort --check-only src tests
	$(VENV)/bin/black --check src tests

format:
	$(VENV)/bin/isort src tests
	$(VENV)/bin/black src tests
	$(VENV)/bin/ruff check --fix src tests

test-fixtures:
	$(PY) scripts/generate_test_media.py

test: test-fixtures
	$(PY) -m pytest

test-cov:
	$(PY) -m pytest --cov=src/player --cov-report=term-missing

run:
	$(PY) -m player.app

package:
	$(PY) -m PyInstaller packaging/player.spec --noconfirm

install: package
	mkdir -p "$(HOME)/Applications"
	rm -rf "$(HOME)/Applications/Yingxu.app"
	ditto dist/Yingxu.app "$(HOME)/Applications/Yingxu.app"
	open "$(HOME)/Applications/Yingxu.app"

clean:
	rm -rf build dist .pytest_cache .coverage htmlcov
	find . -name __pycache__ -type d -exec rm -rf {} +
