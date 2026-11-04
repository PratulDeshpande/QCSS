"""Generator and readout register models: what a QICK client wrote, read back in physical units.

The oracle is the client itself: qick compiles a program against the firmware description and
configures an in-process board with it (``config_all``, no network). The interpreter replays the
program's port writes, and the models must recover the frequencies, gains, phases, lengths and
envelopes the program declared, from register values alone.
"""
# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("qick")
from qick import QickConfig
from qick.asm_v2 import AveragerProgramV2

from qcss.boards.qick.firmware import description
from qcss.boards.qick.gens import pulse_of
from qcss.boards.qick.readouts import readout_of
from qcss.boards.qick.soc import QcssQickSoc
from qcss.boards.qick.tproc_v2_run import run

CFG = description("zcu216_v2_5q")
SOCCFG = QickConfig(CFG)
MUX, RO = 10, [7150.0, 7280.0]


class Probe(AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_gen(ch=0, nqz=2)
        self.declare_gen(ch=1, nqz=1)
        self.declare_gen(ch=5, nqz=1)
        self.declare_gen(ch=MUX, nqz=2, ro_ch=0, mux_freqs=RO, mux_gains=[0.3, 0.6], mux_phases=[0, 90])
        for q, f in enumerate(RO):
            self.declare_readout(ch=q, length=1.0, freq=f, gen_ch=MUX)
        self.add_pulse(ch=0, name="x", style="const", freq=4500, phase=45, length=0.05, gain=0.5)
        self.add_gauss(ch=1, name="g", sigma=0.01, length=0.04)
        self.add_pulse(ch=1, name="y", style="arb", envelope="g", freq=3000, phase=0, gain=0.25)
        self.add_pulse(ch=5, name="z", style="const", freq=0, phase=0, length=0.1, gain=-0.4)
        self.add_pulse(ch=MUX, name="probe", style="const", length=1.0, mask=[1])

    def _body(self, cfg):
        self.pulse(ch=0, name="x", t=0)
        self.pulse(ch=1, name="y", t=0)
        self.pulse(ch=5, name="z", t=0)
        self.pulse(ch=MUX, name="probe", t=0.2)
        self.trigger(ros=[0, 1], t=0.3)


@pytest.fixture(scope="module")
def board():
    soc = QcssQickSoc(CFG)
    prog = Probe(SOCCFG, reps=1, final_delay=1.0, cfg={})
    prog.config_all(soc)
    soc.config_avg(0, length=prog.ro_chs[0]["length"])
    pulses = {e.port: e for e in run(soc.state.binprog).events if e.kind == "pulse"}
    return soc, prog, pulses


def test_a_constant_pulse_reads_back_as_its_frequency_phase_gain_and_length(board):
    soc, _, pulses = board
    p = pulse_of(soc.state.gens[0], pulses[0].wave)
    assert p.tones[0].freq_hz == pytest.approx(4500e6, abs=2.0)          # 1.6 Hz register resolution
    assert np.degrees(p.tones[0].phase_rad) == pytest.approx(45, abs=1e-6)
    assert p.tones[0].amplitude == pytest.approx(0.5, abs=1 / 32766)
    assert p.n_samples == round(0.05 * 430.08) * 16                      # whole fabric cycles of 16 samples
    assert p.envelope is None                                            # outsel "dds": a flat DDS tone


def test_a_first_zone_tone_is_not_folded(board):
    soc, _, pulses = board
    assert pulse_of(soc.state.gens[1], pulses[1].wave).tones[0].freq_hz == pytest.approx(3000e6, abs=2.0)


def test_an_arbitrary_pulse_plays_the_envelope_it_was_given_scaled_by_its_gain(board):
    soc, prog, pulses = board
    p = pulse_of(soc.state.gens[1], pulses[1].wave)
    env = prog.envelopes[1]["envs"]["g"]["data"]                       # int16 (n, 2) as uploaded
    assert p.envelope is not None and len(p.envelope) == p.n_samples == env.shape[0]
    want = (env[:, 0] + 1j * env[:, 1]) / 32766
    np.testing.assert_allclose(p.envelope, want, atol=1e-12)
    assert p.tones[0].amplitude == pytest.approx(0.25, abs=1 / 32766)


def test_a_negative_gain_keeps_its_sign(board):
    soc, _, pulses = board
    assert pulse_of(soc.state.gens[5], pulses[5].wave).tones[0].amplitude == pytest.approx(-0.4, abs=1 / 32766)


def test_a_mux_pulse_plays_the_tones_its_mask_selects(board):
    soc, _, pulses = board
    p = pulse_of(soc.state.gens[MUX], pulses[MUX].wave)
    assert len(p.tones) == 1                                             # mask=[1]: the second tone only
    t = p.tones[0]
    assert t.freq_hz == pytest.approx(7280e6, abs=2e3)
    assert t.amplitude == pytest.approx(0.6, abs=1 / 32766)
    assert np.degrees(t.phase_rad) == pytest.approx(90, abs=1e-6)
    assert p.n_samples == round(1.0 * 430.08) * 16


def test_a_readout_reads_back_its_frequency_and_window(board):
    soc, prog, _ = board
    r = readout_of(soc.state.readouts[0])
    assert r.freq_hz == pytest.approx(7150e6, abs=1e3)
    assert r.sample_rate_hz == pytest.approx(76.8e6)
    assert r.length == prog.ro_chs[0]["length"] == round(1.0 * 76.8)
    assert readout_of(soc.state.readouts[1]).freq_hz == pytest.approx(7280e6, abs=1e3)


def test_an_unconfigured_readout_has_no_frequency():
    soc = QcssQickSoc(CFG)
    assert readout_of(soc.state.readouts[3]).freq_hz is None
