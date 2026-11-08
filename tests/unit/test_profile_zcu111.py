"""Unit tests for the ZCU111 RFSoC hardware profiles (qick_zcu111_5q and qick_zcu111_4q)."""
from __future__ import annotations

import pytest

from qcss.config.loader import load_device, load_profile
from qcss.core.timebase import TimeBase
from qcss.feedback.latency import FeedbackLatencyResolver
from qcss.ir.compiler import build_bindings
from qcss.ir.program import Acquire, ChannelBinding, ChannelKind, Play, Program
from qcss.ir.validator import Validator

PROFILE_5Q = "src/qcss/config/profiles/qick_zcu111_5q.yaml"
PROFILE_4Q = "src/qcss/config/profiles/qick_zcu111_4q.yaml"
DEVICE_5Q = "src/qcss/config/devices/transmon_5q.yaml"


def test_zcu111_5q_profile_structure():
    prof = load_profile(PROFILE_5Q)
    assert prof.profile_name == "qick_zcu111_5q"
    assert prof.vendor == "qick"
    assert float(prof.clock.tick_hz) == 30720.0e6

    # ZCU111 XCZU28DR has 8 DACs on the XM500 balun board
    assert len(prof.ports) == 8
    port_ids = [p.port_id for p in prof.ports]
    assert port_ids == [f"dac{i}" for i in range(8)]

    # 5 drive DACs (dac0..4, rf_direct), 2 flux DACs (dac5..6, baseband),
    # 1 readout mux DAC (dac7, rf_direct, max_generators=5)
    ports = {p.port_id: p for p in prof.ports}
    for i in range(5):
        assert ports[f"dac{i}"].kind == "rf_direct"
        assert ports[f"dac{i}"].max_generators == 1
    assert ports["dac5"].kind == "baseband"
    assert ports["dac6"].kind == "baseband"
    assert ports["dac7"].kind == "rf_direct"
    assert ports["dac7"].max_generators == 5

    # Generators: 5 drive, 2 flux, 5 readout mux tones = 12 total generators
    assert len(prof.generators) == 12
    readout_gens = [g for g in prof.generators if g.is_readout]
    drive_flux_gens = [g for g in prof.generators if not g.is_readout]
    assert len(readout_gens) == 5
    assert len(drive_flux_gens) == 7

    for g in prof.generators:
        assert float(g.sample_rate_hz) == 6144.0e6
        assert g.rt_granularity_ticks == 80  # 1 tProc cycle at 384 MHz
        assert g.wave_granularity_samples == 16


def test_zcu111_4q_profile_structure():
    prof = load_profile(PROFILE_4Q)
    assert prof.profile_name == "qick_zcu111_4q"
    assert float(prof.clock.tick_hz) == 30720.0e6
    assert len(prof.ports) == 2
    assert len(prof.generators) == 2
    assert prof.generators[0].generator_id == "gen0"
    assert not prof.generators[0].is_readout
    assert prof.generators[1].generator_id == "ro_gen0"
    assert prof.generators[1].is_readout


def test_zcu111_acquisition_and_feedback():
    prof = load_profile(PROFILE_5Q)
    # 80 ticks per ADC fabric cycle (384 MHz)
    assert prof.acquisition.integration_granularity_ticks == 80
    assert "discriminated" in prof.acquisition.modes

    # Feedback latency: 5760 ticks = 187.5 ns (Stefanazzi et al. RSI 2022: 184-211 ns)
    resolver = FeedbackLatencyResolver(prof)
    for ro_gen in ["ro_gen0", "ro_gen1", "ro_gen2", "ro_gen3", "ro_gen4"]:
        for xy_gen in ["gen0", "gen1", "gen2", "gen3", "gen4"]:
            lat = resolver.latency_ticks(ro_gen, xy_gen)
            assert lat == 5760


