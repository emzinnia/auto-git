"""Core git utilities and subprocess wrappers."""

import os
import shlex
import subprocess


def run(cmd):
    """
    Run a command and return stripped output.

    Accepts either a string (split using shlex) or an argv list. We avoid invoking
    a shell so file paths containing characters like '(' and ')' are handled
    safely.
    """
    args = cmd if isinstance(cmd, (list, tuple)) else shlex.split(cmd)
    return (
        subprocess.check_output(args, stderr=subprocess.STDOUT)
        .decode("utf-8", errors="ignore")
        .strip()
    )


def get_upstream_ref():
    """
    Return the upstream ref if present; suppress git stderr noise when absent.
    """
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            stderr=subprocess.DEVNULL,
        )
        return out.decode("utf-8", errors="ignore").strip()
    except subprocess.CalledProcessError:
        return None


def get_current_branch():
    """Get the current git branch name."""
    return run("git rev-parse --abbrev-ref HEAD")


def get_origin_repo_slug():
    """Extract the owner/repo slug from the origin remote URL."""
    url = run("git config --get remote.origin.url")
    if url.startswith("git@"):
        _, path = url.split(":", 1)
    elif url.startswith("https://") or url.startswith("http://"):
        parts = url.split("/")
        path = "/".join(parts[-2:])
    else:
        path = url
    
    if path.endswith(".git"):
        path = path[:-4]
    
    if "/" not in path:
        raise RuntimeError(f"Could not determine repo slug from URL: {url}")

    return path


def is_tracked(path):
    """Check if a file is tracked by git."""
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def is_git_ignored(path):
    """Check if a path is ignored by git (including .git directory)."""
    rel_path = os.path.relpath(path, ".")
    if rel_path.startswith(".git"):
        return True
    result = subprocess.run(
        ["git", "check-ignore", "-q", rel_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0
