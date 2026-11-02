"""End-to-end physics through the real runtime (what the gRPC server and CLI execute).

Covers defects D3 (pulse shape/phase), D4 (no gate-name guessing), D6 (carry-over),
D7 (ticks vs ns), D8 (determinism), D10 (signal chain + physical readout wired),
D11 (event loop stays responsive), D13 (routing at submit), D16 (sweeps, timestamps).
"""
from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest

from qcss.config.device import DeviceSpec
from qcss.config.loader import load_device, load_profile
from qcss.core.errors import HardwareValidationError
from qcss.core.ndarray import from_proto, to_proto
from qcss.core.timebase import TimeBase
from qcss.ir.waveforms import gaussian
from qcss.runtime.jobs import JobManager
from qcss.runtime.runner import TierRoutingError, create_simulation_runner, create_simulation_validator
from qcss.v1 import job_pb2, result_pb2
from tests.stats import assert_binomial

PROFILES = "src/qcss/config/profiles/"
IDEAL = load_profile(PROFILES + "test_ideal_1q.yaml")
QBLOX = load_profile(PROFILES + "qblox_cluster_5q.yaml")
ZI = load_profile(PROFILES + "zi_shfqc_5q.yaml")
DEV1 = load_device("src/qcss/config/devices/test_ideal_1q.yaml")
RABI = 2 * np.pi * 0.05          # rad/ns at amplitude 1 (rabi_max_ghz = 0.05)
T2 = job_pb2.FIDELITY_TIER_T2_LINDBLAD
T1B = job_pb2.FIDELITY_TIER_T1B_STATEVECTOR
T1A = job_pb2.FIDELITY_TIER_T1A_STABILIZER
T0 = job_pb2.FIDELITY_TIER_T0_SURROGATE


def run(profile, job, device=None, **kw):
    tb = TimeBase.from_clocks(profile.clock.tick_hz)
    runner = create_simulation_runner(profile, device, tb, **kw)

    async def go():
        return [c async for c in runner("job-under-test", job, asyncio.Event())]
    return asyncio.run(go())


def states(chunks, key="q0"):
    return np.concatenate([from_proto(a.states) for c in chunks for a in c.acquisitions if a.result_key == key])


def job(plays, acq_at, tier, shots=1000, seed=7, wf=None, ro="ro_q0", integ=400, **kw):
    j = job_pb2.Job(job_key="t", num_shots=shots, requested_tier=tier, random_seed=seed, **kw)
    for k, w in (wf or {"pi": job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=20)}).items():
        j.waveform_library[k].CopyFrom(w)
    for p in plays:
        start, op = p[0], p[1]
        if op == "play":
            _, _, ch, wid, amp, *ph = p
            j.main.instructions.add(start_tick=start, play=job_pb2.Play(
                channel_id=ch, waveform_id=wid, amplitude=amp, phase_offset_rad=ph[0] if ph else 0.0))
        elif op == "shift":
            j.main.instructions.add(start_tick=start, shift_phase=job_pb2.ShiftPhase(frame_id=p[2], delta_rad=p[3]))
        elif op == "set":
            j.main.instructions.add(start_tick=start, set_phase=job_pb2.SetPhase(frame_id=p[2], phase_rad=p[3]))
    j.main.instructions.add(start_tick=acq_at, acquire=job_pb2.Acquire(
        channel_id=ro, integration_ticks=integ, mode=job_pb2.ACQUISITION_MODE_DISCRIMINATED,
        register_index=0, result_key="q0"))
    return j


SQ20 = job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=20)
SQ10 = job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=10)


# ---------------------------------------------------------------- D3: shape and phase reach the qubit
def test_t2_pulse_shape_matters():
    g = job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_GAUSSIAN, length_samples=20)
    j = job([(0, "play", "xy_q0", "g", 0.5)], 24, T2, shots=2000, wf={"g": g})
    p1 = states(run(IDEAL, j, DEV1)).mean()
    area = 0.5 * RABI * gaussian(20).sum()
    expected = np.sin(area / 2) ** 2
    assert_binomial(int(p1 * 2000), 2000, expected, delta_model=0.03)
    assert p1 < 0.8          # a square pulse of the same amplitude would give ~0.98


