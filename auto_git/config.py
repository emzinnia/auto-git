"""Configuration constants and settings for auto-git."""

import re

__version__ = "0.1.0"

COMMIT_TYPES = {
    "feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert"
}

COMMIT_SUBJECT_RE = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\(.+\))?: .+$"
)

OPENAI_MODEL_COMMITS = "gpt-4.1"
OPENAI_MODEL_PR = "gpt-4.1-mini"