def test_zcu111_validation_accepts_grid_and_granularity():
    prof = load_profile(PROFILE_5Q)
    tb = TimeBase.from_clocks(prof.clock.tick_hz)
    validator = Validator(prof, tb)

    # Valid program: start at tick 80 (multiple of 80), duration 80 ticks (multiple of 80 / wave gen 16),
    # acquire duration 960 ticks (multiple of 80)
    bindings = {
        "xy_q0": ChannelBinding("xy_q0", ChannelKind.DRIVE, "gen0", "dac0", "q0", (0,)),
        "ro_q0": ChannelBinding("ro_q0", ChannelKind.READOUT, "ro_gen0", "dac7", "ro_q0", (0,))
    }
    prog = Program(
        bindings=bindings,
        waveforms={"pi": 16},  # 16 samples = 80 ticks at 6144 Msps
        ops=[
            Play("p0", "xy_q0", 80, 80, "pi", 0.8),
            Acquire("a0", "ro_q0", 160, 960, "discriminated", register=0)
        ]
    )
    report = validator.validate(prog)
    assert report.ok, f"Expected valid, got violations: {report.violations}"


def test_zcu111_validation_rejects_misaligned_grid():
    prof = load_profile(PROFILE_5Q)
    tb = TimeBase.from_clocks(prof.clock.tick_hz)
    validator = Validator(prof, tb)

    bindings = {
        "xy_q0": ChannelBinding("xy_q0", ChannelKind.DRIVE, "gen0", "dac0", "q0", (0,))
    }
    # start = 50 is NOT a multiple of rt_granularity_ticks (80)
    prog = Program(
        bindings=bindings,
        waveforms={"pi": 16},
        ops=[Play("p0", "xy_q0", 50, 80, "pi", 0.8)]
    )
    report = validator.validate(prog)
    assert not report.ok
    assert any("granularity" in v[1].lower() or "grid" in v[1].lower() for v in report.violations)


def test_zcu111_validation_rejects_misaligned_acquisition():
    prof = load_profile(PROFILE_5Q)
    tb = TimeBase.from_clocks(prof.clock.tick_hz)
    validator = Validator(prof, tb)

    bindings = {
        "ro_q0": ChannelBinding("ro_q0", ChannelKind.READOUT, "ro_gen0", "dac7", "ro_q0", (0,))
    }
    # integration = 950 is NOT a multiple of integration_granularity_ticks (80)
    prog = Program(
        bindings=bindings,
        waveforms={},
        ops=[Acquire("a0", "ro_q0", 80, 950, "discriminated", register=0)]
    )
    report = validator.validate(prog)
    assert not report.ok
    assert any("not a multiple of" in v[1].lower() or "granularity" in v[1].lower() for v in report.violations)


def test_zcu111_qibosoq_board_wiring_and_job():
    from qcss.boards.qibosoq import BoardWiring, request_to_job
    prof = load_profile(PROFILE_5Q)
    dev = load_device(DEVICE_5Q)
    bindings = build_bindings(prof, dev)
    wiring = BoardWiring.from_bindings(bindings)

    # dac 0..4 are drive, dac 5..6 are flux
    assert 0 in wiring.dac and wiring.dac[0].channel_id == "xy_q0"
    assert 5 in wiring.dac
    assert 6 in wiring.dac
    # adc 0..4 mapped to ro_q0..4
    for q in range(5):
        assert q in wiring.adc
        assert wiring.adc[q].channel_id == f"ro_q{q}"

    req = {
        "operation_code": 1,
        "cfg": {"relaxation_time": 50.0, "ro_time_of_flight": 200, "reps": 50, "soft_avgs": 1, "average": False},
        "sequence": [
            {"type": "drive", "frequency": 5050.0, "start_delay": 0.0, "duration": 0.04, "adc": 0, "dac": 0,
             "amplitude": 0.5, "relative_phase": 0.0, "name": "rx", "shape": "gaussian", "rel_sigma": 5.0},
            {"type": "readout", "frequency": 7150.0, "start_delay": 0.04, "duration": 1.0, "adc": 0, "dac": 7,
             "amplitude": 0.1, "relative_phase": 0.0, "name": "mz", "shape": "rectangular"}
        ],
        "qubits": [{"bias": 0.0, "dac": 5}, {"bias": 0.0, "dac": 6}]
    }
    bj = request_to_job(req, wiring, prof)
    assert bj.job.num_shots == 50
    assert len(bj.job.program_points) == 1
    # Verify clock conversion
    tick_rate = 30720.0e6
    pt = bj.job.program_points[0]
    acq_instr = next(i for i in pt.main.instructions if i.WhichOneof("op") == "acquire")
    expected_start = round(0.04e-6 * tick_rate / 80) * 80
    assert acq_instr.start_tick == expected_start


