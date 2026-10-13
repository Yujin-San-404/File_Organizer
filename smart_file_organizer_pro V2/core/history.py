"""Session-based move history / undo, plus a thread-safe cancel flag."""

import datetime
import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Optional

HISTORY_FILENAME = "sfo_history.json"


class HistoryManager:
    """Records file-move operations grouped by session ID."""

    def __init__(self, history_path: Path) -> None:
        self.history_path = history_path
        self.sessions: list[dict] = []
        self._current_session: Optional[dict] = None
        self._load()

    def _load(self) -> None:
        if self.history_path.exists():
            try:
                with self.history_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                self.sessions = data.get("sessions", [])
                return
            except (json.JSONDecodeError, OSError):
                pass
        self.sessions = []

    def _persist(self) -> None:
        try:
            with self.history_path.open("w", encoding="utf-8") as fh:
                json.dump({"sessions": self.sessions}, fh, indent=2)
        except OSError as exc:
            logging.warning("Could not persist history: %s", exc)

    def begin_session(self) -> str:
        sid = str(uuid.uuid4())
        self._current_session = {
            "session_id": sid,
            "timestamp": datetime.datetime.now().isoformat(),
            "records": [],
        }
        self.sessions.append(self._current_session)
        self._persist()
        return sid

    def record(self, src: str, dst: str) -> None:
        if self._current_session is None:
            self.begin_session()
        assert self._current_session is not None
        self._current_session["records"].append({"src": src, "dst": dst})
        self._persist()

    def end_session(self) -> None:
        if self._current_session and not self._current_session["records"]:
            self.sessions = [s for s in self.sessions
                              if s["session_id"] != self._current_session["session_id"]]
        self._current_session = None
        self._persist()

    def has_sessions(self) -> bool:
        return bool(self.sessions)

    def session_count(self) -> int:
        return len(self.sessions)

    def last_session_size(self) -> int:
        if not self.sessions:
            return 0
        return len(self.sessions[-1]["records"])

    def pop_last_session(self) -> list[dict]:
        if not self.sessions:
            return []
        session = self.sessions.pop()
        self._persist()
        return session["records"]

    def clear_all(self) -> None:
        self.sessions = []
        self._current_session = None
        self._persist()


class CancelToken:
    """Thread-safe flag that signals a worker to stop."""

    def __init__(self) -> None:
        self._cancelled = False
        self._lock = threading.Lock()

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True

    def reset(self) -> None:
        with self._lock:
            self._cancelled = False

    @property
    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled
