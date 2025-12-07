import os
import re
import json
import time
import subprocess
import sys
import signal
import threading
from textwrap import dedent

import click
import openai
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

import warnings, urllib3
warnings.filterwarnings("ignore", category=urllib3.exceptions.NotOpenSSLWarning)

COMMIT_TYPES = {
    "feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert"
}

COMMIT_SUBJECT_RE = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\(.+\))?: .+$"
)

OPENAI_MODEL_COMMITS = "gpt-4.1"
OPENAI_MODEL_PR = "gpt-4.1-mini"

def run(cmd):
    return subprocess.check_output(cmd, shell=True).decode("utf-8").strip()

def get_upstream_ref():
    try:
        return run("git rev-parse --abbrev-ref --symbolic-full-name @{u}")
    except subprocess.CalledProcessError:
        return None

def get_commits_since_push(fallback_count=10):
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
    upstream = get_upstream_ref()
    if upstream:
        rev_range = f"{upstream}..HEAD"
        source_desc = f"unpushed commits ({rev_range})"
    else:
        rev_range = f"HEAD~{max_count}..HEAD"
        source_desc = f"last {max_count} commits (no upstream found)"

    log_format = "%H%x1f%s%x1f%b%x1e"
    raw = run(f'git log --reverse --first-parent --format="{log_format}" {rev_range}')
    commits = []
    for record in raw.split("\x1e"):
        if not record.strip():
            continue
        sha, subj, body = record.split("\x1f", 2)
        commits.append({"sha": sha, "subject": subj.strip(), "body": body.strip()})
    return source_desc, commits

def is_tracked(path):
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0

