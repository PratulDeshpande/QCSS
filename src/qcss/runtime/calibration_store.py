"""Calibration store: immutable snapshots per epoch, updated by compare-and-swap.

What the OS writes here is what it would program into the instruments (drive/readout
frequencies, mixer correction, flux predistortion, discriminator rotation/threshold,
acquisition delay); the simulator applies it on top of the hidden truth.
"""
from __future__ import annotations

import threading

from qcss.core.errors import QCSSError
from qcss.v1 import calibration_pb2


class CalibrationEpochError(QCSSError):
    """The caller's expected calibration epoch is stale."""


class CalibrationStore:
    def __init__(self, defaults: calibration_pb2.CalibrationSnapshot | None = None) -> None:
        self._lock = threading.Lock()
        self._snap = calibration_pb2.CalibrationSnapshot()
        if defaults is not None:
            self._snap.CopyFrom(defaults)
        self._os_set: set[int] = set()            # qubits whose calibration the OS has written

    @property
    def epoch(self) -> int:
        return self._snap.calibration_epoch

    def snapshot(self, qubit_indices: list[int] | None = None) -> calibration_pb2.CalibrationSnapshot:
        with self._lock:
            out = calibration_pb2.CalibrationSnapshot(calibration_epoch=self._snap.calibration_epoch)
            for q in self._snap.qubits:
                if not qubit_indices or q.qubit_index in qubit_indices:
                    out.qubits.add().CopyFrom(q)
            return out

    def pin(self) -> tuple[calibration_pb2.CalibrationSnapshot, frozenset[int]]:
        """The snapshot and the OS-written qubits, read together: what an instrument uploads at job start."""
        with self._lock:
            snap = calibration_pb2.CalibrationSnapshot()
            snap.CopyFrom(self._snap)
            return snap, frozenset(self._os_set)

    def os_set(self) -> frozenset[int]:
        with self._lock:
            return frozenset(self._os_set)

    def update(self, snapshot: calibration_pb2.CalibrationSnapshot, expected_epoch: int) -> int:
        """Replace the listed qubits' calibration if expected_epoch is current; returns the new epoch."""
        with self._lock:
            if expected_epoch != self._snap.calibration_epoch:
                raise CalibrationEpochError(
                    f"expected_epoch {expected_epoch} is stale (current {self._snap.calibration_epoch})")
            by_q = {q.qubit_index: q for q in self._snap.qubits}
            for q in snapshot.qubits:
                new = calibration_pb2.QubitCalibration()
                new.CopyFrom(q)
                by_q[q.qubit_index] = new
                self._os_set.add(q.qubit_index)
            del self._snap.qubits[:]
            for k in sorted(by_q):
                self._snap.qubits.add().CopyFrom(by_q[k])
            self._snap.calibration_epoch += 1
            return self._snap.calibration_epoch
