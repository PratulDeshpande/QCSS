"""Error classes for QCSS core and validation."""
from __future__ import annotations


class QCSSError(Exception):
    """Base exception for all QCSS errors."""


class HardwareValidationError(ValueError, QCSSError):
    """Carries (field_path, description) pairs for every violated hardware rule."""

    def __init__(self, violations: list[tuple[str, str]]):
        super().__init__("; ".join(f"{p}: {d}" for p, d in violations))
        self.violations = violations


class TimebaseError(ValueError, QCSSError):
    """Raised when a duration cannot be represented exactly on the tick grid."""


class TierRoutingError(QCSSError):
    """The requested fidelity tier cannot run this job (maps to FAILED_PRECONDITION)."""
