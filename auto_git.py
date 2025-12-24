import json
import os
import re
import shlex
import signal
import subprocess
import threading
import time
import warnings
from textwrap import dedent

import click
import openai
import urllib3
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

warnings.filterwarnings("ignore", category=urllib3.exceptions.NotOpenSSLWarning)

__version__ = "0.1.0"

COMMIT_TYPES = {
    "feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert"
}

COMMIT_SUBJECT_RE = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\(.+\))?: .+$"
)

OPENAI_MODEL_COMMITS = "gpt-4.1"
OPENAI_MODEL_PR = "gpt-4.1-mini"

FIX_PROMPT_INSTRUCTIONS = dedent("""
# Instructions for Rewriting a Local Git Commit Tree into Clean JSON

Analyze the **un-pushed local commit tree** and return a rewritten, improved commit history
in **JSON only** (no commentary).

You will receive an ordered list of commits (oldest → newest), each containing a hash,
message, and full diff.

---

## What You Must Do

### 1. Understand the Commit Series

- Interpret the diffs to infer *intent*, not just mechanical changes.
- Identify categories: feature, bugfix, refactor, styling, docs, infra.
- Detect noisy / meaningless commits (debug logs, accidental files, local undo commits).

### 2. Rewrite the Commit History

Produce a new commit history that is:

- **Clean** — each commit has a single purpose.
- **Logical** — flows in a coherent order.
- **Minimal** — contains no unnecessary commits.
- **Grouped by intent**, not by how the developer initially committed.

You may:

- **Squash** multiple commits into one if they represent one logical change.
- **Split** a commit if it mixes unrelated modifications.
- **Reorder** commits to make the story clearer.
- **Drop** commits that add no value or cancel each other out.

### 3. Generate High-Quality Commit Metadata

For each rewritten commit:

- **Title**: ≤72 characters, imperative mood (“Add X”, “Fix Y”)
- **Description**: optional, used only when necessary
- **Changes** array: summarize each file and classify the change type
- **Rationale**: why these changes belong together

### 4. Specify the Overall Merge Strategy

Choose one:
`squash`, `reorder`, `split`, `drop`
(You may use more than one but list the primary strategy.)

### 5. Output Strictly as JSON

Return only JSON matching this schema:

```json
{
  "rewrittenCommits": [
    {
      "title": "Concise commit title",
      "description": "Optional longer description",
      "changes": [
        {
          "file": "path/to/file",
          "summary": "Human-readable explanation of what changed",
          "type": "add|remove|modify|refactor|rename"
        }
      ],
      "rationale": "Why these changes logically belong in this commit"
    }
  ],
  "mergeStrategy": "squash|reorder|split|drop",
  "notes": "Optional additional recommendations"
}
```

### 6. Important Constraints

* Do **not** return Git commands.
* Do **not** reference AI tools or rewriting.
* Do **not** include any explanatory text outside the JSON.
* Output must represent the **final, cleaned commit tree**, not a one-to-one transformation.

---

## Final Output Template

Use this exact structure:

```json
{
  "rewrittenCommits": [
    {
      "title": "",
      "description": "",
      "changes": [
        {
          "file": "",
          "summary": "",
          "type": ""
        }
      ],
      "rationale": ""
    }
  ],
  "mergeStrategy": "",
  "notes": ""
}
```
""").strip()

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

def get_commits_since_push(fallback_count=10):
    upstream = get_upstream_ref()
    if upstream:
        log_cmd = f"git log {upstream}..HEAD --pretty=format:%s"
        source_desc = f"commits since last push ({upstream}..HEAD)"
    else:
        log_cmd = f"git log -{fallback_count} --pretty=format:%s"
        source_desc = f"last {fallback_count} commits (no upstream found)"

    log_output = run(log_cmd)
    lines = [line for line in log_output.splitlines() if line.strip()]
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

def get_commits_for_fix(max_count=20, force=False):
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
            err_out = exc.output
            if isinstance(err_out, (bytes, bytearray)):
                decoded = err_out.decode("utf-8", errors="ignore")
            else:
                decoded = str(err_out or "")
            click.secho(f"Skipping commit {sha}: git show failed", fg="yellow")
            if decoded:
                click.echo(decoded)
            continue

        commits.append({"hash": sha, "message": message, "diff": diff})
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
        diff_parts.append("git diff --cached -- " + " ".join(files))
    if unstaged and files:
        diff_parts.append("git diff -- " + " ".join(files))
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
           - Determine the type of commit based on the changes.
           - Fixes should be a fix type, not a feat type.
           - If the feature does not yet feel complete, ignore it and do not include it
             in the commit
        3. Properly determine the type of commit based on the changes.
            - feat: new feature or improvement
            - fix: bug fix
            - docs: documentation
            - style: code style
            - refactor: code refactor
            - perf: performance improvement
            - test: test improvement
            - chore: chore
            - build: build improvement
        4. Output ONLY valid JSON in this structure:

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

