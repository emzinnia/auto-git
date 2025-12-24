"""Commit history operations including rewriting and applying commits."""

import os
import shlex
import subprocess

import click

from .core import run, get_upstream_ref, is_tracked
from ..validation import lint_commit_dict


def get_commits_since_push(fallback_count=10):
    """
    Get commit subjects since last push to upstream.
    
    Returns:
        Tuple of (source_description, list_of_subjects)
    """
    upstream = get_upstream_ref()
    if upstream:
        log_cmd = f"git log {upstream}..HEAD --pretty=format:%s"
        source_desc = f"commits since last push ({upstream}..HEAD)"
    else:
        log_cmd = f"git log -{fallback_count} --pretty=format:%s"
        source_desc = f"last {fallback_count} commits (no upstream found)"

    log_output = run(log_cmd)
    lines = [l for l in log_output.splitlines() if l.strip()]
    return source_desc, lines


def get_unpushed_commits(max_count=20):
    """
    Get unpushed commits with their details.
    
    Returns:
        Tuple of (source_description, list_of_commit_dicts)
    """
    log_format = "%H%x1f%s%x1f%b%x1e"
    upstream = get_upstream_ref()
    if upstream:
        rev_range = f"{upstream}..HEAD"
        source_desc = f"unpushed commits ({rev_range})"
        log_cmd = f'git log --reverse --first-parent --format="{log_format}" {rev_range}'
    else:
        source_desc = f"last {max_count} commits (no upstream found)"
        # Use -n instead of HEAD~N..HEAD so this works even for short histories.
        log_cmd = f'git log --reverse --first-parent -n {max_count} --format="{log_format}" HEAD'
    raw = run(log_cmd)
    commits = []
    for record in raw.split("\x1e"):
        if not record.strip():
            continue
        record = record.strip()
        parts = record.split("\x1f")
        if len(parts) < 2:
            continue
        sha = parts[0]
        subj = parts[1]
        body = parts[2] if len(parts) > 2 else ""
        commits.append({"sha": sha, "subject": subj.strip(), "body": body.strip()})
    return source_desc, commits


def get_commits_for_fix(max_count=20, force=False):
    """
    Get commits with full diffs for the fix command.
    
    Args:
        max_count: Maximum number of commits to retrieve
        force: If True, include pushed commits as well
    
    Returns:
        Tuple of (source_description, list_of_commit_dicts_with_diffs)
    """
    upstream = get_upstream_ref()
    log_format = "%H%x1f%s%x1f%b%x1e"

    if upstream and not force:
        rev_range = f"{upstream}..HEAD"
        source_desc = f"unpushed commits ({rev_range})"
        log_cmd = f'git log --reverse --first-parent --format="{log_format}" {rev_range}'
    else:
        source_desc = f"last {max_count} commits"
        if force and upstream:
            source_desc += " (force enabled)"
        elif not upstream:
            source_desc += " (no upstream found)"
        log_cmd = f'git log --reverse --first-parent -n {max_count} --format="{log_format}" HEAD'

    raw = run(log_cmd)
    commits = []
    for record in raw.split("\x1e"):
        if not record.strip():
            continue
        record = record.strip()
        parts = record.split("\x1f")
        if len(parts) < 2:
            click.secho(f"Skipping malformed commit record: {record}", fg="yellow")
            continue
        sha = parts[0].strip()
        subj = parts[1].strip()
        body = parts[2].strip() if len(parts) > 2 else ""

        message = subj
        if body:
            message = f"{message}\n\n{body}"

        try:
            diff = run(f"git show {sha} --format=format:")
        except subprocess.CalledProcessError as exc:
            decoded = exc.output.decode("utf-8", errors="ignore") if isinstance(exc.output, (bytes, bytearray)) else str(exc.output or "")
            click.secho(f"Skipping commit {sha}: git show failed", fg="yellow")
            if decoded:
                click.echo(decoded)
            continue

        commits.append({"hash": sha, "message": message, "diff": diff})
    return source_desc, commits


def apply_fix_plan(commits, plan):
    """
    Apply the AI rewrite plan to the current commit range.

    Supported scenarios:
    - mergeStrategy == "drop" and no rewritten commits: drop the range.
    - mergeStrategy == "squash" OR single rewritten commit: squash range to one commit.
    - Equal commit counts: rewrite commit messages (same order/trees).

    Unsupported (will abort): split/reorder where counts differ.
    """
    status = run("git status --porcelain")
    if status.strip():
        raise RuntimeError("Working tree not clean; commit or stash changes first.")

    rewritten = plan.get("rewrittenCommits") or []
    merge_strategy = (plan.get("mergeStrategy") or "").strip().lower()

    if not commits:
        return "noop"

    first_sha = commits[0]["hash"]
    parents_raw = run(f"git show -s --format=%P {first_sha}")
    parents = parents_raw.split()
    base_parent = parents[0] if parents else None

    # Refuse to rewrite merge history
    upstream = get_upstream_ref()
    if upstream:
        rev_range = f"{upstream}..HEAD"
    else:
        rev_range = f"{base_parent or ''}..{commits[-1]['hash']}"
    merges = run(f"git rev-list --merges --first-parent {rev_range}")
    if merges.strip():
        raise RuntimeError("History contains merges; linear rewrite only. Aborting.")

    def _commit_tree(tree_sha, parent_sha, title, body):
        if not title or not title.strip():
            raise RuntimeError("Rewrite plan provided an empty commit title.")
        cmd_parts = ["git", "commit-tree", tree_sha]
        if parent_sha:
            cmd_parts.extend(["-p", parent_sha])
        cmd_parts.extend(["-m", shlex.quote(title.strip())])
        if body and body.strip():
            cmd_parts.extend(["-m", shlex.quote(body.strip())])
        return run(" ".join(cmd_parts))

    # Handle drop
    if merge_strategy == "drop" and not rewritten:
        if not base_parent:
            raise RuntimeError("Cannot drop range without a parent commit.")
        run(f"git reset --hard {base_parent}")
        return "dropped"

    # Handle squash (or single rewrite entry)
    if merge_strategy == "squash" or len(rewritten) == 1:
        entry = rewritten[0] if rewritten else {"title": "Rewrite commits", "description": ""}
        title = entry.get("title") or "Rewrite commits"
        body = entry.get("description") or ""
        tree_sha = run("git show -s --format=%T HEAD")
        new_sha = _commit_tree(tree_sha, base_parent, title, body)
        run(f"git reset --hard {new_sha}")
        return "squashed"

    # If counts differ, we cannot safely rewrite (split/reorder unsupported).
    if len(rewritten) != len(commits):
        raise RuntimeError(
            f"Rewrite plan has {len(rewritten)} commits but history has {len(commits)}; "
            "split/reorder not supported automatically. Please rerun with a compatible plan."
        )

    # Rewrite messages with same trees/order
    last_new = base_parent
    for entry, orig in zip(rewritten, commits):
        title = (entry.get("title") or "").strip()
        body = (entry.get("description") or "").strip()
        tree_sha = run(f"git show -s --format=%T {orig['hash']}")
        last_new = _commit_tree(tree_sha, last_new, title, body)

    if not last_new:
        raise RuntimeError("Failed to compute new commit chain.")

    run(f"git reset --hard {last_new}")
    return "rewritten"


