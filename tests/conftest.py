import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def tmp_git_repo(tmp_path):
    """Create a temporary git repository with user config set."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(cmd):
        subprocess.check_call(f"git -C {repo} {cmd}", shell=True)

    git("init")
    git('config user.email "test@example.com"')
    git('config user.name "Test User"')
    return repo, git


@pytest.fixture(autouse=True)
def clear_openai_key(monkeypatch):
    """Ensure OPEN_AI_API_KEY is absent during tests."""
    monkeypatch.delenv("OPEN_AI_API_KEY", raising=False)
    return


@pytest.fixture
def write_file():
    def _write(base: Path, name: str, content: str = "sample"):
        path = base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    return _write

