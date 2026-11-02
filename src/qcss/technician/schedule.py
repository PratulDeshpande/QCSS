"""The technician's shift: calibration requests first, then whatever routine calibration has come due.

Requests arrive as JSON files in a spool folder on the lab side: from Quark's adapter (its
L4 request_calibration, configured to call `qcss technician request`) or from the operator.
Nothing here is a QCSS concept a lab would not have: a lab's staff take requests the same way.
"""
from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from qcss.technician import CalibrationOutcome


def request_calibration(requests_dir: Path, scope: Iterable[str], *, expected_duration_s: float,
                        now: float | None = None, known_scopes: Iterable[str] | None = None) -> dict[str, Any]:
    """Queue a calibration request; the acknowledgement carries when it should be done."""
    scope = list(scope)
    now = time.time() if now is None else now
    unknown = sorted(set(scope) - set(known_scopes)) if known_scopes is not None else []
    if not scope or unknown:
        return {"accepted": False, "expected_complete_at": None,
                "reason": f"unknown calibration scope {unknown}" if unknown else "empty calibration scope"}
    requests_dir = Path(requests_dir)
    requests_dir.mkdir(parents=True, exist_ok=True)
    ack = {"accepted": True, "expected_complete_at": now + expected_duration_s, "reason": None}
    name = f"{now:017.6f}-{uuid.uuid4().hex[:8]}.json"
    tmp = requests_dir / f".{name}.tmp"
    tmp.write_text(json.dumps({"scope": scope, "requested_at": now, **ack}), encoding="utf-8")
    tmp.replace(requests_dir / name)                     # a request appears whole or not at all
    return ack


class Shift:
    def __init__(self, calibrate: Callable[[Path], CalibrationOutcome], schedule: Mapping[Path, float],
                 requests_dir: Path, scope_runcards: Mapping[str, Path], *,
                 clock: Callable[[], float] = time.time, state_file: Path | None = None) -> None:
        self._calibrate = calibrate
        self._schedule = dict(schedule)                  # runcard -> interval (s), in order of priority
        self._requests = Path(requests_dir)
        self._scopes = dict(scope_runcards)              # request scope -> runcard that serves it
        self._clock = clock
        self._state_file = Path(state_file) if state_file is not None else None
        self.last_ok: dict[Path, float] = self._load_last_ok()
        self._last_attempt: dict[Path, float] = {}

    def _load_last_ok(self) -> dict[Path, float]:
        """What earlier shifts calibrated, so a restart does not redo hours of work that is still fresh."""
        if self._state_file is None or not self._state_file.exists():
            return {}
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            return {Path(k): float(v) for k, v in data.get("last_ok", {}).items()}
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
            return {}                                   # unreadable state: treat everything as due

    def _mark_ok(self, runcard: Path) -> None:
        self.last_ok[runcard] = self._clock()
        if self._state_file is None:
            return
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_file.with_name(f".{self._state_file.name}.tmp")
        tmp.write_text(json.dumps({"last_ok": {str(k): v for k, v in self.last_ok.items()}}), encoding="utf-8")
        tmp.replace(self._state_file)

    def _run(self, runcard: Path) -> tuple[CalibrationOutcome | None, str | None]:
        """Calibrate, turning an exception (a failed install, say) into a failure instead of ending the shift."""
        try:
            return self._calibrate(runcard), None
        except Exception as err:  # noqa: BLE001
            return None, f"{runcard.name}: {err!r}"

    def step(self) -> bool:
        """Run what is waiting or due; False when there is nothing to do.

        A request runs every scope it names; a malformed or failing request moves to failed/ with the
        reason, so it never blocks the shift. A failing scheduled runcard backs off (a tenth of its
        interval, at most an hour) and lets the others run."""
        pending = sorted(self._requests.glob("*.json")) if self._requests.exists() else []
        if pending:
            path = pending[0]
            try:
                req = json.loads(path.read_text(encoding="utf-8"))
                runcards = [self._scopes[s] for s in req["scope"]]
            except (json.JSONDecodeError, KeyError, TypeError) as err:
                self._file(path, "failed", {"reason": f"malformed request: {err!r}"})
                return True
            runs = [self._run(rc) for rc in runcards]
            outcomes = [o for o, _ in runs if o is not None]
            errors = [e for _, e in runs if e is not None]
            ok = not errors and all(o.ok for o in outcomes)
            if ok:
                for rc in runcards:
                    self._mark_ok(rc)
            record = {**req, "ok": ok, "finished_at": self._clock(), "reports": [str(o.report_dir) for o in outcomes]}
            if errors:
                record["reason"] = "; ".join(errors)
            self._file(path, "done" if ok else "failed", record)
            return True
        now = self._clock()
        for runcard, interval in self._schedule.items():
            last, tried = self.last_ok.get(runcard), self._last_attempt.get(runcard)
            due = last is None or now - last >= interval
            backing_off = tried is not None and (last is None or tried > last) and now - tried < min(interval / 10, 3600)
            if due and not backing_off:
                self._last_attempt[runcard] = now
                outcome, _ = self._run(runcard)
                if outcome is not None and outcome.ok:
                    self._mark_ok(runcard)
                return True
        return False

    def _file(self, path: Path, where: str, record: dict[str, Any]) -> None:
        folder = self._requests / where
        folder.mkdir(exist_ok=True)
        (folder / path.name).write_text(json.dumps(record), encoding="utf-8")
        path.unlink()
