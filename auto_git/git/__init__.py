"""Git utilities package."""

from .core import (
    run,
    get_upstream_ref,
    get_current_branch,
    get_origin_repo_slug,
    is_tracked,
    is_git_ignored,
)
from .diff import (
    get_untracked_files,
    get_changed_files,
    get_diff,
)
from .history import (
    get_commits_since_push,
    get_unpushed_commits,
    get_commits_for_fix,
    apply_fix_plan,
    apply_commits,
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
