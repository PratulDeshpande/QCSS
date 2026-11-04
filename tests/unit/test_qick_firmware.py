"""The native QICK face's firmware description, checked by the real qick client.

The client is the specification: a description a real ZCU216 would never report makes QickConfig, the
program compiler or the readout declaration fail here exactly as it would for a user.
"""
from __future__ import annotations

import logging
import subprocess
import sys

import pytest

qick = pytest.importorskip("qick")
from qick import QickConfig

from qcss.boards.qick.firmware import FIRMWARES, description
from qcss.config.loader import load_device

DRIVE, FLUX, MUX = range(5), range(5, 10), 10
QUBITS = range(5)
DEVICES = __import__("pathlib").Path(__file__).resolve().parents[2] / "src/qcss/config/devices"
# the chip's readout resonators (true values: a test may know them, the face never does), MHz by qubit
RESONATORS_MHZ = [r.f_r_ghz * 1e3 for r in sorted(load_device(DEVICES / "transmon_5q.yaml").resonators,
                                                   key=lambda r: r.qubit_index)]


@pytest.mark.parametrize("name", sorted(FIRMWARES))
def test_the_board_can_read_out_this_chip_with_one_pfb_channel_per_resonator(name):
    from qick.asm_v2 import AveragerProgramV2
    from qick.averager_program import AveragerProgram

    soccfg = QickConfig(description(name))
    if soccfg["tprocs"][0]["type"] == "qick_processor":
        class P(AveragerProgramV2):
            def _initialize(self, cfg):
                self.declare_gen(ch=MUX, nqz=2, ro_ch=0, mux_freqs=RESONATORS_MHZ, mux_gains=[0.2] * 5)
                for q in QUBITS:
                    self.declare_readout(ch=q, length=1.0, freq=RESONATORS_MHZ[q], gen_ch=MUX)
                self.add_pulse(ch=MUX, name="probe", style="const", length=1.0, mask=list(QUBITS))

            def _body(self, cfg):
                self.pulse(ch=MUX, name="probe", t=0)
                self.trigger(ros=list(QUBITS), pins=[0], t=0)

        prog = P(soccfg, reps=1, final_delay=1.0, cfg={})
    else:
        class P1(AveragerProgram):
            def initialize(self):
                self.declare_gen(ch=MUX, nqz=2, ro_ch=0, mux_freqs=RESONATORS_MHZ, mux_gains=[0.2] * 5)
                for q in QUBITS:
                    self.declare_readout(ch=q, length=300, freq=RESONATORS_MHZ[q], gen_ch=MUX)
                self.set_pulse_registers(ch=MUX, style="const", length=300, mask=list(QUBITS))
                self.synci(200)

            def body(self):
                self.measure(pulse_ch=MUX, adcs=list(QUBITS), adc_trig_offset=50, wait=True,
                             syncdelay=self.us2cycles(10))

        prog = P1(soccfg, {"reps": 1})
    from qcss.boards.qick.soc import QcssQickSoc
    # the PFB collision check runs when the readouts are configured, not at compile time
    prog.config_all(QcssQickSoc(description(name)))   # raises "Two tones on same PFB channel" on a collision
    assert prog.binprog is not None


@pytest.mark.parametrize("name", sorted(FIRMWARES))
def test_the_board_introduces_itself_as_a_zcu216_running_the_pinned_software(name):
    text = str(QickConfig(description(name)))
    assert f"QICK running on ZCU216, software version {qick.get_version()}" in text
    assert "11 signal generator channels" in text
    assert "5 readout channels" in text


@pytest.mark.parametrize("name", sorted(FIRMWARES))
def test_a_client_of_the_pinned_version_sees_no_version_mismatch(name, caplog):
    with caplog.at_level(logging.WARNING, logger="qick"):
        QickConfig(description(name))
    assert "version mismatch" not in caplog.text


@pytest.mark.parametrize("name", sorted(FIRMWARES))
def test_the_wiring_is_the_chip_every_other_face_sees(name):
    cfg = description(name)
    gens, ros = cfg["gens"], cfg["readouts"]
    assert [g["type"] for g in gens] == ["axis_signal_gen_v6"] * 10 + ["axis_sg_mux8_v1"]
    assert all(gens[i]["fs"] == pytest.approx(6881.28) for i in (*DRIVE, *FLUX, MUX))
    assert gens[MUX]["n_tones"] == 8
    assert [r["ro_type"] for r in ros] == ["axis_pfb_readout_v4"] * 5
    assert len({r["adc"] for r in ros}) == 1                       # one feedline, one ADC


