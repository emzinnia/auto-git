.PHONY: help venv deps dev clean install uninstall

PYTHON := python3.11
VENV := venv
BIN := $(VENV)/bin
INSTALL_PATH := /usr/local/bin/auto-git

help:
	@echo "auto-git - AI-powered Git commit message generator"
	@echo ""
	@echo "Development:"
	@echo "  make venv     - Create virtual environment"
	@echo "  make deps     - Install dependencies"
	@echo "  make dev      - Setup development environment (venv + deps)"
	@echo "  make lint     - Run Ruff linting checks"
	@echo "  make clean    - Remove venv and build artifacts"
	@echo ""
	@echo "Installation:"
	@echo "  make install   - Install auto-git command to $(INSTALL_PATH)"
	@echo "  make uninstall - Remove auto-git from $(INSTALL_PATH)"

venv:
	$(PYTHON) -m venv $(VENV)
	@echo "Virtual environment created at $(VENV)/"

deps: $(BIN)/activate
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements.txt
	@echo "Dependencies installed"

dev: venv deps
	@echo "Development environment ready"
	@echo "Activate with: source $(VENV)/bin/activate"

lint: deps
	$(BIN)/ruff check .

clean:
	rm -rf $(VENV)
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleaned up"

install: deps
	@echo "Installing auto-git to $(INSTALL_PATH)..."
	@echo '#!/bin/bash' | sudo tee $(INSTALL_PATH) > /dev/null
	@echo 'source "$(CURDIR)/$(BIN)/activate"' | sudo tee -a $(INSTALL_PATH) > /dev/null
	@echo 'python "$(CURDIR)/auto_git.py" "$$@"' | sudo tee -a $(INSTALL_PATH) > /dev/null
	sudo chmod +x $(INSTALL_PATH)
	@echo "Installed! Run 'auto-git --help' to get started"

uninstall:
	@if [ -f $(INSTALL_PATH) ]; then \
		sudo rm $(INSTALL_PATH); \
		echo "Uninstalled auto-git from $(INSTALL_PATH)"; \
	else \
		echo "auto-git is not installed at $(INSTALL_PATH)"; \
	fi

