from types import SimpleNamespace

import pytest

import auto_git as ag


def test_lint_commit_dict_valid():
    subject = ag.lint_commit_dict(
        {"type": "feat", "title": "add thing", "body": "desc", "files": ["a.py"]}
    )
    assert subject == "feat: add thing"


def test_lint_commit_dict_invalid_type():
    with pytest.raises(ValueError):
        ag.lint_commit_dict({"type": "oops", "title": "bad", "files": ["a.py"]})


def test_lint_commit_dict_requires_files():
    with pytest.raises(ValueError):
        ag.lint_commit_dict({"type": "feat", "title": "missing files", "files": []})


def test_lint_git_commit_subject_validation():
    ag.lint_git_commit_subject("feat: ok subject")
    with pytest.raises(ValueError):
        ag.lint_git_commit_subject("bad subject")


def test_parse_json_from_openai_response_handles_fence():
    raw = "Response:\\n```json\\n[{\"key\": \"value\"}]\\n```"
    parsed = ag.parse_json_from_openai_response(raw)
    assert parsed == [{"key": "value"}]


def test_format_commit_preview():
    preview = ag.format_commit_preview(
        [
            {"type": "feat", "title": "add api", "body": "desc", "files": ["a.py"]},
            {"type": "fix", "title": "patch bug", "files": ["b.py"]},
        ]
    )
    assert "1. feat: add api" in preview
    assert "files: a.py" in preview
    assert "2. fix: patch bug" in preview


@pytest.mark.parametrize(
    "remote, expected",
    [
        ("https://github.com/example/repo.git", "example/repo"),
        ("git@github.com:example/repo.git", "example/repo"),
        ("ssh://git@github.com/example/repo", "github.com/example/repo"),
    ],
)
def test_get_origin_repo_slug(monkeypatch, remote, expected):
    monkeypatch.setattr(ag, "run", lambda cmd: remote)
    assert ag.get_origin_repo_slug() == expected


def test_get_diff_commands():
    diff_cmds = ag.get_diff(["a.py", "b.py"], staged=True, unstaged=True)
    assert "git diff --cached -- a.py b.py" in diff_cmds
    assert "git diff -- a.py b.py" in diff_cmds


def test_change_handler_ignores_git(monkeypatch, tmp_path):
    calls = []
    handler = ag.ChangeHandler(ignore_dirs=[".git"])
    monkeypatch.setattr(ag, "is_git_ignored", lambda path: True)
    monkeypatch.setattr(ag, "run", lambda cmd: calls.append(cmd))
    monkeypatch.setattr(ag, "display_spinning_animation", lambda *a, **k: None)
    event = SimpleNamespace(src_path=str(tmp_path / ".git" / "config"))
    handler.on_any_event(event)
    assert calls == []


def test_change_handler_stages_when_not_ignored(monkeypatch, tmp_path):
    calls = []
    handler = ag.ChangeHandler(ignore_dirs=[], status_cooldown=0)
    monkeypatch.setattr(ag, "is_git_ignored", lambda path: False)
    monkeypatch.setattr(ag, "run", lambda cmd: calls.append(cmd))
    monkeypatch.setattr(ag, "display_spinning_animation", lambda *a, **k: None)
    monkeypatch.setattr(
        ag,
        "get_changed_files",
        lambda staged=False, unstaged=False, untracked=False, untracked_files=None: [],
    )
    event = SimpleNamespace(src_path=str(tmp_path / "file.py"))
    handler.on_any_event(event)
    assert any("git add -A" in c for c in calls)


def test_change_handler_debounces_with_interval(monkeypatch, tmp_path):
    calls = []
    scheduled = []

    class FakeTimer:
        def __init__(self, interval, func):
            self.interval = interval
            self.func = func
            self._alive = False
            self.daemon = False

        def start(self):
            self._alive = True
            scheduled.append(self)

        def is_alive(self):
            return self._alive

    now = [100.0]

    def clock():
        return now[0]

    handler = ag.ChangeHandler(
        ignore_dirs=[],
        status_cooldown=0,
        interval_seconds=10,
        clock=clock,
        timer_factory=FakeTimer,
    )
    monkeypatch.setattr(ag, "is_git_ignored", lambda path: False)
    monkeypatch.setattr(ag, "run", lambda cmd: calls.append(cmd))
    monkeypatch.setattr(ag, "display_spinning_animation", lambda *a, **k: None)
    monkeypatch.setattr(
        ag,
        "get_changed_files",
        lambda staged=False, unstaged=False, untracked=False, untracked_files=None: [],
    )

    event = SimpleNamespace(src_path=str(tmp_path / "file.py"))
    handler.on_any_event(event)
    handler.on_any_event(event)  # should coalesce into same scheduled run

    assert not any("git add -A" in c for c in calls)
    assert len(scheduled) == 1
    assert int(scheduled[0].interval) == 10

    # Fire the scheduled timer after the interval.
    now[0] = 111.0
    scheduled[0].func()
    assert any("git add -A" in c for c in calls)

