"""Prompt templates for AI interactions."""

from textwrap import dedent

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

- **Title**: ≤72 characters, imperative mood ("Add X", "Fix Y")
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
* Do **not** hallucinate or make up information. It should all be based on the diffs provided.
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


COMMIT_GENERATION_PROMPT = dedent("""
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
       - If the feature does not yet feel complete, ignore it and do not include it in the commit
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


AMENDMENT_PROMPT = dedent("""
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
    {commits}
""")
