"""CLI commands and entry point."""

import json
import signal
import threading

import click
from watchdog.observers import Observer

from .config import __version__
from .git import (
    apply_commits,
    apply_fix_plan,
    get_changed_files,
    get_commits_for_fix,
    get_commits_since_push,
    get_diff,
    get_unpushed_commits,
    get_untracked_files,
    get_upstream_ref,
    rewrite_commits,
    run,
)
from .ui import display_spinning_animation, format_commit_preview
from .validation import lint_git_commit_subject
from .watcher import ChangeHandler


@click.group()
@click.version_option(version=__version__)
def cli():
    """Auto-git: AI-powered git commit automation."""
    pass


@cli.command()
@click.option("--unstaged", is_flag=True, help="Include unstaged changes")
@click.option("--staged", is_flag=True, help="Include staged changes")
@click.option("--untracked", is_flag=True, help="Include untracked files")
def generate(staged, unstaged, untracked):
    """Generate commit messages without committing."""
    import auto_git as ag

    if not (staged or unstaged):
        staged = unstaged = True

    untracked_files = get_untracked_files() if untracked else []
    files = get_changed_files(
        staged=staged,
        unstaged=unstaged,
        untracked=untracked,
        untracked_files=untracked_files,
    )
    if not files:
        click.echo("No changed files found")
        return

    diff = get_diff(
        files,
        staged=staged,
        unstaged=unstaged,
        untracked_files=untracked_files,
    )
    commits = ag.ask_openai_for_commits(files, diff)

    click.echo(json.dumps(commits, indent=2))


@cli.command()
@click.option("--unstaged", is_flag=True, help="Include unstaged changes")
@click.option("--staged", is_flag=True, help="Include staged changes")
@click.option("--untracked", is_flag=True, help="Include untracked files")
@click.option("--dry-run", is_flag=True, help="Preview commits and diff without committing")
def commit(staged, unstaged, untracked, dry_run):
    """Generate and apply commits."""
    import auto_git as ag

    if not (staged or unstaged):
        staged = unstaged = True

    untracked_files = get_untracked_files() if untracked else []
    files = get_changed_files(
        staged=staged,
        unstaged=unstaged,
        untracked=untracked,
        untracked_files=untracked_files,
    )
    if not files:
        click.echo("No changed files found")
        return

    diff = get_diff(
        files,
        staged=staged,
        unstaged=unstaged,
        untracked_files=untracked_files,
    )
    commits = ag.ask_openai_for_commits(files, diff)

    click.echo(json.dumps(commits, indent=2))
    if dry_run:
        click.secho("Dry run: planned commits", fg="yellow")
        preview = format_commit_preview(commits)
        if preview:
            click.echo(preview)
        if diff:
            click.secho("\nDiff used for planning:", fg="yellow")
            click.echo(diff)
        return

    apply_commits(commits)


@cli.command(name="amend_unpushed")
@click.option("--max-count", default=20, help="If no upstream, how many last commits to consider")
@click.option("--dry-run", is_flag=True, help="Preview amendments without rewriting")
@click.option("--allow-dirty", is_flag=True, help="Allow running with a dirty working tree")
def amend_unpushed(max_count, dry_run, allow_dirty):
    """Amend unpushed commit messages using AI suggestions."""
    import auto_git as ag

    source_desc, commits = get_unpushed_commits(max_count=max_count)
    if not commits:
        click.echo("No commits to amend.")
        return

    click.echo(f"Commits to consider ({source_desc}):")
    for c in commits:
        click.echo(f"  - {c['sha'][:7]} {c['subject']}")

    amendments = ag.ask_openai_for_amendments(commits)

    amend_map = {a["sha"]: a for a in amendments}
    amendments_sorted = []
    for c in commits:
        if c["sha"] in amend_map:
            amendments_sorted.append(amend_map[c["sha"]])
        else:
            click.secho(f"No amendment returned for {c['sha']}; aborting.", fg="red")
            return

    click.secho("\nProposed amendments:", fg="yellow")
    for a in amendments_sorted:
        body = (a.get("body") or "").strip()
        click.echo(f"- {a['sha'][:7]} -> {a['subject']}")
        if body:
            click.echo(f"  body: {body}")

    if dry_run:
        click.secho("\nDry run only; no changes applied.", fg="yellow")
        return

    # Refuse to rewrite merge history
    upstream = get_upstream_ref()
    if upstream:
        rev_range = f"{upstream}..HEAD"
    else:
        first_parent = run(f"git show -s --format=%P {commits[0]['sha']}").split()
        base = first_parent[0] if first_parent else ""
        rev_range = f"{base}..{commits[-1]['sha']}"

    merges = run(f"git rev-list --merges --first-parent {rev_range}")
    if merges.strip():
        click.secho("History contains merges; linear rewrite only. Aborting.", fg="red")
        return

    try:
        rewrite_commits(amendments_sorted, allow_dirty=allow_dirty)
        click.secho("Amendments applied. History rewritten.", fg="green", bold=True)
        click.echo("Remember to push with --force-with-lease to update remote history.")
    except Exception as exc:  # noqa: BLE001
        click.secho(f"Amend failed: {exc}", fg="red")


# Backwards/ergonomic alias (Click normally converts underscores to hyphens).
@cli.command(name="amend-unpushed")
@click.option("--max-count", default=20, help="If no upstream, how many last commits to consider")
@click.option("--dry-run", is_flag=True, help="Preview amendments without rewriting")
@click.option("--allow-dirty", is_flag=True, help="Allow running with a dirty working tree")
def amend_unpushed_alias(max_count, dry_run, allow_dirty):
    """Alias for `amend_unpushed` (same behavior)."""
    return amend_unpushed(max_count=max_count, dry_run=dry_run, allow_dirty=allow_dirty)


@cli.command()
@click.option("--force", is_flag=True, help="Include pushed commits as well (limits to last N).")
@click.option(
    "--max-count",
    default=20,
    show_default=True,
    type=int,
    help="Maximum commits to include when no upstream or when forcing.",
)
def fix(force, max_count):
    """Ask AI for a rewritten commit plan and apply it."""
    import auto_git as ag

    _, commits = get_commits_for_fix(max_count=max_count, force=force)
    if not commits:
        click.echo("No commits to process.")
        return

    if not force and not get_upstream_ref():
        click.secho(
            f"No upstream detected; using {len(commits)} commit(s) from local history.",
            fg="yellow",
            err=True,
        )
    if force and get_upstream_ref():
        click.secho(
            "Force enabled; including pushed commits from local history.",
            fg="yellow",
            err=True,
        )

    try:
        rewrite_plan = ag.ask_openai_for_fix(commits)
    except Exception as exc:  # noqa: BLE001
        click.secho(f"Failed to get rewrite plan: {exc}", fg="red")
        return

    click.echo(json.dumps(rewrite_plan, indent=2))

    try:
        result = apply_fix_plan(commits, rewrite_plan)
    except Exception as exc:  # noqa: BLE001
        click.secho(f"Failed to apply rewrite plan: {exc}", fg="red")
        return

    click.secho(f"History updated ({result}).", fg="green", bold=True)
    click.echo(
        "Remember to push with --force-with-lease if you had pushed these commits previously."
    )


@cli.command()
def status():
    """Show staged and unstaged changes."""
    click.echo("Staged:")
    click.echo(run("git diff --cached --name-only") or "(none)")
    click.echo("\nUnstaged:")
    click.echo(run("git diff --name-only") or "(none)")


@cli.command()
@click.argument("count", required=False, default=10)
def lint(count):
    """Lint recent commit messages against Conventional Commits format."""
    source_desc, lines = get_commits_since_push(fallback_count=count)

    click.echo(f"Commits inspected: {source_desc}")
    if lines:
        for subj in lines:
            click.echo(f"  - {subj}")
    else:
        click.echo("  (none)")
        return

    errors = []
    for subj in lines:
        try:
            lint_git_commit_subject(subj)
        except ValueError as e:
            errors.append(f"{subj}: {e}")

    if errors:
        click.echo("\nErrors:")
        for err in errors:
            click.echo(f"  - {err}")
    else:
        click.echo(f"Last {len(lines)} commits pass lint")


@cli.command()
@click.option(
    "--interval",
    default=300,
    show_default=True,
    type=int,
    help="Polling interval in seconds (default is 5 minutes)",
)
def watch(interval):
    """Watch for file changes and auto-commit."""
    display_spinning_animation()
    stop_event = threading.Event()
    interval_seconds = max(1, interval)
    event_handler = ChangeHandler(
        ignore_dirs=[".git"],
        stop_event=stop_event,
        interval_seconds=interval_seconds,
    )
    observer = Observer()
    observer.schedule(event_handler, path=".", recursive=True)
    observer.start()

    def _handle_signal(signum, frame):
        if not stop_event.is_set():
            click.echo("\nStopping watch...")
            stop_event.set()
            observer.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    for sig_name in ("SIGTERM", "SIGQUIT"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            signal.signal(sig, _handle_signal)

    try:
        # Use stop_event.wait so Ctrl+C/signal stops promptly without waiting full interval
        while not stop_event.is_set():
            stop_event.wait(interval_seconds)
    except KeyboardInterrupt:
        _handle_signal(signal.SIGINT, None)
    finally:
        observer.stop()
        observer.join(timeout=5)
        if observer.is_alive():
            click.echo("Watcher thread did not exit cleanly; forcing shutdown.", err=True)
        else:
            click.echo("Watch stopped")


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
