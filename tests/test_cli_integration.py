import json
import subprocess

from click.testing import CliRunner

import auto_git as ag


def test_commit_dry_run(monkeypatch, tmp_git_repo, write_file):
    repo, git = tmp_git_repo
    write_file(repo, "file.txt", "hello")
    git("add file.txt")

    monkeypatch.chdir(repo)
    stub_commits = [
        {"type": "feat", "title": "add file", "body": "desc", "files": ["file.txt"]}
    ]
    monkeypatch.setattr(ag, "ask_openai_for_commits", lambda files, diff: stub_commits)

    runner = CliRunner()
    result = runner.invoke(ag.cli, ["commit", "--dry-run"])

    assert result.exit_code == 0
    assert '"title": "add file"' in result.output
    assert "Dry run: planned commits" in result.output


def test_generate_outputs_plan(monkeypatch, tmp_git_repo, write_file):
    repo, git = tmp_git_repo
    write_file(repo, "file.txt", "hello")
    git("add file.txt")

    monkeypatch.chdir(repo)
    stub_commits = [
        {"type": "feat", "title": "add file", "body": "desc", "files": ["file.txt"]}
    ]
    monkeypatch.setattr(ag, "ask_openai_for_commits", lambda files, diff: stub_commits)

    runner = CliRunner()
    result = runner.invoke(ag.cli, ["generate"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed[0]["title"] == "add file"


def test_amend_unpushed_dry_run(monkeypatch, tmp_git_repo, write_file):
    repo, git = tmp_git_repo
    write_file(repo, "file.txt", "first")
    git("add file.txt")
    git('commit -m "feat: first"')

    write_file(repo, "file.txt", "second")
    git("add file.txt")
    git('commit -m "feat: second"')

    # Capture SHAs for deterministic amendments
    log_output = subprocess.check_output(
        f"git -C {repo} log --pretty=format:%H --reverse", shell=True, text=True
    ).splitlines()
    amendments = [
        {"sha": log_output[0], "subject": "feat: first updated", "body": "body1"},
        {"sha": log_output[1], "subject": "feat: second updated", "body": "body2"},
    ]

    monkeypatch.chdir(repo)
    monkeypatch.setattr(ag, "ask_openai_for_amendments", lambda commits: amendments)

    runner = CliRunner()
    result = runner.invoke(ag.cli, ["amend_unpushed", "--dry-run"])

    assert result.exit_code == 0
    assert "Proposed amendments:" in result.output
    assert "first updated" in result.output
    assert "second updated" in result.output

