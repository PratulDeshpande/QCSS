"""The native QICK face end to end: a real Pyro4 nameserver, the virtual board, and an unmodified qick
client in its own process, as a user's PC would run it.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import textwrap

import pytest

pytest.importorskip("qick")
pytest.importorskip("Pyro4")

from qcss.boards.qick.firmware import description
from qcss.boards.qick.pyro_host import QickBoardHost, start_nameserver
from qcss.boards.qick.soc import QcssQickSoc

CONNECT = """
import sys
from qick.pyro import make_proxy
soc, soccfg = make_proxy(ns_host="127.0.0.1", ns_port=int(sys.argv[1]), proxy_name="myqick", remote_traceback=False)
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def ns_port():
    port = _free_port()
    ns = start_nameserver(f"127.0.0.1:{port}")
    host = QickBoardHost(QcssQickSoc(description("zcu216_v2_5q")), ns_address=f"127.0.0.1:{port}", name="myqick")
    host.start()
    yield port
    host.stop()
    ns.stop()


def _client(script: str, port: int) -> subprocess.CompletedProcess[str]:
    out = subprocess.run([sys.executable, "-c", CONNECT + textwrap.dedent(script), str(port)], capture_output=True,
                         text=True, timeout=120, check=False)
    assert out.returncode == 0, out.stderr
    return out


def test_a_qick_client_connects_and_sees_a_zcu216(ns_port):
    out = _client("print(soccfg)", ns_port)
    assert "QICK running on ZCU216" in out.stdout
    assert "11 signal generator channels" in out.stdout


def test_a_qick_program_configures_the_board_as_on_hardware(ns_port):
    out = _client("""
        from qick.asm_v2 import AveragerProgramV2
        RO = [7150.0, 7280.0, 7020.0, 7400.0, 7210.0]     # the chip's resonators, as a user would have them
        class P(AveragerProgramV2):
            def _initialize(self, cfg):
                self.declare_gen(ch=10, nqz=2, ro_ch=0, mux_freqs=RO, mux_gains=[0.2]*5)
                for q in range(5):
                    self.declare_readout(ch=q, length=1.0, freq=RO[q], gen_ch=10)
                self.declare_gen(ch=0, nqz=2)
                self.add_pulse(ch=10, name="probe", style="const", length=1.0, mask=[0, 1, 2, 3, 4])
                self.add_pulse(ch=0, name="pi", style="const", freq=4500, phase=0, length=0.05, gain=0.5)
            def _body(self, cfg):
                self.pulse(ch=0, name="pi", t=0)
                self.pulse(ch=10, name="probe", t=0.1)
                self.trigger(ros=[0, 1, 2, 3, 4], pins=[0], t=0.1)
        prog = P(soccfg, reps=10, final_delay=50.0, cfg={})
        prog.config_all(soc)
        print("configured", soc.get_tproc_counter(addr=1))
    """, ns_port)
    assert "configured 0" in out.stdout


def test_a_board_error_reaches_the_client_as_the_real_boards_traceback(ns_port):
    out = _client("""
        import Pyro4
        try:
            soc.get_tproc_counter(addr=7)
        except KeyError:
            print("TB<<" + "".join(Pyro4.util.getPyroTraceback()) + ">>")
    """, ns_port)
    tb = out.stdout.split("TB<<", 1)[1].split(">>", 1)[0]
    remote = tb.split("Remote traceback:", 1)[1]           # Pyro frames the board's lines with " | "
    assert "site-packages/qick/qick.py" in remote and "in get_tproc_counter" in remote
    assert "| KeyError: 7\n +--- End of remote traceback" in remote
    # the local frames are the client's own (here this repo's venv); the board controls only the remote part
    assert "qcss" not in remote.lower() and "QCS_SIL_SIM" not in remote


