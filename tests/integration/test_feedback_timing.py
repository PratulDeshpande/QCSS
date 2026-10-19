"""Mid-circuit feedback timing on the real shot executor (plan Phase 8).

A branch declared before its result can exist is re-armed to
acquisition start + ToF + integration + latency(route); the other sequencer keeps playing at its
programmed ticks while the conditional one waits.
"""
from __future__ import annotations

import numpy as np

from qcss.config.loader import load_profile
from qcss.core.timebase import TimeBase
from qcss.feedback.executor import ShotExecutor
from qcss.feedback.latency import FeedbackLatencyResolver
from qcss.ir.compiler import compile_job
from qcss.runtime.runner import PlannedPoint, SimulationContext
from qcss.v1 import job_pb2


def test_inter_module_latency_from_profile():
    prof = load_profile("src/qcss/config/profiles/qblox_cluster_5q.yaml")
    assert FeedbackLatencyResolver(prof).latency_ticks("qrm_rf0_seq0", "qcm_rf0_seq0") == 388


def test_branch_waits_for_result_while_spectator_plays():
    prof = load_profile("src/qcss/config/profiles/qblox_cluster_5q.yaml")
    seq1 = next(g for g in prof.generators if g.generator_id == "qcm_rf0_seq0").model_copy(
        update={"generator_id": "qcm_rf0_seq1"})
    prof = prof.model_copy(update={"generators": prof.generators + (seq1,)})
    tb = TimeBase.from_clocks("1e9")
    ctx = SimulationContext(prof, None, tb)
    assert ctx.bindings["xy_q1"].generator_id == "qcm_rf0_seq1"     # spectator on another sequencer

    j = job_pb2.Job(num_shots=1, repetition_delay_ticks=0)
    j.waveform_library["pi"].CopyFrom(job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=20))
    add = j.main.instructions.add
    add(start_tick=0, play=job_pb2.Play(channel_id="xy_q0", waveform_id="pi", amplitude=0.5))
    add(start_tick=20, acquire=job_pb2.Acquire(channel_id="ro_q0", integration_ticks=1000, register_index=0,
                                               mode=job_pb2.ACQUISITION_MODE_DISCRIMINATED))
    add(start_tick=1200, play=job_pb2.Play(channel_id="xy_q1", waveform_id="pi", amplitude=0.5))
    add(start_tick=1300, play=job_pb2.Play(channel_id="xy_q1", waveform_id="pi", amplitude=0.5))
    br = job_pb2.Branch(sequencer_id="qcm_rf0_seq0", duration_ticks=20, condition=job_pb2.Condition(
        op=job_pb2.CONDITION_OP_EQUAL, register_indices=[0], value=1))
    br.then_block.instructions.add(start_tick=1200, play=job_pb2.Play(channel_id="xy_q0", waveform_id="pi",
                                                                       amplitude=0.5))
    add(start_tick=1200, branch=br)       # declared too early on purpose (the validator would reject it)

    prog, wf = compile_job(j, prof, tb, bindings=ctx.bindings)
    point = PlannedPoint((), j, prog, wf)
    qubits = [0, 1]
    f01, t1 = ctx.device_parameters(0.0)
    engine = ctx.make_engine("T1B", qubits, f01, t1, seed=1)
    ex = ShotExecutor(ctx.exec_context(point, qubits, engine, ctx.calibration.snapshot(), f01, t1, tier="T1B"))
    res = ex.run_shot(prog, np.random.default_rng(0))

    ready = 20 + 153 + 1000 + 388                        # acq start + ToF + integration + inter-module latency
    events = {desc: tick for tick, desc in res.timeline}
    assert events["acq_done ro_q0 -> r0=1"] == 20 + 153 + 1000
    assert events["play xy_q1:pi"] in (1200, 1300)        # spectator: programmed ticks, not delayed
    assert sorted(t for t, d in res.timeline if d == "play xy_q1:pi") == [1200, 1300]
    assert events["branch job.main.instructions[4] -> then"] == ready
    assert sorted(t for t, d in res.timeline if d == "play xy_q0:pi") == [0, ready]   # reset pi spliced at decision
