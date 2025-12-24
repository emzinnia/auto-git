"""File system watcher for automatic commits."""

import time

from watchdog.events import FileSystemEventHandler

class ChangeHandler(FileSystemEventHandler):
    """Handler for file system change events that triggers AI commits."""
    
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
        # Import lazily to avoid hard-binding references, so tests can monkeypatch
        # `auto_git.display_spinning_animation`.
        import auto_git as ag

        ag.display_spinning_animation(message)

    def on_any_event(self, event):
        import os
        import auto_git as ag
        
        if self.stop_event and self.stop_event.is_set():
            return
        rel_path = os.path.relpath(event.src_path, ".")
        for d in self.ignore_dirs:
            if rel_path.startswith(d):
                return
        if ag.is_git_ignored(event.src_path):
            return
        self._show_status("Checking for changes...")
        # Stage everything (we then split by AI into multiple commits)
        ag.run("git add -A")

        files = ag.get_changed_files(staged=True, unstaged=False)
        if not files:
            self._show_status("No changes found yet...")
            return

        diff = ag.get_diff(files, staged=True, unstaged=False)
        commits = ag.ask_openai_for_commits(files, diff)
        ag.apply_commits(commits)