def is_git_ignored(path):
    rel_path = os.path.relpath(path, ".")
    if rel_path.startswith(".git"):
        return True
    result = subprocess.run(
        ["git", "check-ignore", "-q", rel_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def get_untracked_files():
    out = run("git ls-files --others --exclude-standard")
    if not out:
        return []
    return [f for f in out.splitlines() if f.strip()]


def get_changed_files(staged=False, unstaged=False, untracked=False, untracked_files=None):
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
    diff_parts = []

    if staged and files:
        diff_parts.append(f"git diff --cached -- " + " ".join(files))
    if unstaged and files:
        diff_parts.append(f"git diff -- " + " ".join(files))
    if untracked_files:
        for f in untracked_files:
            diff_parts.append(f"git diff --no-index -- /dev/null {f}")

    return "\n".join(part for part in diff_parts if part)

def get_current_branch():
    return run("git rev-parse --abbrev-ref HEAD")

def get_origin_repo_slug():
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

def display_spinning_animation(message="Watching for changes... (Ctrl+C to stop)"):
    animation = "|/-\\"
    spin_cycles = 24
    for i in range(spin_cycles):
        frame = animation[i % len(animation)]
        click.echo(f"\r{message} {frame}", nl=False)
        time.sleep(0.05)
    click.echo(f"\r{message}    \n")

def lint_commit_dict(commit):
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
    if not COMMIT_SUBJECT_RE.match(subject):
        raise ValueError("Commit subject must match the format: <type>(<scope>): <subject>")


def get_openai_client():
    api_key = os.environ.get("OPEN_AI_API_KEY")

    if not api_key:
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as env_file:
                for line in env_file:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    if key.strip() == "OPEN_AI_API_KEY":
                        api_key = value.strip().strip('"').strip("'")
                        break

    if not api_key:
        raise RuntimeError("OPEN_AI_API_KEY is not set in the environment or .env file")

    return openai.OpenAI(api_key=api_key)

def format_commit_preview(commits):
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

def parse_json_from_openai_response(text):
    stripped = text.strip()

    if stripped.startswith("```"):
        stripped = stripped.strip("`")

    start = None
    for ch in ("[", "{"):
        idx = stripped.find(ch)
        if idx != -1:
            if start is None or idx < start:
                start = idx
    if start is not None:
        stripped = stripped[start:]

    return json.loads(stripped)

def ask_openai_for_commits(files, diff):
    client = get_openai_client()
    display_spinning_animation("Consulting our AI overlords...")

    prompt = dedent(f"""
        You are an AI that analyzes Git diffs and produces commit messages.

        FILES INVOLVED:
        {files}

        DIFF:
        ```
        {diff}
        ```

        TASKS:
        1. Group changes into one or multiple commits logically.
        2. For each commit:
           - Use Conventional Commits type: feat, fix, docs, style, refactor,
             perf, test, chore, build, or ci.
           - Provide a short title (<75 chars), without the type prefix.
           - Provide a longer body description (can be multi-line, markdown ok).
           - List which files belong to that commit.
        3. Output ONLY valid JSON in this structure:

        [
          {{
            "type": "feat|fix|docs|style|refactor|perf|test|chore|build|ci",
            "title": "Short descriptive title, no type prefix, use lowercase",
            "body": "Longer description of the change.",
            "files": ["file1.js", "file2.ts"]
          }}
        ]

        Do NOT add any commentary outside the JSON.
    """)

    response = client.responses.create(
        model=OPENAI_MODEL_COMMITS,
        input=prompt
    )

    raw_text = response.output_text
    commits = parse_json_from_openai_response(raw_text)

    # Lint all commits and build subject lines
    for c in commits:
        _ = lint_commit_dict(c)

    return commits

def ask_openai_for_amendments(commits):
    client = get_openai_client()
    prompt = dedent(f"""
        You are helping rewrite commit messages for a linear Git history.
        For each commit, propose a new Conventional Commit subject and optional body.
        Keep the same commit order; do not merge or split commits.

        Return JSON array like:
        [
          {{
            "sha": "<orig sha>",
            "subject": "feat: better subject",
            "body": "optional body"
          }}
        ]

        Commits (oldest first):
        {json.dumps(commits, indent=2)}
    """)

    response = client.responses.create(model=OPENAI_MODEL_COMMITS, input=prompt)
    raw_text = response.output_text
    amendments = parse_json_from_openai_response(raw_text)

    sha_set = {c["sha"] for c in commits}
    for a in amendments:
        sha = a.get("sha")
        if sha not in sha_set:
            raise ValueError(f"Amendment references unknown sha: {sha}")
        _ = lint_git_commit_subject(a.get("subject", ""))
    return amendments

def apply_commits(commit_list):
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
            run("git add -A -- " + " ".join(stage_targets))
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

        # Escape double-quotes in body to avoid shell issues
        safe_body = body.replace('"', '\\"')

        cmd = f'git commit -m "{subject}"'
        if safe_body.strip():
            cmd += f' -m "{safe_body}"'

        try:
            run(cmd)
            click.secho(f"✔ Committed: {subject}", fg="green", bold=True)
            # Show newest-first commits since last push so the just-added commit is on top
            source_desc, commits = get_commits_since_push()
            click.echo(f"Commits inspected: {source_desc}")
            if commits:
                for csubj in commits:
                    click.echo(f"  - {csubj}")
            else:
                click.echo("  (none)")
        except subprocess.CalledProcessError as exc:
            err_out = exc.output
            decoded = err_out.decode("utf-8", errors="ignore") if isinstance(err_out, (bytes, bytearray)) else str(err_out or "")
            click.secho("Commit failed; skipping remaining steps for this commit.", fg="red")
            if decoded:
                click.echo(decoded)


def rewrite_commits(amendments, allow_dirty=False):
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
        cmd_parts.extend(["-m", subject])
        if body:
            cmd_parts.extend(["-m", body])

        new_sha = run(" ".join(cmd_parts))
        last_new = new_sha

    if not last_new:
        raise RuntimeError("Failed to compute new commit chain.")

    run(f"git reset --hard {last_new}")
    return last_new


class ChangeHandler(FileSystemEventHandler):
    def __init__(self, ignore_dirs=None, stop_event=None):
        self.ignore_dirs = ignore_dirs or []
        self.stop_event = stop_event

    def on_any_event(self, event):
        if self.stop_event and self.stop_event.is_set():
            return
        rel_path = os.path.relpath(event.src_path, ".")
        for d in self.ignore_dirs:
            if rel_path.startswith(d):
                return
        if is_git_ignored(event.src_path):
            return

        display_spinning_animation("Checking for changes...")
        # Stage everything (we then split by AI into multiple commits)
        run("git add -A")

        files = get_changed_files(staged=True, unstaged=False)
        if not files:
            display_spinning_animation("No changes found yet...")
            return

        diff = get_diff(files, staged=True, unstaged=False)
        commits = ask_openai_for_commits(files, diff)
        apply_commits(commits)

@click.group()
def cli():
    pass

@cli.command()
@click.option("--unstaged", is_flag=True, help="Include unstaged changes")
@click.option("--staged", is_flag=True, help="Include staged changes")
@click.option("--untracked", is_flag=True, help="Include untracked files")
def generate(staged, unstaged, untracked):
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
    commits = ask_openai_for_commits(files, diff)
    
    click.echo(json.dumps(commits, indent=2))

@cli.command()
@click.option("--unstaged", is_flag=True, help="Include unstaged changes")
@click.option("--staged", is_flag=True, help="Include staged changes")
@click.option("--untracked", is_flag=True, help="Include untracked files")
@click.option("--dry-run", is_flag=True, help="Preview commits and diff without committing")
def commit(staged, unstaged, untracked, dry_run):
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
    commits = ask_openai_for_commits(files, diff)

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

@cli.command()
def status():
    click.echo("Staged:")
    click.echo(run("git diff --cached --name-only") or "(none)")
    click.echo("\nUnstaged:")
    click.echo(run("git diff --name-only") or "(none)")

@cli.command()
@click.argument("count", required=False, default=10)
def lint(count):
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
@click.option("--interval", default=60, help="Polling interval in seconds")
def watch(interval):
    display_spinning_animation()
    stop_event = threading.Event()
    event_handler = ChangeHandler(ignore_dirs=[".git"], stop_event=stop_event)
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
            stop_event.wait(interval)
    except KeyboardInterrupt:
        _handle_signal(signal.SIGINT, None)
    finally:
        observer.stop()
        observer.join(timeout=5)
        if observer.is_alive():
            click.echo("Watcher thread did not exit cleanly; forcing shutdown.", err=True)
        else:
            click.echo("Watch stopped")

if __name__ == "__main__":
    cli()