def test_t2_phase_offset_cancels_rotation():
    j = job([(0, "play", "xy_q0", "h", 0.5), (10, "play", "xy_q0", "h", 0.5, np.pi)], 24, T2, shots=1000,
            wf={"h": SQ10})
    assert states(run(IDEAL, j, DEV1)).mean() < 0.05


def test_t2_virtual_z_reaches_the_drive_and_set_phase_is_absolute():
    vz = job([(0, "play", "xy_q0", "h", 0.5), (10, "shift", "q0", np.pi), (10, "play", "xy_q0", "h", 0.5)],
             24, T2, shots=1000, wf={"h": SQ10})
    assert states(run(IDEAL, vz, DEV1)).mean() < 0.05
    reset = job([(0, "play", "xy_q0", "h", 0.5), (10, "shift", "q0", np.pi / 2), (10, "set", "q0", 0.0),
                 (10, "play", "xy_q0", "h", 0.5)], 24, T2, shots=1000, wf={"h": SQ10})
    assert states(run(IDEAL, reset, DEV1)).mean() > 0.9


# ---------------------------------------------------------------- D4: names carry no meaning
@pytest.mark.parametrize("tier", [T0, T1A, T1B])
def test_gate_tiers_use_the_pulse_not_its_name(tier):
    j = job([(0, "play", "xy_q0", "cz", 0.5)], 24, tier, wf={"cz": SQ20})
    assert states(run(IDEAL, j, DEV1)).mean() > 0.95


def test_t1b_matches_t2_for_a_half_rotation():
    j2 = job([(0, "play", "xy_q0", "h", 0.5)], 24, T2, shots=2000, wf={"h": SQ10})
    j1 = job([(0, "play", "xy_q0", "h", 0.5)], 24, T1B, shots=2000, wf={"h": SQ10})
    a, b = states(run(IDEAL, j2, DEV1)).mean(), states(run(IDEAL, j1, DEV1)).mean()
    assert abs(a - b) < 5 * np.sqrt(0.25 / 2000) * np.sqrt(2) + 0.02


def test_non_clifford_pulse_on_t1a_is_refused_at_submit():
    validate = create_simulation_validator(IDEAL, TimeBase.from_clocks("1e9"), DEV1)
    j = job([(0, "play", "xy_q0", "w", 0.13)], 24, T1A, wf={"w": SQ20})
    with pytest.raises(TierRoutingError, match="Clifford"):
        asyncio.run(validate(j))


# ---------------------------------------------------------------- D7: ticks are not nanoseconds
def test_zi_ticks_convert_to_ns_for_decay():
    dev = DeviceSpec.model_validate({
        "device_name": "fast_t1",
        "qubits": [{"qubit_index": 0, "f_max_ghz": 5.0, "ec_ghz": 0.3, "t1_us": 10.0, "t2_star_us": 10.0}],
        "resonators": [{"qubit_index": 0, "f_r_ghz": 7.0, "kappa_mhz": 1.0, "pulls_mhz": [0.0, -1.5, -3.0],
                        "cable_delay_ns": 100.0, "eta": 0.5}]})
    pi32 = job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=32)
    amp = np.pi / (RABI * 32 * 0.5)                    # 32 samples at 2 GS/s = 16 ns
    # QA at 2 GS/s: 2000 ticks = 1 us of integration (the resonator rings up in 2/kappa ~ 318 ns);
    # ZI discriminates up to 4 levels, so "excited" means label >= 1
    j = job([(0, "play", "xy_q0", "pi", amp)], 20032, T1B, shots=3000, wf={"pi": pi32}, integ=2000)
    p1 = (states(run(ZI, j, dev)) >= 1).mean()
    assert_binomial(int(p1 * 3000), 3000, np.exp(-1.0), delta_model=0.03)   # 10 us of decay, not 20 us


