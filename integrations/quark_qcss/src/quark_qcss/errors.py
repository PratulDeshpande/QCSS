"""Driver errors classified the way Quark's Scheduler acts on them (HLD §8.5, §8.7).

transient            -> retry with backoff (at most 3), then FAILED
counts_toward_breaker -> consecutive ones open the device's circuit breaker (device offline + alert)
StaleCalibrationError -> re-plan once against the current calibration
"""
from __future__ import annotations

import grpc

from qcss.client import QcssRpcError


class DriverError(Exception):
    transient = False
    counts_toward_breaker = False

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.code = code


class TransientDriverError(DriverError):
    """The control stack could not be reached or was overloaded; the job itself may be fine."""
    transient = True
    counts_toward_breaker = True


class PermanentDriverError(DriverError):
    """The job cannot run as given (hardware-rule violation, unsupported program, failed run)."""


class StaleCalibrationError(PermanentDriverError):
    """The plan was made against a calibration epoch that is no longer current."""


class DriverConfigurationError(PermanentDriverError):
    """Credentials or endpoint are wrong; every job will fail until an operator fixes the driver."""
    counts_toward_breaker = True


_TRANSIENT = {grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED, grpc.StatusCode.RESOURCE_EXHAUSTED,
              grpc.StatusCode.ABORTED}
_CONFIG = {grpc.StatusCode.UNAUTHENTICATED, grpc.StatusCode.PERMISSION_DENIED, grpc.StatusCode.UNIMPLEMENTED}


def classify(err: QcssRpcError) -> DriverError:
    """Map a QCSS gRPC failure onto Quark's error classes, keeping field paths and precondition types."""
    detail = err.message
    if err.field_violations:
        detail += "; " + "; ".join(f"{path}: {desc}" for path, desc in err.field_violations)
    code = err.code.name
    if err.code in _TRANSIENT:
        return TransientDriverError(detail, code=code)
    if err.code in _CONFIG:
        return DriverConfigurationError(detail, code=code)
    if err.code == grpc.StatusCode.FAILED_PRECONDITION and any(
            kind == "CALIBRATION_EPOCH" for kind, _, _ in err.precondition_failures):
        return StaleCalibrationError(detail, code=code)
    return PermanentDriverError(detail, code=code)
