import os
import re
import json
import time
import subprocess
import sys
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
    print(f"Asking OpenAI for commits for files: {files}")

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

def apply_commits(commit_list):
    for commit in commit_list:
        files = commit.get("files", [])
        if not files:
            continue

        subject = lint_commit_dict(commit)
        body = commit.get("body") or ""

        run("git add " + " ".join(files))

        # Escape double-quotes in body to avoid shell issues
        safe_body = body.replace('"', '\\"')

        cmd = f'git commit -m "{subject}"'
        if safe_body.strip():
            cmd += f' -m "{safe_body}"'

        try:
            run(cmd)
            click.secho("Committed", fg="green")
            click.secho(f"{subject}")
        except subprocess.CalledProcessError as exc:
            err_out = exc.output
            decoded = err_out.decode("utf-8", errors="ignore") if isinstance(err_out, (bytes, bytearray)) else str(err_out or "")
            click.secho("Commit failed; skipping remaining steps for this commit.", fg="red")
            if decoded:
                click.echo(decoded)


class ChangeHandler(FileSystemEventHandler):
    def __init__(self, ignore_dirs=None):
        self.ignore_dirs = ignore_dirs or []

    def on_any_event(self, event):
        for d in self.ignore_dirs:
            if event.src_path.startswith(d):
                return

        click.echo("\nChange detected! Auto-generating commits...")
        # Stage everything (we then split by AI into multiple commits)
        run("git add -A")

        files = get_changed_files(staged=True, unstaged=False)
        if not files:
            click.echo("No staged changes after add -A; skipping.")
            return

        diff = get_diff(files, staged=True, unstaged=False)
        commits = ask_openai_for_commits(files, diff)
        apply_commits(commits)

# files = get_changed_files(staged=True, unstaged=True)
# print(files)
# print(get_current_branch())
# print(get_origin_repo_slug())

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
def commit(staged, unstaged, untracked):
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
    log_output = run(f"git log -{count} --pretty=format:%s")
    lines = [l for l in log_output.splitlines() if l.strip()]

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
    message = "Watching for changes... (Ctrl+C to stop)"
    animation = "|/-\\"
    spin_cycles = 24
    for i in range(spin_cycles):
        frame = animation[i % len(animation)]
        sys.stdout.write(f"\r{message} {frame}")
        sys.stdout.flush()
        time.sleep(0.05)
    sys.stdout.write(f"\r{message}    \n")
    sys.stdout.flush()

    event_handler = ChangeHandler(ignore_dirs=[".git"])
    observer = Observer()
    observer.schedule(event_handler, path=".", recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(interval)
    except KeyboardInterrupt:
        click.echo("\nStopping watch...")
        observer.stop()
        click.echo("Watch stopped")
    
    observer.join()

if __name__ == "__main__":
    cli()