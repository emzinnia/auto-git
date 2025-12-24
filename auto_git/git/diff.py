"""Diff and file change detection utilities."""

from .core import run


def get_untracked_files():
    """Get list of untracked files (excluding ignored files)."""
    out = run("git ls-files --others --exclude-standard")
    if not out:
        return []
    return [f for f in out.splitlines() if f.strip()]


def get_changed_files(staged=False, unstaged=False, untracked=False, untracked_files=None):
    """
    Get list of changed files based on specified criteria.
    
    Args:
        staged: Include staged changes
        unstaged: Include unstaged changes
        untracked: Include untracked files
        untracked_files: Pre-computed list of untracked files (optional)
    
    Returns:
        List of file paths
    """
    files = []

    if staged:
        out = run("git diff --cached --name-only")
        if out:
            files.extend(out.splitlines())
    
    if unstaged:
        out = run("git diff --name-only")
        if out:
            for f in out.splitlines():
                if f and f not in files:
                    files.append(f)

    if untracked:
        if untracked_files is None:
            untracked_files = get_untracked_files()
        for f in untracked_files:
            if f and f not in files:
                files.append(f)
    
    return files


def get_diff(files, staged=False, unstaged=False, untracked_files=None):
    """
    Get the diff for specified files.
    
    Args:
        files: List of file paths
        staged: Include staged diff
        unstaged: Include unstaged diff
        untracked_files: List of untracked files to include
    
    Returns:
        Combined diff string
    """
    diff_parts = []

    if staged and files:
        diff_parts.append(f"git diff --cached -- " + " ".join(files))
    if unstaged and files:
        diff_parts.append(f"git diff -- " + " ".join(files))
    if untracked_files:
        for f in untracked_files:
            diff_parts.append(f"git diff --no-index -- /dev/null {f}")

    return "\n".join(part for part in diff_parts if part)