def ask_openai_for_fix(commits):
    client = get_openai_client()
    prompt = dedent(f"""
    {FIX_PROMPT_INSTRUCTIONS}

    Commits (oldest to newest):
    {json.dumps(commits, indent=2)}
    """)

    response = client.responses.create(model=OPENAI_MODEL_COMMITS, input=prompt)
    raw_text = response.output_text
    return parse_json_from_openai_response(raw_text)


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
    for entry, orig in zip(rewritten, commits, strict=True):
        title = (entry.get("title") or "").strip()
        body = (entry.get("description") or "").strip()
        tree_sha = run(f"git show -s --format=%T {orig['hash']}")
        last_new = _commit_tree(tree_sha, last_new, title, body)

    if not last_new:
        raise RuntimeError("Failed to compute new commit chain.")

    run(f"git reset --hard {last_new}")
    return "rewritten"

def apply_commits(commit_list):
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
            if isinstance(err_out, (bytes, bytearray)):
                decoded = err_out.decode("utf-8", errors="ignore")
            else:
                decoded = str(err_out or "")
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
            if isinstance(err_out, (bytes, bytearray)):
                decoded = err_out.decode("utf-8", errors="ignore")
            else:
                decoded = str(err_out or "")
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
    status = run("git status --porcelain")
    if status.strip() and not allow_dirty:
        raise RuntimeError(
            "Working tree not clean; commit or stash before rewriting, "
            "or pass allow_dirty=True"
        )

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


class ChangeHandler(FileSystemEventHandler):
    def __init__(self, ignore_dirs=None, stop_event=None, status_cooldown=5):
        self.ignore_dirs = ignore_dirs or []
        self.stop_event = stop_event
        self.status_cooldown = status_cooldown
        self._last_status_message = None
        self._last_status_time = 0

    def _show_status(self, message):
        now = time.time()
        if (
            message == self._last_status_message
            and (now - self._last_status_time) < self.status_cooldown
        ):
            return

        self._last_status_message = message
        self._last_status_time = now
        display_spinning_animation(message)

    def on_any_event(self, event):
        if self.stop_event and self.stop_event.is_set():
            return
        rel_path = os.path.relpath(event.src_path, ".")
        for d in self.ignore_dirs:
            if rel_path.startswith(d):
                return
        if is_git_ignored(event.src_path):
            return
        self._show_status("Checking for changes...")
        # Stage everything (we then split by AI into multiple commits)
        run("git add -A")

        files = get_changed_files(staged=True, unstaged=False)
        if not files:
            self._show_status("No changes found yet...")
            return

        diff = get_diff(files, staged=True, unstaged=False)
        commits = ask_openai_for_commits(files, diff)
        apply_commits(commits)

@click.group()
@click.version_option(version=__version__)
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
@click.option("--max-count", default=20, help="If no upstream, how many last commits to consider")
@click.option("--dry-run", is_flag=True, help="Preview amendments without rewriting")
@click.option("--allow-dirty", is_flag=True, help="Allow running with a dirty working tree")
def amend_unpushed(max_count, dry_run, allow_dirty):
    source_desc, commits = get_unpushed_commits(max_count=max_count)
    if not commits:
        click.echo("No commits to amend.")
        return

    click.echo(f"Commits to consider ({source_desc}):")
    for c in commits:
        click.echo(f"  - {c['sha'][:7]} {c['subject']}")

    amendments = ask_openai_for_amendments(commits)

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
    """
    Ask OpenAI for a rewritten commit plan for the local history and apply it.
    """
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
        rewrite_plan = ask_openai_for_fix(commits)
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
@click.option(
    "--interval",
    default=300,
    show_default=True,
    type=int,
    help="Polling interval in seconds (default is 5 minutes)",
)
def watch(interval):
    display_spinning_animation()
    stop_event = threading.Event()
    event_handler = ChangeHandler(ignore_dirs=[".git"], stop_event=stop_event)
    observer = Observer()
    observer.schedule(event_handler, path=".", recursive=True)
    observer.start()

    interval_seconds = max(1, interval)

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

if __name__ == "__main__":
    cli()
