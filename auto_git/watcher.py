"""File system watcher for automatic commits."""

import threading
import time

from watchdog.events import FileSystemEventHandler


class ChangeHandler(FileSystemEventHandler):
    """Handler for file system change events that triggers AI commits."""

    def __init__(
        self,
        ignore_dirs=None,
        stop_event=None,
        status_cooldown=5,
        interval_seconds=0,
        clock=None,
        timer_factory=None,
    ):
        self.ignore_dirs = ignore_dirs or []
        self.stop_event = stop_event
        self.status_cooldown = status_cooldown
        self._last_status_message = None
        self._last_status_time = 0
        self.interval_seconds = max(0, int(interval_seconds or 0))

        # Injection points for deterministic tests.
        self._clock = clock or time.time
        self._timer_factory = timer_factory or threading.Timer

        # Debounce / coalescing state.
        self._lock = threading.Lock()
        self._pending = False
        self._processing = False
        self._timer = None
        self._last_run_time = 0.0
        self._next_run_time = None

    def _show_status(self, message):
        now = self._clock()
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

    def _schedule_locked(self, delay_seconds):
        """
        Schedule a processing run after `delay_seconds`.
        Must be called with `_lock` held.
        """
        if self.stop_event and self.stop_event.is_set():
            return
        if self._timer is not None and getattr(self._timer, "is_alive", lambda: False)():
            return
        t = self._timer_factory(max(0.0, float(delay_seconds)), self._process_pending)
        # Avoid blocking interpreter shutdown.
        try:
            t.daemon = True
        except Exception:  # noqa: BLE001
            pass
        self._timer = t
        t.start()

    def _process_pending(self):
        import auto_git as ag

        # Claim a processing slot or reschedule if we're too early.
        with self._lock:
            if self.stop_event and self.stop_event.is_set():
                return
            if self._processing:
                return
            if not self._pending:
                self._timer = None
                return

            now = self._clock()
            if self.interval_seconds > 0:
                # `_next_run_time` is set when the first change arrives (or when
                # changes arrive during/after a run). This avoids repeatedly
                # "re-initializing" the first run window.
                if self._next_run_time is None:
                    if self._last_run_time > 0:
                        self._next_run_time = self._last_run_time + self.interval_seconds
                    else:
                        self._next_run_time = now + self.interval_seconds

                if now < self._next_run_time:
                    self._timer = None
                    self._schedule_locked(self._next_run_time - now)
                    return

            self._processing = True
            self._pending = False
            self._last_run_time = now
            self._timer = None
            self._next_run_time = None

        try:
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
        finally:
            with self._lock:
                self._processing = False
                if self.stop_event and self.stop_event.is_set():
                    return
                if self._pending:
                    # Coalesce further events into the next interval window.
                    if self.interval_seconds > 0:
                        now = self._clock()
                        self._next_run_time = self._last_run_time + self.interval_seconds
                        self._schedule_locked(max(0.0, self._next_run_time - now))
                    else:
                        self._schedule_locked(0.0)

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

        # When interval is set, debounce/collect changes so we don't create commits
        # on every filesystem event.
        with self._lock:
            self._pending = True
            if self.interval_seconds > 0:
                now = self._clock()
                if self._next_run_time is None:
                    if self._last_run_time > 0:
                        self._next_run_time = self._last_run_time + self.interval_seconds
                    else:
                        self._next_run_time = now + self.interval_seconds
                self._show_status(
                    f"Change detected; next check in {max(0, int(self._next_run_time - now))}s..."
                )
                self._schedule_locked(self._next_run_time - now)
                return

        # Default behavior (interval=0): process immediately (backwards compatible).
        self._process_pending()
