"""Audit log: every action that changes the chassis or a config, as JSON lines in the workspace."""
from __future__ import annotations

import json
import pathlib
import threading
import time
from typing import Any


class Audit:
    def __init__(self, workspace: pathlib.Path) -> None:
        self.path = pathlib.Path(workspace) / "audit.log"
        self._lock = threading.Lock()

    def record(self, action: str, args: dict[str, Any], ok: bool, result: str = "") -> dict[str, Any]:
        entry = {"ts": time.time(), "action": action, "args": args, "ok": ok, "result": result}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        return entry

    def tail(self, n: int = 200) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-n:]
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
