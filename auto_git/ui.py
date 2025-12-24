"""Display utilities and UI helpers."""

import time

import click


def display_spinning_animation(message="Watching for changes... (Ctrl+C to stop)"):
    """Display a spinning animation with a message."""
    animation = "|/-\\"
    spin_cycles = 24
    for i in range(spin_cycles):
        frame = animation[i % len(animation)]
        click.echo(f"\r{message} {frame}", nl=False)
        time.sleep(0.05)
    click.echo(f"\r{message}    \n")


def format_commit_preview(commits):
    """Format a list of commits for preview display."""
    lines = []
    for idx, c in enumerate(commits, start=1):
        ctype = c.get("type", "?")
        title = c.get("title", "").strip()
        body = (c.get("body") or "").strip()
        files = c.get("files") or []
        lines.append(f"{idx}. {ctype}: {title}")
        if body:
            lines.append(f"   body: {body}")
        if files:
            lines.append(f"   files: {', '.join(files)}")
    return "\n".join(lines)
