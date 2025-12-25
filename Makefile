.PHONY: help sync dev lint test clean run install uninstall

UV ?= uv

help:
	@echo "auto-git - AI-powered Git commit message generator"
	@echo ""
	@echo "Development:"
	@echo "  make sync     - Create/update .venv and install all deps via uv"
	@echo "  make dev      - Alias for sync"
	@echo "  make lint     - Run Ruff linting checks"
	@echo "  make test     - Run tests"
	@echo "  make run      - Run auto-git (help)"
	@echo "  make clean    - Remove venv and build artifacts"
	@echo ""
	@echo "Installation:"
	@echo "  make install   - Install the auto-git CLI as a uv tool"
	@echo "  make uninstall - Uninstall the auto-git CLI uv tool"

sync:
	$(UV) sync --all-groups

dev: sync

lint:
	$(UV) run ruff check .

test:
	$(UV) run pytest

run:
	$(UV) run auto-git --help

clean:
	rm -rf .venv
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleaned up"

install:
	$(UV) tool install --editable .
	@echo "Installed! Run 'auto-git --help' to get started"

uninstall:
	$(UV) tool uninstall auto-git || true

