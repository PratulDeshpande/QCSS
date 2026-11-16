"""Each play() pins its job to the settings it just uploaded (review C1: clients sharing one instrument)."""
from __future__ import annotations

import pytest

pytest.importorskip("qibolab", reason="the qibolab extra is not installed")

from qibolab import (
    AcquisitionType,
    AveragingMode,
    ExecutionParameters,
    Gaussian,
    Pulse,
    PulseSequence,
)

from qcss.v1 import calibration_pb2, result_pb2
from qcss_qibolab.controller import QcssController


class FakeInstrument:
    def __init__(self) -> None:
        self.jobs: list = []

    def get_calibration(self, qubits=()):
        return calibration_pb2.CalibrationSnapshot(calibration_epoch=4)

    def update_calibration(self, snapshot, expected_epoch):
        return expected_epoch + 1

    def submit(self, job, *, quark_job_id=None):
        self.jobs.append(job)
        return "job-1", 5

    def wait(self, job_id, *, poll_s=0.2, timeout_s=None):
        return result_pb2.JobStatus(job_id=job_id, state=result_pb2.JOB_STATE_COMPLETED)

    def results(self, job_id, *, resume_after=0, reconnects=3):
        return iter(())


def test_a_job_is_pinned_to_the_settings_its_play_uploaded():
    ctl = QcssController(address="127.0.0.1:1", channels={})
    fake = FakeInstrument()
    ctl._client = fake                                       # type: ignore[assignment]
    seq = PulseSequence([("0/drive", Pulse(duration=40, amplitude=0.5, envelope=Gaussian(rel_sigma=0.2)))])
    ctl.play({}, [seq], ExecutionParameters(nshots=10, relaxation_time=1000,
                                            acquisition_type=AcquisitionType.DISCRIMINATION,
                                            averaging_mode=AveragingMode.CYCLIC), [])
    (job,) = fake.jobs
    assert job.HasField("expected_calibration_epoch") and job.expected_calibration_epoch == 5


class CountingInstrument(FakeInstrument):
    def __init__(self, drive_hz: float) -> None:
        super().__init__()
        self.epoch, self.writes = 4, 0
        self.drive_hz = drive_hz

    def get_calibration(self, qubits=()):
        return calibration_pb2.CalibrationSnapshot(calibration_epoch=self.epoch, qubits=[
            calibration_pb2.QubitCalibration(qubit_index=0, drive_frequency_hz=self.drive_hz, pi_amplitude=0.3)])

    def update_calibration(self, snapshot, expected_epoch):
        self.writes += 1
        self.epoch = expected_epoch + 1
        return self.epoch


def _settings(drive_hz: float) -> calibration_pb2.CalibrationSnapshot:
    return calibration_pb2.CalibrationSnapshot(qubits=[
        calibration_pb2.QubitCalibration(qubit_index=0, drive_frequency_hz=drive_hz)])


def test_settings_the_instrument_already_has_are_not_written_again():
    """A write bumps the epoch, which would invalidate every other client's pin for no change at all."""
    ctl = QcssController(address="127.0.0.1:1", channels={})
    fake = CountingInstrument(5.0e9)
    assert ctl._program(fake, _settings(5.0e9)) == 4     # type: ignore[arg-type]
    assert fake.writes == 0


def test_changed_settings_are_written_and_the_job_is_pinned_to_the_new_epoch():
    ctl = QcssController(address="127.0.0.1:1", channels={})
    fake = CountingInstrument(5.0e9)
    assert ctl._program(fake, _settings(5.1e9)) == 5     # type: ignore[arg-type]
    assert fake.writes == 1
