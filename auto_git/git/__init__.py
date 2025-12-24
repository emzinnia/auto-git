"""Git utilities package."""

from .core import (
    get_current_branch,
    get_origin_repo_slug,
    get_upstream_ref,
    is_git_ignored,
    is_tracked,
    run,
)
from .diff import (
    get_changed_files,
    get_diff,
    get_untracked_files,
)
from .history import (
    apply_commits,
    apply_fix_plan,
    get_commits_for_fix,
    get_commits_since_push,
    get_unpushed_commits,
    rewrite_commits,
)

__all__ = [
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
]