# ---------------------------------------------------------------- D8: reproducibility
@pytest.mark.parametrize("tier", [T0, T1B])
def test_seeded_jobs_are_reproducible(tier):
    j = job([(0, "play", "xy_q0", "h", 0.5)], 24, tier, shots=500, seed=11, wf={"h": SQ10})
    a, b = states(run(IDEAL, j, DEV1)), states(run(IDEAL, j, DEV1))
    assert np.array_equal(a, b)
    j.random_seed = 12
    assert not np.array_equal(a, states(run(IDEAL, j, DEV1)))


# ---------------------------------------------------------------- D6, D16: carry-over and timestamps
def test_no_hidden_reset_between_shots():
    j = job([(0, "play", "xy_q0", "pi", 0.5)], 24, T1B, shots=200, wf={"pi": SQ20}, repetition_delay_ticks=0)
    s = states(run(IDEAL, j, DEV1))
    assert 0.4 < s.mean() < 0.6                       # |0>->1, then the next pi takes 1->0, ...
    assert np.mean(s[1:] != s[:-1]) > 0.95            # alternates; ~1 % readout error breaks a few pairs


def test_default_repetition_delay_lets_the_qubit_relax():
    j = job([(0, "play", "xy_q0", "pi", 0.5)], 24, T1B, shots=200, wf={"pi": SQ20})
    assert states(run(IDEAL, j, DEV1)).mean() > 0.95


def test_shot_end_ticks_are_absolute_and_periodic():
    j = job([(0, "play", "xy_q0", "pi", 0.5)], 24, T1B, shots=50, wf={"pi": SQ20}, repetition_delay_ticks=1000)
    ch = run(IDEAL, j, DEV1)
    ends = np.concatenate([from_proto(a.shot_end_ticks) for c in ch for a in c.acquisitions])
    assert ends.dtype == np.uint64 and len(ends) == 50
    assert np.all(np.diff(ends.astype(np.int64)) == 24 + 400 + 100 + 1000)    # duration incl. ToF, + delay


def test_amplitude_sweep_streams_each_point():
    j = job([(0, "play", "xy_q0", "pi", 0.0)], 24, T1B, shots=300, wf={"pi": SQ20})
    j.sweeps.add(axis=0, amplitude=job_pb2.AmplitudeTarget(instruction_index=0),
                 values=to_proto(np.array([0.0, 0.25, 0.5])))
    ch = run(IDEAL, j, DEV1)
    by_point = {}
    for c in ch:
        by_point.setdefault(tuple(c.sweep_point), []).append(from_proto(c.acquisitions[0].states))
    assert sorted(by_point) == [(0,), (1,), (2,)]
    p = [np.concatenate(by_point[(i,)]).mean() for i in range(3)]
    assert p[0] < 0.05 < p[1] < p[2] and p[2] > 0.95
    assert ch[-1].is_last and sum(c.is_last for c in ch) == 1


# ---------------------------------------------------------------- D10: seams are wired
def test_t2_reads_out_through_the_physical_resonator():
    j = job([(0, "play", "xy_q0", "pi", 0.5)], 24, T2, shots=400, wf={"pi": SQ20})
    j.main.instructions[-1].acquire.mode = job_pb2.ACQUISITION_MODE_INTEGRATED
    iq = from_proto(run(IDEAL, j, DEV1)[0].acquisitions[0].iq)
    assert iq.dtype == np.complex64 and np.std(iq) > 0
    assert len(np.unique(np.round(iq, 6))) > 100      # noisy integrated points, not synthetic labels


def test_hidden_mixer_imbalance_reaches_the_qubit():
    data = DEV1.model_dump()
    data["faults"] = {"drive_mixers": [{"qubit_index": 0, "gain_i": 0.8}]}
    dev = DeviceSpec.model_validate(data)
    j = job([(0, "play", "xy_q0", "pi", 0.5)], 24, T1B, shots=3000, wf={"pi": SQ20})
    p1 = states(run(IDEAL, j, dev)).mean()
    assert_binomial(int(p1 * 3000), 3000, np.sin(0.4 * np.pi) ** 2, delta_model=0.02)


def test_device_dynamics_feed_engine_parameters():
    from qcss.runtime.runner import SimulationContext
    dev = load_device("src/qcss/config/devices/transmon_5q.yaml")
    ctx = SimulationContext(QBLOX, dev, TimeBase.from_clocks("1e9"))
    f_a, t1_a = ctx.device_parameters(lab_time_s=0.0)
    _, t1_b = ctx.device_parameters(lab_time_s=6 * 3600.0)
    assert t1_a != t1_b
    assert len(f_a) == 5


# ---------------------------------------------------------------- feedback on the real executor
def test_active_reset_through_the_runtime():
    j = job_pb2.Job(num_shots=1000, requested_tier=T1B, random_seed=3, repetition_delay_ticks=200_000)
    j.waveform_library["pi"].CopyFrom(SQ20)
    j.waveform_library["h"].CopyFrom(SQ10)
    add = j.main.instructions.add
    add(start_tick=0, play=job_pb2.Play(channel_id="xy_q0", waveform_id="h", amplitude=0.5))
    add(start_tick=12, acquire=job_pb2.Acquire(channel_id="ro_q0", integration_ticks=500, register_index=0,
                                                mode=job_pb2.ACQUISITION_MODE_DISCRIMINATED, result_key="m0"))
    br = job_pb2.Branch(sequencer_id="qcm_rf0_seq0", duration_ticks=20, condition=job_pb2.Condition(
        op=job_pb2.CONDITION_OP_EQUAL, register_indices=[0], value=1))
    br.then_block.instructions.add(start_tick=1060, play=job_pb2.Play(channel_id="xy_q0", waveform_id="pi",
                                                                       amplitude=0.5))
    add(start_tick=1060, branch=br)        # 12 + 153 (ToF) + 500 + 388 (inter-module) = 1053 <= 1060
    add(start_tick=1100, acquire=job_pb2.Acquire(channel_id="ro_q0", integration_ticks=500, register_index=1,
                                                  mode=job_pb2.ACQUISITION_MODE_DISCRIMINATED, result_key="m1"))
    ch = run(QBLOX, j)
    first, final = states(ch, "m0"), states(ch, "m1")
    assert 0.4 < first.mean() < 0.6
    assert final.mean() < 0.02


# ---------------------------------------------------------------- D11, D13: server behaviour
def test_job_manager_records_tier_and_fidelity():
    tb = TimeBase.from_clocks("1e9")

    async def go():
        jm = JobManager(create_simulation_runner(IDEAL, DEV1, tb), create_simulation_validator(IDEAL, tb, DEV1))
        jid = await jm.submit(job([(0, "play", "xy_q0", "pi", 0.5)], 24, T1A, shots=10, wf={"pi": SQ20}))
        async for _ in jm.results(jid):
            pass
        st = jm.status(jid)
        await jm.close()
        return st
    st = asyncio.run(go())
    assert st.state == result_pb2.JOB_STATE_COMPLETED
    assert st.tier_used == T1A
    assert st.noise_fidelity == result_pb2.NOISE_FIDELITY_TWIRLED


def test_event_loop_stays_responsive_during_simulation():
    tb = TimeBase.from_clocks("1e9")
    j = job([(0, "play", "xy_q0", "pi", 0.5)], 24, T2, shots=60, wf={"pi": SQ20}, repetition_delay_ticks=0)

    async def go():
        jm = JobManager(create_simulation_runner(IDEAL, DEV1, tb), create_simulation_validator(IDEAL, tb, DEV1))
        jid = await jm.submit(j)
        stalls = []
        while jm.status(jid).state not in (result_pb2.JOB_STATE_COMPLETED, result_pb2.JOB_STATE_FAILED):
            t0 = time.perf_counter()
            await asyncio.sleep(0.005)
            stalls.append(time.perf_counter() - t0)
        await jm.close()
        return jm.status(jid).state, max(stalls)
    state, worst = asyncio.run(go())
    assert state == result_pb2.JOB_STATE_COMPLETED
    assert worst < 0.1


