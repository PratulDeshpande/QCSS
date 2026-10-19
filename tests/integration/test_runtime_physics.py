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
