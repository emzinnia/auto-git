"""AI commit generation and parsing."""

import json

from ..config import OPENAI_MODEL_COMMITS
from ..ui import display_spinning_animation
from ..validation import lint_commit_dict, lint_git_commit_subject
from .client import get_openai_client, parse_json_from_openai_response
from .prompts import AMENDMENT_PROMPT, COMMIT_GENERATION_PROMPT, FIX_PROMPT_INSTRUCTIONS


def ask_openai_for_commits(files, diff):
    """
    Ask OpenAI to generate commit messages based on files and diff.
    
    Args:
        files: List of file paths
        diff: Diff string
        
    Returns:
        List of commit dictionaries
    """
    client = get_openai_client()
    display_spinning_animation("Consulting our AI overlords...")

    prompt = COMMIT_GENERATION_PROMPT.format(files=files, diff=diff)

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
    """
    Ask OpenAI to propose amendments for existing commits.
    
    Args:
        commits: List of commit dictionaries with sha, subject, body
        
    Returns:
        List of amendment dictionaries
    """
    client = get_openai_client()
    prompt = AMENDMENT_PROMPT.format(commits=json.dumps(commits, indent=2))

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
    """
    Ask OpenAI for a rewritten commit plan.
    
    Args:
        commits: List of commit dictionaries with hash, message, diff
        
    Returns:
        Rewrite plan dictionary
    """
    client = get_openai_client()
    prompt = f"{FIX_PROMPT_INSTRUCTIONS}\n\nCommits (oldest to newest):\n{json.dumps(commits, indent=2)}"

    response = client.responses.create(model=OPENAI_MODEL_COMMITS, input=prompt)
    raw_text = response.output_text
    return parse_json_from_openai_response(raw_text)