def test_the_chassis_serves_the_qick_board_and_a_reboot_wipes_what_was_uploaded():
    import asyncio
    import threading

    from qcss.admin.v1 import admin_pb2 as apb
    from qcss.chassis import Chassis, ChassisConfig
    from qcss.config.loader import load_device, load_profile

    port = _free_port()
    chassis = Chassis(ChassisConfig(
        profile=load_profile("src/qcss/config/profiles/qick_zcu216_5q.yaml"),
        device=load_device("src/qcss/config/devices/transmon_5q.yaml"), lab_address=f"127.0.0.1:{_free_port()}",
        time_scale=0.0, seed=40, qick_ns=f"127.0.0.1:{port}", qick_name="myqick", qick_start_ns=True))
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    asyncio.run_coroutine_threadsafe(chassis.start(), loop).result(30)
    try:
        out = _client("""
            soc.load_bin_program({"pmem": [[0] * 8], "wmem": None, "dmem": None})
            print("uploaded", len(soc.get_cfg()["readouts"]))
        """, port)
        assert "uploaded 5" in out.stdout
        assert chassis.qick_soc is not None and chassis.qick_soc.state.binprog is not None
        assert chassis.faults is not None
        chassis.faults.inject(apb.INSTRUMENT_FAULT_REBOOT)
        assert chassis.qick_soc.state.binprog is None            # the FPGA forgot; the chip did not
    finally:
        asyncio.run_coroutine_threadsafe(chassis.stop(), loop).result(30)
        loop.call_soon_threadsafe(loop.stop)


def test_a_pickle_gadget_is_refused_and_the_board_keeps_serving(ns_port, tmp_path):
    marker = tmp_path / "pwned"
    out = _client(f"""
        import os
        class Gadget:
            def __reduce__(self):
                return (os.system, ("echo x > {marker.as_posix()}",))
        try:
            soc.load_bin_program(Gadget())
            print("ACCEPTED")
        except Exception as exc:
            print("REFUSED", type(exc).__name__)
        print("still serving", len(soc.get_cfg()["gens"]))
    """, ns_port)
    assert "REFUSED" in out.stdout and "ACCEPTED" not in out.stdout
    assert "still serving 11" in out.stdout
    assert not marker.exists()


def test_a_client_acquires_a_rabi_sweep_over_the_wire_from_the_chassis():
    import asyncio
    import threading

    from qcss.chassis import Chassis, ChassisConfig
    from qcss.config.loader import load_device, load_profile

    port = _free_port()
    chassis = Chassis(ChassisConfig(
        profile=load_profile("src/qcss/config/profiles/qick_zcu216_5q.yaml"),
        device=load_device("src/qcss/config/devices/transmon_5q.yaml"), lab_address=f"127.0.0.1:{_free_port()}",
        time_scale=0.0, seed=40, qick_ns=f"127.0.0.1:{port}", qick_name="myqick", qick_start_ns=True))
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    asyncio.run_coroutine_threadsafe(chassis.start(), loop).result(30)
    try:
        out = _client("""
            import numpy as np
            from qick.asm_v2 import AveragerProgramV2, QickSweep1D
            class Rabi(AveragerProgramV2):
                def _initialize(self, cfg):
                    self.declare_gen(ch=10, nqz=2, ro_ch=0, mux_freqs=[7150.0], mux_gains=[0.5])
                    self.declare_readout(ch=0, length=1.0, freq=7150.0, gen_ch=10)
                    self.add_pulse(ch=10, name="probe", style="const", length=1.0, mask=[0])
                    self.declare_gen(ch=0, nqz=2)
                    self.add_loop("amp", 6)
                    self.add_pulse(ch=0, name="x", style="const", freq=5050.0, phase=0, length=0.1,
                                   gain=QickSweep1D("amp", 0.0, 1.0))
                def _body(self, cfg):
                    self.pulse(ch=0, name="x", t=0)
                    self.delay_auto(0.02)
                    self.pulse(ch=10, name="probe", t=0)
                    self.trigger(ros=[0], t=0.3)
            prog = Rabi(soccfg, reps=200, final_delay=50.0, cfg={})
            iq = prog.acquire(soc, progress=False)[0][0]
            dec = Rabi(soccfg, reps=1, final_delay=50.0, cfg={}).acquire_decimated(soc, progress=False)
            print("SHAPE", iq.shape, len(dec), dec[0].shape, soc.get_tproc_counter(addr=1))
            print("FINITE", bool(np.all(np.isfinite(iq))))
        """, port)
        assert "SHAPE (6, 2) 1 (6, 77, 2) 6" in out.stdout and "FINITE True" in out.stdout
    finally:
        asyncio.run_coroutine_threadsafe(chassis.stop(), loop).result(30)
        loop.call_soon_threadsafe(loop.stop)