# ---------------------------------------------------------------- calibration is uploaded once per job
def test_a_recalibration_mid_job_does_not_change_the_running_job():
    from qcss.runtime.runner import SimulationContext
    from qcss.v1 import calibration_pb2
    tb = TimeBase.from_clocks(IDEAL.clock.tick_hz)
    ctx = SimulationContext(IDEAL, DEV1, tb)
    runner = create_simulation_runner(IDEAL, DEV1, tb, chunk_size=200, context=ctx)
    j = job([(0, "play", "xy_q0", "pi", 0.5)], 24, T2, shots=400)

    async def go():
        out = []
        async for c in runner("job-under-test", j, asyncio.Event()):
            out.append(c)
            if len(out) == 1:                 # the lab detunes the drive while the job is running
                detuned = calibration_pb2.CalibrationSnapshot()
                detuned.qubits.add(qubit_index=0, drive_frequency_hz=ctx.qdef[0].f01_ghz * 1e9 + 30e6)
                ctx.calibration.update(detuned, ctx.calibration.epoch)
        return out

    chunks = asyncio.run(go())
    assert len(chunks) == 2
    assert {c.calibration_epoch for c in chunks} == {0}      # the epoch the job actually ran with
    second = np.concatenate([from_proto(a.states) for a in chunks[1].acquisitions])
    assert second.mean() > 0.9                                # still the pi pulse uploaded at start


# ---------------------------------------------------------------- the chip keeps drifting while idle
def test_lab_time_advances_with_scaled_wall_time_between_jobs():
    from qcss.runtime.runner import SimulationContext
    now = [100.0]
    ctx = SimulationContext(IDEAL, DEV1, TimeBase.from_clocks(IDEAL.clock.tick_hz),
                            time_scale=60.0, wall_clock=lambda: now[0])
    assert ctx.lab_time_s == 0.0
    now[0] += 10.0                                    # 10 s of wall time idle = 10 lab minutes
    assert ctx.lab_time_s == pytest.approx(600.0)
    ctx.lab_time_s = 1000.0                           # a job ended here: idle time counts from now on
    now[0] += 1.0
    assert ctx.lab_time_s == pytest.approx(1060.0)


def test_lab_time_is_frozen_while_idle_by_default():
    from qcss.runtime.runner import SimulationContext
    ctx = SimulationContext(IDEAL, DEV1, TimeBase.from_clocks(IDEAL.clock.tick_hz))
    first = ctx.lab_time_s
    time.sleep(0.01)
    assert ctx.lab_time_s == first


# ---------------------------------------------------------------- real hardware cannot replay shots
def test_a_realistic_chassis_ignores_the_jobs_random_seed():
    from qcss.runtime.runner import SimulationContext
    tb = TimeBase.from_clocks(IDEAL.clock.tick_hz)
    ctx = SimulationContext(IDEAL, DEV1, tb, honour_job_seed=False)
    runner = create_simulation_runner(IDEAL, DEV1, tb, context=ctx)
    half = job([(0, "play", "xy_q0", "pi", 0.25)], 24, T1B, shots=2000, seed=7)

    async def go(job_id):
        return [c async for c in runner(job_id, half, asyncio.Event())]
    a, b = asyncio.run(go("job-a")), asyncio.run(go("job-b"))
    assert not np.array_equal(states(a), states(b))


def test_job_status_carries_no_simulator_diagnostics_on_a_lab_chassis():
    tb = TimeBase.from_clocks(IDEAL.clock.tick_hz)
    runner = create_simulation_runner(IDEAL, DEV1, tb)

    async def go():
        jobs = JobManager(runner, create_simulation_validator(IDEAL, tb, DEV1), expose_diagnostics=False)
        try:
            job_id = await jobs.submit(job([(0, "play", "xy_q0", "pi", 0.5)], 24, T1A, shots=10))
            return jobs.status(job_id), jobs.info(job_id)
        finally:
            await jobs.close()
    st, info = asyncio.run(go())
    assert st.tier_used == 0 and st.noise_fidelity == 0
    assert info.tier_used == T1A                  # still known to the chassis, for the admin channel