def apply_commits(commit_list):
    """
    Apply a list of commit dictionaries by staging files and committing.
    
    Each commit dict should have: type, title, body (optional), files
    """
    from .diff import get_diff
    from ..ui import display_spinning_animation
    
    committed_subjects = []
    for commit in commit_list:
        files = commit.get("files", [])
        if not files:
            continue

        subject = lint_commit_dict(commit)
        body = commit.get("body") or ""

        stage_targets = []
        skipped_missing = []
        for f in files:
            if os.path.exists(f):
                stage_targets.append(f)
            elif is_tracked(f):
                # Track deletion
                stage_targets.append(f)
            else:
                skipped_missing.append(f)

        if skipped_missing:
            click.secho(
                f"Skipping untracked missing files: {', '.join(skipped_missing)}",
                fg="yellow",
            )

        if not stage_targets:
            click.secho(
                f"No valid files to stage for commit '{subject}'; skipping.",
                fg="yellow",
            )
            continue

        try:
            # Use -A to ensure deletions are staged too; plain git add errors on removed paths
            run(["git", "add", "-A", "--", *stage_targets])
        except subprocess.CalledProcessError as exc:
            err_out = exc.output
            decoded = err_out.decode("utf-8", errors="ignore") if isinstance(err_out, (bytes, bytearray)) else str(err_out or "")
            click.secho(
                f"Staging failed for files: {', '.join(stage_targets)}; skipping this commit.",
                fg="red",
            )
            if decoded:
                click.echo(decoded)
            continue

        cmd = ["git", "commit", "-m", subject]
        if body and body.strip():
            cmd.extend(["-m", body])

        try:
            run(cmd)
            committed_subjects.append(subject)
        except subprocess.CalledProcessError as exc:
            err_out = exc.output
            decoded = err_out.decode("utf-8", errors="ignore") if isinstance(err_out, (bytes, bytearray)) else str(err_out or "")
            click.secho("Commit failed; skipping remaining steps for this commit.", fg="red")
            if decoded:
                click.echo(decoded)

    if committed_subjects:
        click.secho(f"✔ Committed: {', '.join(committed_subjects)}", fg="green", bold=True)
        # Show newest-first commits since last push so the just-added commit is on top
        source_desc, commits = get_commits_since_push()
        divider = click.style("─" * 48, fg="blue")
        click.echo(divider)
        click.secho(" Commit log (newest first) ", fg="cyan", bold=True, nl=False)
        click.echo()
        click.echo(f"Source: {source_desc}")
        if commits:
            pad = len(str(len(commits)))
            for idx, csubj in enumerate(commits, 1):
                click.echo(f"  {idx:>{pad}}. {csubj}")
        else:
            click.echo("  (none)")
        click.echo(divider)


def rewrite_commits(amendments, allow_dirty=False):
    """
    Rewrite commit messages for a list of amendments.
    
    Args:
        amendments: List of dicts with sha, subject, body
        allow_dirty: Allow running with dirty working tree
    
    Returns:
        The new HEAD sha, or None if no amendments
    """
    status = run("git status --porcelain")
    if status.strip() and not allow_dirty:
        raise RuntimeError("Working tree not clean; commit or stash before rewriting, or pass allow_dirty=True")

    if not amendments:
        return None

    first_sha = amendments[0]["sha"]
    parents_raw = run(f"git show -s --format=%P {first_sha}")
    parents = parents_raw.split()
    base_parent = parents[0] if parents else None

    last_new = base_parent
    for entry in amendments:
        sha = entry["sha"]
        subject = entry.get("subject", "").strip()
        body = (entry.get("body") or "").strip()

        tree = run(f"git show -s --format=%T {sha}")
        cmd_parts = ["git", "commit-tree", tree]
        if last_new:
            cmd_parts.extend(["-p", last_new])
        cmd_parts.extend(["-m", shlex.quote(subject)])
        if body:
            cmd_parts.extend(["-m", shlex.quote(body)])
        new_sha = run(" ".join(cmd_parts))
        last_new = new_sha

    if not last_new:
        raise RuntimeError("Failed to compute new commit chain.")

    run(f"git reset --hard {last_new}")
    return last_new