@pytest.mark.parametrize("profile, firmware", [
    ("qick_zcu216_5q", "zcu216_v2_5q"), ("qick_zcu216_4q", "zcu216_v1_5q"),
    ("qick_zcu111_5q", "zcu111_v2_5q"), ("qick_zcu111_4q", "zcu111_v1_5q"),
])
def test_the_acquisition_grid_fits_the_boards_readout_clocks(profile, firmware):
    from qcss.boards.qick.firmware import description
    prof = load_profile(f"src/qcss/config/profiles/{profile}.yaml")
    tb = TimeBase.from_clocks(prof.clock.tick_hz)
    readout = description(firmware)["readouts"][0]
    grid = prof.acquisition.integration_granularity_ticks
    assert grid == tb.ticks_per(f"{readout['f_fabric']}e6")        # one ADC fabric cycle
    assert tb.ticks_per(f"{readout['f_output']}e6") % grid == 0    # whole PFB samples land on the grid


def test_zcu111_firmware_descriptions():
    from qcss.boards.qick.firmware import FIRMWARES, description
    assert "zcu111_v2_5q" in FIRMWARES
    assert "zcu111_v1_5q" in FIRMWARES

    for fw_name in ["zcu111_v2_5q", "zcu111_v1_5q"]:
        cfg = description(fw_name)
        assert cfg["board"] == "ZCU111"
        assert len(cfg["gens"]) == 8
        assert len(cfg["readouts"]) == 5
        # All DACs running at 6144.0 Msps, fabric 384.0 MHz
        assert all(g["fs"] == 6144.0 for g in cfg["gens"])
        assert all(g["f_fabric"] == 384.0 for g in cfg["gens"])
        # Readout ADC 3072.0 Msps decimated by PFB (64-ch, 32-down) to 96.0 MHz (320 ticks)
        assert all(r["fs"] == 3072.0 for r in cfg["readouts"])
        assert all(r["f_dds"] == 96.0 for r in cfg["readouts"])


def test_zcu111_tproc_v2_translation():
    pytest.importorskip("qick")
    from qick import QickConfig
    from qick.asm_v2 import AveragerProgramV2, QickSweep1D

    from qcss.boards.qick.firmware import description
    from qcss.boards.qick.soc import QcssQickSoc
    from qcss.boards.qick.tproc_v2_run import run
    from qcss.boards.qick.translate import translate

    prof = load_profile(PROFILE_5Q)
    dev = load_device(DEVICE_5Q)
    bindings = build_bindings(prof, dev)

    soccfg = QickConfig(description("zcu111_v2_5q"))
    mux_ch = len(soccfg["gens"]) - 1  # 7 for ZCU111

    class RabiZCU111(AveragerProgramV2):
        def _initialize(self, cfg):
            self.declare_gen(ch=0, nqz=2)
            self.declare_gen(ch=mux_ch, nqz=2, ro_ch=0, mux_freqs=[7150.0], mux_gains=[0.3])
            self.declare_readout(ch=0, length=1.0, freq=7150.0, gen_ch=mux_ch)
            self.add_pulse(ch=mux_ch, name="probe", style="const", length=1.0, mask=[0])
            self.add_loop("amp", 3)
            self.add_pulse(ch=0, name="pi", style="const", freq=4500, phase=0, length=0.05,
                           gain=QickSweep1D("amp", 0, 1))

        def _body(self, cfg):
            self.pulse(ch=0, name="pi", t=0)
            # qick 0.2.370 annotates t as int, but tProc v2 times are float microseconds
            self.delay_auto(0.01)  # pyright: ignore[reportArgumentType]
            self.pulse(ch=mux_ch, name="probe", t=0)
            self.trigger(ros=[0], pins=[0], t=0.05)  # pyright: ignore[reportArgumentType]
            self.wait_auto()
            self.delay_auto(1.0)  # pyright: ignore[reportArgumentType]

    soc = QcssQickSoc(soccfg._cfg)
    prog = RabiZCU111(soccfg, reps=2, final_delay=1.0, cfg={})
    prog.config_all(soc)
    prog.config_bufs(soc, enable_avg=True, enable_buf=False)

    tr = translate(run(soc.state.binprog), soc.state, bindings, prof)
    assert len(tr.jobs) == 1
    job = tr.jobs[0]
    assert len(job.program_points) == 3
    assert job.num_shots == 2
