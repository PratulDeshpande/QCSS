"""What one job may cost the host. The hardware's own limits live in the profile; these protect the machine."""
from __future__ import annotations

# shortcut: fixed for every host, make them chassis options if someone needs a bigger machine
MAX_SWEEP_POINTS = 65_536
MAX_EXPANDED_JOB_BYTES = 2 << 30                  # every sweep point starts as a copy of the job
MAX_SHOTS_PER_POINT = 10_000_000
MAX_READOUT_BYTES = 8 << 30
BYTES_PER_SHOT_SAMPLE = 48                        # record, resonator field and two noise arrays, at the peak


def readout_bytes(shots: int, samples: int) -> int:
    """Peak memory of simulating `shots` captures of `samples` ADC samples."""
    return shots * samples * BYTES_PER_SHOT_SAMPLE


def check_record(shots: int, samples: int) -> None:
    """Raise rather than let one capture take the host down."""
    if readout_bytes(shots, samples) > MAX_READOUT_BYTES:
        raise ValueError("the record exceeds the instrument's capture memory")
