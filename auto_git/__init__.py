"""Auto-git: AI-powered git commit automation."""

import warnings

import urllib3

# Suppress urllib3 warnings about OpenSSL
warnings.filterwarnings("ignore", category=urllib3.exceptions.NotOpenSSLWarning)

# Re-export the public API for library-style usage (and tests).
from .ai import (  # noqa: F401
    ask_openai_for_amendments,
    ask_openai_for_commits,
    ask_openai_for_fix,
    get_openai_client,
    parse_json_from_openai_response,
)
from .cli import cli, main
from .config import __version__
from .git import (  # noqa: F401
    apply_commits,
    apply_fix_plan,
    get_changed_files,
    get_commits_for_fix,
    get_commits_since_push,
    get_current_branch,
    get_diff,
    get_unpushed_commits,
    get_untracked_files,
    get_upstream_ref,
    is_git_ignored,
    is_tracked,
    rewrite_commits,
    run,
)
from .ui import display_spinning_animation, format_commit_preview  # noqa: F401
from .validation import lint_commit_dict, lint_git_commit_subject  # noqa: F401
from .watcher import ChangeHandler  # noqa: F401


def get_origin_repo_slug():
    """Extract the owner/repo slug from the origin remote URL."""
    from urllib.parse import urlparse

    url = run("git config --get remote.origin.url")
    if url.startswith("git@"):
        _, path = url.split(":", 1)
    elif url.startswith("https://") or url.startswith("http://"):
        parts = url.split("/")
        path = "/".join(parts[-2:])
    elif url.startswith("ssh://"):
        parsed = urlparse(url)
        host = (parsed.netloc or "").split("@")[-1]
        repo_path = (parsed.path or "").lstrip("/")
        path = f"{host}/{repo_path}" if host and repo_path else url
    else:
        path = url

    if path.endswith(".git"):
        path = path[:-4]

    if "/" not in path:
        raise RuntimeError(f"Could not determine repo slug from URL: {url}")

    return path

__all__ = [
    "__version__",
    # CLI
    "cli",
    "main",
    # Git
    "run",
    "get_upstream_ref",
    "get_current_branch",
    "get_origin_repo_slug",
    "is_tracked",
    "is_git_ignored",
    "get_untracked_files",
    "get_changed_files",
    "get_diff",
    "get_commits_since_push",
    "get_unpushed_commits",
    "get_commits_for_fix",
    "apply_fix_plan",
    "apply_commits",
    "rewrite_commits",
    # AI
    "get_openai_client",
    "parse_json_from_openai_response",
    "ask_openai_for_commits",
    "ask_openai_for_amendments",
    "ask_openai_for_fix",
    # Validation/UI
    "lint_commit_dict",
    "lint_git_commit_subject",
    "display_spinning_animation",
    "format_commit_preview",
    # Watcher
    "ChangeHandler",
]
