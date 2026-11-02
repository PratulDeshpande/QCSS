"""The virtual technician: calibrates a QCSS platform with the real Qibocal, as a lab's staff do.

QCSS never writes calibration. The technician runs a Qibocal runcard against the platform
(through Qibolab, so through the instrument), checks what Qibocal fitted, and only then
puts Qibocal's updated parameters.json and calibration.json in place, one atomic replace
per file, so a reader such as Quark's adapter never sees a half-written file. A failed or
implausible run leaves the platform as it was, and the report stays for the record.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CALIBRATION_FILES = ("parameters.json", "calibration.json")
NEW_PLATFORM = "new_platform"           # Qibocal's output folder of the updated platform


def calibration_set_digest(platform_dir: Path) -> str:
    """The calibration-set identity of a Qibolab platform (L7 LLD 7.4): sha256 of its calibration files."""
    h = hashlib.sha256()
    for name in CALIBRATION_FILES:
        path = Path(platform_dir) / name
        h.update(name.encode() + b"\0" + (path.read_bytes() if path.exists() else b"") + b"\0")
    return h.hexdigest()


@dataclass
class CalibrationOutcome:
    ok: bool
    report_dir: Path
    log: str = ""
    files_after: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)


def _finite(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, Mapping):
        return all(_finite(v) for v in value.values())
    if isinstance(value, list):
        return all(_finite(v) for v in value)
    return True


class Technician:
    def __init__(self, platforms_dir: Path, platform: str, *, reports: Path,
                 env: Mapping[str, str] | None = None, timeout_s: float = 3600.0) -> None:
        self.platforms_dir = Path(platforms_dir)
        self.platform = platform
        self.platform_dir = self.platforms_dir / platform
        self.reports = Path(reports)
        self.env = dict(env or {})
        self.timeout_s = timeout_s

    def calibrate(self, runcard: Path) -> CalibrationOutcome:
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S%fZ")
        out = self.reports / f"{stamp}-{Path(runcard).stem}"
        self.reports.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "QIBOLAB_PLATFORMS": str(self.platforms_dir), **self.env}
        cmd = [sys.executable, "-c", "from qibocal import command; command()", "run", str(runcard),
               "-o", str(out), "-f", "--platform", self.platform]
        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=self.timeout_s, check=False)
            log, ok = proc.stdout + proc.stderr, proc.returncode == 0
        except subprocess.TimeoutExpired as err:
            log, ok = f"qibocal timed out after {self.timeout_s} s\n{err.stdout or ''}{err.stderr or ''}", False
        new = out / NEW_PLATFORM
        if ok:
            ok, why = self._plausible(new)
            log += why
        replaced = self._install(new) if ok else []
        return CalibrationOutcome(ok, out, log[-20_000:], sorted(os.listdir(self.platform_dir)), replaced)

    def _plausible(self, new: Path) -> tuple[bool, str]:
        params = new / "parameters.json"
        if not params.exists():
            return False, f"\nno updated platform in {new}"
        try:
            data = json.loads(params.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            return False, f"\nupdated parameters.json does not parse: {err}"
        if not _finite(data):
            return False, "\nupdated parameters.json holds NaN or infinite values: the fit failed"
        problem = _impossible(data)
        if problem:
            return False, f"\nupdated parameters.json is not physically possible: {problem}"
        return True, ""

    def _install(self, new: Path) -> list[str]:
        """Put the new calibration set in place whole, or leave the old one.

        Every file is staged (written and fsynced) before any is replaced, so the window between the
        renames is two renames long. If a rename fails — on Windows, a reader holding the file open is
        enough — the files already replaced are restored from their backups and the error is raised:
        the platform never keeps a new parameters.json beside an old calibration.json.
        """
        names = [name for name in CALIBRATION_FILES if (new / name).exists()]
        staged: dict[str, str] = {}
        backups: dict[str, str] = {}
        done: list[str] = []
        try:
            for name in names:
                staged[name] = self._stage(name, (new / name).read_bytes())
                old = self.platform_dir / name
                if old.exists():
                    backups[name] = self._stage(name + ".bak", old.read_bytes())
            for name in names:
                os.replace(staged[name], self.platform_dir / name)
                del staged[name]                        # only once it is in place: a failed rename is cleaned up
                done.append(name)
        except BaseException:
            for name in reversed(done):
                if name in backups:
                    os.replace(backups.pop(name), self.platform_dir / name)
                else:                                   # the file was new: the old set did not have it
                    (self.platform_dir / name).unlink(missing_ok=True)
            raise
        finally:
            for tmp in [*staged.values(), *backups.values()]:
                Path(tmp).unlink(missing_ok=True)
        return done

    def _stage(self, name: str, data: bytes) -> str:
        fd, tmp = tempfile.mkstemp(prefix=f".{name}.", dir=self.platform_dir)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        return tmp


def _impossible(data: Mapping[str, Any]) -> str:
    """The first value in a Qibolab parameters.json that no instrument could play, or "" (finite values only).

    Pulse amplitudes are fractions of full scale (Qibolab clips beyond 1), durations are positive, and
    channel frequencies are positive: a fit that lands outside these converged on nonsense.
    """
    def walk(node: Any, where: str) -> str:
        if isinstance(node, Mapping):
            if node.get("kind") == "pulse":
                amplitude, duration = node.get("amplitude"), node.get("duration")
                if isinstance(amplitude, int | float) and abs(amplitude) > 1.0:
                    return f"{where}: amplitude {amplitude} is beyond full scale"
                if isinstance(duration, int | float) and duration <= 0:
                    return f"{where}: duration {duration} is not positive"
            frequency = node.get("frequency")
            if isinstance(frequency, int | float) and frequency <= 0:
                return f"{where}: frequency {frequency} is not positive"
            items: Any = node.items()
        elif isinstance(node, list):
            items = enumerate(node)
        else:
            return ""
        for key, value in items:
            found = walk(value, f"{where}/{key}" if where else str(key))
            if found:
                return found
        return ""

    return walk(data, "")
