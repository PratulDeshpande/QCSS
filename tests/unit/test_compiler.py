"""Unit tests for compiler (Job -> Program IR)."""
from __future__ import annotations

import numpy as np

from qcss.config.loader import load_profile
from qcss.core.timebase import TimeBase
from qcss.ir.compiler import compile_job
from qcss.ir.program import Acquire, FrameOp, Play
from qcss.v1 import job_pb2


def test_compile_job_basic():
    profile = load_profile("src/qcss/config/profiles/qblox_cluster_5q.yaml")
    tb = TimeBase.from_clocks("1e9")

    job = job_pb2.Job(
        job_key="test_compile",
        num_shots=10,
        repetition_delay_ticks=200_000,
        waveform_library={
            "g1": job_pb2.Waveform(
                shape=job_pb2.WAVEFORM_SHAPE_GAUSSIAN,
                length_samples=20,
                sigma_samples=5.0,
            ),
            "drag1": job_pb2.Waveform(
                shape=job_pb2.WAVEFORM_SHAPE_DRAG,
                length_samples=32,
                sigma_samples=8.0,
                drag_beta_samples=1.5,
            ),
        },
    )

    # Add instructions
    job.main.instructions.add(
        start_tick=0,
        play=job_pb2.Play(channel_id="xy_q0", waveform_id="g1", amplitude=0.8),
    )
    job.main.instructions.add(
        start_tick=20,
        shift_phase=job_pb2.ShiftPhase(frame_id="q0", delta_rad=1.57),
    )
    job.main.instructions.add(
        start_tick=40,
        acquire=job_pb2.Acquire(
            channel_id="ro_q0",
            integration_ticks=500,
            mode=job_pb2.ACQUISITION_MODE_DISCRIMINATED,
            register_index=0,
            result_key="q0",
        ),
    )

    prog, wf_lib = compile_job(job, profile, tb)

    assert len(prog.ops) == 3
    assert isinstance(prog.ops[0], Play)
    assert prog.ops[0].duration == 20
    assert prog.ops[0].amplitude == 0.8

    assert isinstance(prog.ops[1], FrameOp)
    assert prog.ops[1].kind == "shift"
    assert np.isclose(prog.ops[1].value, 1.57)

    assert isinstance(prog.ops[2], Acquire)
    assert prog.ops[2].integration == 500
    assert prog.ops[2].mode == "discriminated"

    assert prog.duration == 540  # 40 + 500
    assert prog.repetition_delay == 200_000

    # Check waveform library
    assert wf_lib.count("qcm_rf0_seq0") == 2