def test_a_lab_chassis_picks_the_tier_itself_and_ignores_the_requested_one():
    from qcss.runtime.runner import SimulationContext
    tb = TimeBase.from_clocks(IDEAL.clock.tick_hz)
    ctx = SimulationContext(IDEAL, DEV1, tb, tier_policy="AUTO")
    half = job([(0, "play", "xy_q0", "pi", 0.2)], 24, T1A)           # a non-Clifford pulse, "asking" for T1A
    assert ctx.plan(half).tier == "T1B"                              # AUTO picks the exact tier, no refusal
    ctx.tier_policy = "T2"                                           # the operator raises fidelity (admin)
    assert ctx.plan(half).tier == "T2"


# ---------------------------------------------------------------- execution takes instrument time
def test_a_paced_runner_takes_the_jobs_lab_time_in_wall_time():
    from qcss.runtime.runner import SimulationContext
    from qcss.timing.instrument_time import InstrumentPacer
    tb = TimeBase.from_clocks(IDEAL.clock.tick_hz)
    ctx = SimulationContext(IDEAL, DEV1, tb)
    j = job([(0, "play", "xy_q0", "pi", 0.5)], 24, T1A, shots=2000)

    def run_once(pacer):
        runner = create_simulation_runner(IDEAL, DEV1, tb, context=ctx, pacer=pacer)
        lab0, t0 = ctx.lab_time_s, time.monotonic()
        asyncio.run(_drain_runner(runner, j))
        return ctx.lab_time_s - lab0, time.monotonic() - t0

    lab_s, _ = run_once(None)
    scale = lab_s / 0.3                               # so that this job should take 0.3 s of wall time
    _, wall_s = run_once(InstrumentPacer(lambda: scale, upload_median_s=0.0))
    assert wall_s >= 0.28


def test_a_job_that_computes_slower_than_real_time_still_ages_the_chip_by_the_wall_time(monkeypatch):
    """The lab clock never goes back: a job whose simulation outlasts its lab time leaves the chip as old as the
    wall clock says, not just as old as the job's ticks (M6)."""
    from qcss.runtime.runner import SimulationContext
    now = [0.0]
    tb = TimeBase.from_clocks(IDEAL.clock.tick_hz)
    ctx = SimulationContext(IDEAL, DEV1, tb, time_scale=1.0, wall_clock=lambda: now[0])
    real = ctx.simulate_chunk

    def slow_chunk(*args, **kwargs):
        now[0] += 10.0                                # ten wall seconds of compute for microseconds of shots
        return real(*args, **kwargs)

    monkeypatch.setattr(ctx, "simulate_chunk", slow_chunk)
    lab0 = ctx.lab_time_s
    runner = create_simulation_runner(IDEAL, DEV1, tb, context=ctx)
    asyncio.run(_drain_runner(runner, job([(0, "play", "xy_q0", "pi", 0.5)], 24, T1A, shots=100)))
    assert ctx.lab_time_s - lab0 >= 10.0


async def _drain_runner(runner, j):
    return [c async for c in runner("job-under-test", j, asyncio.Event())]


# ---------------------------------------------------------------- client-resolved sweeps (program points)
def test_program_points_each_run_their_own_program():
    j = job([], 24, T1B, shots=200)
    acquire = j.main.instructions[0]
    pi = job_pb2.Instruction(start_tick=0, play=job_pb2.Play(channel_id="xy_q0", waveform_id="pi", amplitude=0.5))
    idle_pt = j.program_points.add(indices=[0])
    idle_pt.main.instructions.add().CopyFrom(acquire)
    pi_pt = j.program_points.add(indices=[1])
    pi_pt.main.instructions.add().CopyFrom(pi)
    pi_pt.main.instructions.add().CopyFrom(acquire)
    chunks = run(IDEAL, j, DEV1)
    by_point = {tuple(c.sweep_point): states([c]).mean() for c in chunks}
    assert by_point[(0,)] < 0.05 and by_point[(1,)] > 0.95


