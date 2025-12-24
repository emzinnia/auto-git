# auto-git

Update readme test.

This is a simple tool I created and use to automatically create commit messages based off my current work tree.

## Obvious Disclaimer

AI can make mistakes. Don't use this for your missile software.

## Installation

### Requirements

- Python 3.8 or newer

### Install Python dependencies

```
pip install -r requirements.txt
```

### Set An OpenAI API Key

```bash
# .env
OPEN_AI_API_KEY=<your_key_here>
```

### CLI install (optional, requires sudo)

To install the `auto-git` command globally (for all users):

```
sudo make install
```

This will symlink `auto_git.py` to `/usr/local/bin/auto-git` and make it executable.  
Now you can run `auto-git` from anywhere.

To uninstall the CLI:

```
sudo make uninstall
```

## CLI

Use via `python auto_git.py <command>` or, after `make install`, `auto-git <command>`.

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
auto-git commit --dry-run --untracked

# Apply commits for staged + unstaged changes (default)
auto-git commit

# Just get the commit plan as JSON
auto-git generate --unstaged

# Rewrite unpushed commits after previewing
auto-git amend_unpushed --dry-run
auto-git amend_unpushed --allow-dirty
```

## Testing

Run the test suite with:

```
pytest
```