def test_each_call_returns_a_fresh_copy():
    a = description("zcu216_v2_5q")
    a["gens"].clear()
    assert len(description("zcu216_v2_5q")["gens"]) == 11


def test_an_unknown_firmware_is_refused_with_the_known_ones_listed():
    with pytest.raises(KeyError, match="zcu216_v2_5q"):
        description("zcu111_v9")


def test_the_face_never_imports_the_qick_client():
    code = "import sys, qcss.boards.qick.firmware as f; f.description('zcu216_v2_5q'); print('qick' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_a_tproc_v2_program_reads_all_five_qubits_through_the_mux():
    from qick.asm_v2 import AveragerProgramV2, QickSweep1D

    class Rabi(AveragerProgramV2):
        def _initialize(self, cfg):
            self.declare_gen(ch=MUX, nqz=1, ro_ch=0, mux_freqs=[5000 + 100 * q for q in QUBITS],
                             mux_gains=[0.2] * 5)
            for q in QUBITS:
                self.declare_readout(ch=q, length=1.0, freq=5000 + 100 * q, gen_ch=MUX)
                self.declare_gen(ch=DRIVE[q], nqz=2)
            self.add_loop("amp", 11)
            self.add_pulse(ch=MUX, name="probe", style="const", length=1.0, mask=list(QUBITS))
            for q in QUBITS:
                self.add_pulse(ch=DRIVE[q], name=f"pi{q}", style="const", freq=4500 + 10 * q, phase=0,
                               length=0.05, gain=QickSweep1D("amp", 0.0, 1.0))

        def _body(self, cfg):
            for q in QUBITS:
                self.pulse(ch=DRIVE[q], name=f"pi{q}", t=0)
            # qick 0.2.370 annotates t as int, but tProc v2 times are float microseconds (its tutorials pass 0.1)
            self.pulse(ch=MUX, name="probe", t=0.1)  # pyright: ignore[reportArgumentType]
            self.trigger(ros=list(QUBITS), pins=[0], t=0.1)  # pyright: ignore[reportArgumentType]

    prog = Rabi(QickConfig(description("zcu216_v2_5q")), reps=100, final_delay=50.0, cfg={})
    assert prog.binprog["pmem"]
    assert list(prog.ro_chs) == list(QUBITS)


def test_a_tproc_v1_averager_program_reads_all_five_qubits_through_the_mux():
    from qick.averager_program import AveragerProgram

    class Spec(AveragerProgram):
        def initialize(self):
            self.declare_gen(ch=MUX, nqz=1, ro_ch=0, mux_freqs=[5000 + 100 * q for q in QUBITS],
                             mux_gains=[0.2] * 5)
            for q in QUBITS:
                self.declare_readout(ch=q, length=300, freq=5000 + 100 * q, gen_ch=MUX)
            self.set_pulse_registers(ch=MUX, style="const", length=300, mask=list(QUBITS))
            self.synci(200)

        def body(self):
            self.measure(pulse_ch=MUX, adcs=list(QUBITS), adc_trig_offset=50, wait=True,
                         syncdelay=self.us2cycles(10))

    soccfg = QickConfig(description("zcu216_v1_5q"))
    prog = Spec(soccfg, {"reps": 100})
    prog.compile()                                 # v1 fills prog.binprog
    assert prog.binprog is not None and len(prog.binprog) > 0
    assert list(prog.ro_chs) == list(QUBITS)


def test_v1_generators_sit_on_the_tprocs_axis_channels_clear_of_the_trigger_register():
    # qick_216.hwh: m1_axis drives axis_set_reg (channel 0, the trigger bits); m2..m8 (channels 1-7) drive
    # generators. Eleven generators need a tProc mux on one channel; the mux readout gen keeps its own.
    cfg = description("zcu216_v1_5q")
    slots = [(g["tproc_ch"], g.get("tmux_ch")) for g in cfg["gens"]]
    assert len(set(slots)) == len(slots)
    assert all(1 <= ch <= 7 for ch, _ in slots)
    assert all(r["trigger_type"] == "output" and r["trigger_port"] == 0 for r in cfg["readouts"])
    assert cfg["gens"][10]["tproc_ch"] not in {ch for ch, t in slots[:10]}