def test_program_points_and_sweeps_are_exclusive():
    from qcss.ir.compiler import expand_sweeps
    j = job([(0, "play", "xy_q0", "pi", 0.5)], 24, T1B)
    j.program_points.add(indices=[0]).main.CopyFrom(j.main)
    j.sweeps.add(axis=0, amplitude=job_pb2.AmplitudeTarget(instruction_index=0), values=to_proto(np.array([0.1])))
    with pytest.raises(HardwareValidationError):
        expand_sweeps(j)


def test_a_virtual_z_phase_sweep_traces_a_ramsey_fringe():
    """X90 . Z(phi) . X90 as program points (Qibocal's virtual-Z phase sweep): P1 = cos^2(phi / 2)."""
    phis = np.linspace(0, 2 * np.pi, 5)
    j = job([], 60, T2, shots=1500, wf={"x90": SQ10})
    acquire = j.main.instructions[0]
    for k, phi in enumerate(phis):
        ins = j.program_points.add(indices=[k]).main.instructions
        ins.add(start_tick=0, play=job_pb2.Play(channel_id="xy_q0", waveform_id="x90", amplitude=0.5))
        ins.add(start_tick=12, shift_phase=job_pb2.ShiftPhase(frame_id="q0", delta_rad=float(phi)))
        ins.add(start_tick=12, play=job_pb2.Play(channel_id="xy_q0", waveform_id="x90", amplitude=0.5))
        ins.add().CopyFrom(acquire)
    for c in run(IDEAL, j, DEV1):
        phi = phis[c.sweep_point[0]]
        p1 = states([c]).mean()
        assert_binomial(round(p1 * 1500), 1500, np.cos(phi / 2) ** 2, delta_model=0.03)


def _flux_during_pi(tier: int) -> job_pb2.Job:
    j = job([], 60, tier, shots=400, wf={"pi": SQ20, "fx": job_pb2.Waveform(
        shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=40)})
    acquire = j.main.instructions[0]
    acquire.acquire.integration_ticks = 1000
    for k, a in enumerate((0.0, 0.4)):
        ins = j.program_points.add(indices=[k]).main.instructions
        ins.add(start_tick=0, play=job_pb2.Play(channel_id="flux_q0", waveform_id="fx", amplitude=a))
        ins.add(start_tick=8, play=job_pb2.Play(channel_id="xy_q0", waveform_id="pi", amplitude=0.5))
        ins.add().CopyFrom(acquire)
    return j


@pytest.mark.parametrize("tier", [T2, job_pb2.FIDELITY_TIER_AUTO])
def test_a_flux_offset_detunes_the_qubit_from_its_drive(tier):
    """Flux spectroscopy (Qibocal's offset sweeps): a flux pulse during the pi pulse moves the qubit off its drive."""
    dev = load_device("src/qcss/config/devices/transmon_5q.yaml")
    p1 = {c.sweep_point[0]: states([c]).mean() for c in run(QBLOX, _flux_during_pi(tier), dev)}
    assert p1[0] > 0.85 and p1[1] < 0.3


def test_gate_tiers_refuse_pulses_that_overlap_on_a_qubit():
    """Lifting pulses one at a time would drop the flux shift under the drive: refuse instead of being wrong."""
    dev = load_device("src/qcss/config/devices/transmon_5q.yaml")
    with pytest.raises(TierRoutingError):
        run(QBLOX, _flux_during_pi(T1B), dev)


def test_a_repeated_flux_pulse_is_lifted_once_per_chunk(monkeypatch):
    """Chevron scans repeat one flux pulse every shot: lift it once and frame-shift it (exact, see lifter)."""
    from qcss.feedback import executor
    calls = []
    real = executor.lift_multi

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)
    monkeypatch.setattr(executor, "lift_multi", counting)
    dev = load_device("src/qcss/config/devices/transmon_5q.yaml")
    j = job([(0, "play", "xy_q0", "pi", 0.5), (24, "play", "flux_q0", "fx", 0.3)], 100, T1B, shots=50,
            wf={"pi": SQ20, "fx": job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=40)})
    j.main.instructions[-1].acquire.integration_ticks = 1000
    run(QBLOX, j, dev)
    assert len(calls) <= 2                       # once in the planning dry run, once in the chunk


