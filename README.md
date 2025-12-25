# auto-git

This is a simple tool I created and use to automatically create commit messages based off my current work tree.

## Obvious Disclaimer

AI can make mistakes. Don't use this for your missile software.

## Installation

### Requirements

- Python 3.11 or newer

### Install

```bash
uv sync --all-groups
```

### Set An OpenAI API Key

```bash
# .env
OPEN_AI_API_KEY=<your_key_here>
```

### CLI install (optional)

To install the `auto-git` command globally as a uv tool:

```bash
uv tool install --editable .
```

To uninstall:

```bash
uv tool uninstall auto-git
```

## CLI

Use via `uv run auto-git <command>` (recommended), or after `uv tool install`, `auto-git <command>`.

### Commands

- `generate` — Plan commits from current changes and print the JSON plan. Options: `--staged`, `--unstaged`, `--untracked` (defaults to staged+unstaged if none provided).
- `commit` — Plan and apply commits. Options: same inclusion flags as `generate`, plus `--dry-run` to preview commits/diff without writing history.
- `amend_unpushed` — Rewrite unpushed commits with improved messages. Options: `--max-count` (default 20) for fallback range, `--dry-run` to preview only, `--allow-dirty` to bypass clean-tree requirement. Aborts if history has merges.
- `fix` — Request a rewritten commit history (JSON only) for the local branch. Includes only unpushed commits unless `--force` is used. Options: `--max-count` (default 20) for fallback/force mode, `--force` to allow including pushed commits.
- `status` — Show staged and unstaged files (wrapper around git diff name-only).
- `lint` — Lint commit subjects since upstream (or last `count`, default 10). Prints errors or a pass summary.
- `watch` — Watch the repo for changes, stage everything, have AI split into commits, and apply them. Option: `--interval` seconds for the watcher loop (default 60). Ctrl+C stops cleanly.

### Examples

```bash
# Preview proposed commits and diff (no writes)
uv run auto-git commit --dry-run --untracked

# Apply commits for staged + unstaged changes (default)
uv run auto-git commit

# Just get the commit plan as JSON
uv run auto-git generate --unstaged

# Rewrite unpushed commits after previewing
uv run auto-git amend_unpushed --dry-run
uv run auto-git amend_unpushed --allow-dirty
```

## Testing

Run the test suite with:

```
uv run pytest
```
