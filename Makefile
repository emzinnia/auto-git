.PHONY: help install generate commit status lint watch

help:
\t@echo "Common commands:"
\t@echo "  make install     Install dependencies"
\t@echo "  make generate    Generate commit suggestions (uses staged+unstaged)"
\t@echo "  make commit      Generate and apply commits (uses staged+unstaged)"
\t@echo "  make status      Show staged/unstaged files"
\t@echo "  make lint        Lint recent commit messages"
\t@echo "  make watch       Watch for changes and auto-commit"

install:
\tpython3 -m pip install -r requirements.txt

generate:
\tpython3 auto_git.py generate $(ARGS)

commit:
\tpython3 auto_git.py commit $(ARGS)

status:
\tpython3 auto_git.py status

lint:
\tpython3 auto_git.py lint $(ARGS)

watch:
\tpython3 auto_git.py watch $(ARGS)

