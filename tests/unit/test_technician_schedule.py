"""When the technician calibrates: requests first (Quark's L4 request, the operator), then the schedule."""
from __future__ import annotations

import json
from pathlib import Path

from qcss.technician import CalibrationOutcome
from qcss.technician.schedule import Shift, request_calibration


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def shift(tmp_path: Path, ran: list[str], ok: bool = True) -> tuple[Shift, Clock]:
    clock = Clock()

    def calibrate(runcard: Path) -> CalibrationOutcome:
        ran.append(runcard.stem)
        return CalibrationOutcome(ok, tmp_path / "report")
    schedule = {Path("quick.yml"): 3600.0, Path("full.yml"): 86400.0}
    return Shift(calibrate, schedule, tmp_path / "requests", {"device": Path("full.yml")}, clock=clock), clock


def test_everything_never_run_is_due_then_only_what_has_aged(tmp_path):
    ran: list[str] = []
    s, clock = shift(tmp_path, ran)
    while s.step():
        pass
    assert ran == ["quick", "full"]
    clock.t += 3601
    while s.step():
        pass
    assert ran == ["quick", "full", "quick"]                # the daily one is not due yet


def test_a_request_is_served_before_the_schedule_and_acknowledged(tmp_path):
    ran: list[str] = []
    s, _ = shift(tmp_path, ran)
    ack = request_calibration(tmp_path / "requests", ["device"], expected_duration_s=600, now=1000.0)
    assert ack["accepted"] and ack["expected_complete_at"] == 1600.0
    assert s.step()
    assert ran == ["full"]                                  # the request's runcard, ahead of anything scheduled
    done = list((tmp_path / "requests" / "done").glob("*.json"))
    assert len(done) == 1 and json.loads(done[0].read_text())["ok"] is True


def test_a_failed_run_is_retried_after_its_back_off_not_marked_done(tmp_path):
    ran: list[str] = []
    s, clock = shift(tmp_path, ran, ok=False)
    s.step()
    s.step()
    assert ran == ["quick", "full"]                         # quick failed: it waits, the next one runs
    clock.t += 361                                          # a tenth of quick's hour
    s.step()
    assert ran == ["quick", "full", "quick"]


def test_an_unknown_scope_is_refused_at_request_time(tmp_path):
    ack = request_calibration(tmp_path / "requests", ["q9-teleportation"], known_scopes={"device"},
                              expected_duration_s=60, now=0.0)
    assert not ack["accepted"] and "q9-teleportation" in ack["reason"]
    assert not list((tmp_path / "requests").glob("*.json"))


def test_a_calibration_that_raises_files_the_request_as_failed_and_the_shift_goes_on(tmp_path):
    def calibrate(runcard: Path) -> CalibrationOutcome:
        raise PermissionError("parameters.json is held open by a reader")
    s = Shift(calibrate, {}, tmp_path / "requests", {"device": Path("full.yml")}, clock=lambda: 0.0)
    request_calibration(tmp_path / "requests", ["device"], expected_duration_s=60, now=0.0)
    assert s.step()                                         # did not raise
    failed = list((tmp_path / "requests" / "failed").glob("*.json"))
    assert len(failed) == 1 and "PermissionError" in json.loads(failed[0].read_text())["reason"]
    assert not list((tmp_path / "requests").glob("*.json"))


def test_a_scheduled_calibration_that_raises_backs_off_like_a_failed_one(tmp_path):
    ran: list[str] = []

    def calibrate(runcard: Path) -> CalibrationOutcome:
        ran.append(runcard.stem)
        if runcard.stem == "quick":
            raise OSError("rename failed")
        return CalibrationOutcome(True, tmp_path)
    s = Shift(calibrate, {Path("quick.yml"): 3600.0, Path("full.yml"): 86400.0}, tmp_path / "r", {},
              clock=lambda: 0.0)
    for _ in range(3):
        s.step()
    assert ran == ["quick", "full"]


def test_a_restarted_shift_remembers_what_it_already_calibrated(tmp_path):
    ran: list[str] = []
    state = tmp_path / "state.json"

    def calibrate(runcard: Path) -> CalibrationOutcome:
        ran.append(runcard.stem)
        return CalibrationOutcome(True, tmp_path)
    schedule = {Path("quick.yml"): 3600.0, Path("full.yml"): 86400.0}
    first = Shift(calibrate, schedule, tmp_path / "r", {}, clock=lambda: 1000.0, state_file=state)
    while first.step():
        pass
    assert ran == ["quick", "full"]
    second = Shift(calibrate, schedule, tmp_path / "r", {}, clock=lambda: 1060.0, state_file=state)
    assert not second.step()                                # a minute later nothing is due again
    assert ran == ["quick", "full"]