def test_a_cz_chevron_scan_is_simulated_with_leakage():
    """Flux on q1 sweeping |11> through the |20> resonance (Qibocal's chevron): the leaky points need T2."""
    from qcss.runtime.runner import SimulationContext
    dev = load_device("src/qcss/config/devices/transmon_5q.yaml")
    j = job([(0, "play", "xy_q0", "pi", 0.5)], 24, job_pb2.FIDELITY_TIER_AUTO, shots=10,
            wf={"pi": SQ20, "fx": job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=60)})
    base = list(j.main.instructions)
    del j.main.instructions[:]
    for k, a in enumerate(np.linspace(0.30, 0.42, 25)):
        ins = j.program_points.add(indices=[k]).main.instructions
        ins.add().CopyFrom(base[0])
        ins.add(start_tick=0, play=job_pb2.Play(channel_id="xy_q1", waveform_id="pi", amplitude=0.5))
        ins.add(start_tick=24, play=job_pb2.Play(channel_id="flux_q1", waveform_id="fx", amplitude=float(a)))
        acq = ins.add()
        acq.CopyFrom(base[1])
        acq.start_tick = 100
    ctx = SimulationContext(QBLOX, dev, TimeBase.from_clocks("1e9"))
    assert ctx.plan(j).tier == "T2"
    j.requested_tier = T1B
    with pytest.raises(TierRoutingError, match="leak"):
        ctx.plan(j)


def test_a_readout_frame_frequency_sets_that_points_probe_frequency():
    """Resonator spectroscopy: each point's probe NCO decides where the resonator is probed."""
    from qcss.runtime.runner import SimulationContext
    ctx = SimulationContext(IDEAL, DEV1, TimeBase.from_clocks(IDEAL.clock.tick_hz))
    lo = IDEAL.port(ctx.bindings["ro_q0"].port_id).lo_frequency_hz or 0.0
    f_ro = ctx.calibration.snapshot().qubits[0].readout_frequency_hz
    j = job([], 24, T2, shots=200)
    acquire = j.main.instructions[0]
    acquire.acquire.mode = job_pb2.ACQUISITION_MODE_INTEGRATED
    for k, f in enumerate((f_ro, f_ro + 20e6)):
        ins = j.program_points.add(indices=[k]).main.instructions
        ins.add(start_tick=0, set_frequency=job_pb2.SetFrequency(frame_id="ro_q0", frequency_hz=f - lo))
        ins.add().CopyFrom(acquire)
    runner = create_simulation_runner(IDEAL, DEV1, ctx.tb, context=ctx)
    chunks = asyncio.run(_drain_runner(runner, j))
    iq = {c.sweep_point[0]: np.mean(from_proto(c.acquisitions[0].iq)) for c in chunks}
    assert abs(iq[0] - iq[1]) > 0.3 * max(abs(iq[0]), abs(iq[1]))


def test_planning_does_not_simulate_readout(monkeypatch):
    """The planning dry run only lifts pulses; readout physics is for the shots (and costly at a QICK tick)."""
    from qcss.readout import model
    from qcss.runtime.runner import SimulationContext

    def boom(*args, **kwargs):
        raise AssertionError("readout simulated while planning")
    monkeypatch.setattr(model.PhysicalReadout, "acquire", boom)
    monkeypatch.setattr(model.SurrogateReadout, "acquire", boom)
    ctx = SimulationContext(IDEAL, DEV1, TimeBase.from_clocks(IDEAL.clock.tick_hz))
    assert ctx.plan(job([(0, "play", "xy_q0", "pi", 0.5)], 24, T1B)).tier == "T1B"


def test_the_gate_tier_chip_is_as_warm_as_the_device_file_says():
    """transmon_5q sits at T_eff 60 mK: an idle qubit reads |1> about 1.7 % of the time, not never."""
    dev = load_device("src/qcss/config/devices/transmon_5q.yaml")
    j = job([], 24, T1B, shots=4000)
    j.main.instructions[0].acquire.integration_ticks = 2000
    p1 = states(run(QBLOX, j, dev)).mean()
    assert 0.008 < p1 < 0.04
