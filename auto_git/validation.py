"""Linting and validation functions for commits."""

from .config import COMMIT_SUBJECT_RE, COMMIT_TYPES


def lint_commit_dict(commit):
    """
    Validate a commit dictionary and return the formatted subject line.
    
    Raises ValueError if validation fails.
    """
    ctype = commit.get("type")
    title = commit.get("title", "")
    body = commit.get("body", "")
    files = commit.get("files", [])

    if ctype not in COMMIT_TYPES:
        raise ValueError(f"Invalid commit type: {ctype}")

    if not isinstance(title, str) or not title.strip():
        raise ValueError("Commit title is required")

    if len(title) > 75:
        raise ValueError("Commit title must be less than 75 characters")

    if not isinstance(files, list) or not files:
        raise ValueError("Commit files are required")

    subject = f"{ctype}: {title}"
    if not COMMIT_SUBJECT_RE.match(subject):
        raise ValueError("Commit title must match the format: <type>(<scope>): <subject>")

    if body is not None and not isinstance(body, str):
        raise ValueError("Commit body must be a string")

    return subject


def lint_git_commit_subject(subject):
    """
    Validate a git commit subject line.
    
    Raises ValueError if validation fails.
    """
    if not COMMIT_SUBJECT_RE.match(subject):
        raise ValueError("Commit subject must match the format: <type>(<scope>): <subject>")
