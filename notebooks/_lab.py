"""Start and stop a simulated lab (`qcss serve`) for the tutorial notebooks.

The lab runs as its own process, as a real board or cluster does: the notebook reaches it only over the
network faces the client libraries already speak (Pyro4 for QICK, gRPC for Qibolab, TCP/JSON for qibosoq).
The ports are the official tutorials' defaults, so the connect cells stay as upstream wrote them.
"""
from __future__ import annotations

import atexit
import os
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GRPC_PORT, ADMIN_PORT, QICK_NS_PORT, BOARD_PORT = 50051, 50052, 8888, 6000
ADMIN_TOKEN = "tutorial-admin-token"    # loopback only; the admin channel refuses calls without it
_CLI = [sys.executable, "-c", "from qcss.cli import app; app()"]


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


@dataclass
class Lab:
    """A running `qcss serve`; `admin(...)` drives its admin channel, `truth()` reads the real chip."""

    proc: subprocess.Popen
    ports: list[int]
    log: Path
    env: dict[str, str] = field(default_factory=dict)

    def admin(self, *args: str) -> str:
        """Run `qcss admin <args>` against this lab and return its printed output."""
        out = subprocess.run([*_CLI, "admin", *args, "--target", f"127.0.0.1:{ADMIN_PORT}"],
                             capture_output=True, text=True, env={**os.environ, "QCSS_ADMIN_TOKEN": ADMIN_TOKEN})
        if out.returncode:
            raise RuntimeError(f"qcss admin {' '.join(args)} failed:\n{out.stdout}{out.stderr}")
        return out.stdout

    def truth(self) -> list[dict]:
        """The chip as it really is, one dict per qubit (frequency_hz, t1_s, dead): what no real lab can read."""
        import grpc

        from qcss.admin.v1 import admin_pb2 as apb
        from qcss.admin.v1 import admin_pb2_grpc as apbg

        with grpc.insecure_channel(f"127.0.0.1:{ADMIN_PORT}") as ch:
            t = apbg.AdminServiceStub(ch).ReadTruth(apb.ReadTruthRequest(), timeout=30,
                                                    metadata=(("authorization", f"Bearer {ADMIN_TOKEN}"),))
        return [{"qubit": q.qubit_index, "frequency_hz": q.frequency_hz, "t1_s": q.t1_s, "dead": q.dead}
                for q in t.qubits]

    def stop(self) -> None:
        if self.proc.poll() is None:
            if os.name == "nt":     # a venv python.exe is a launcher with the real interpreter as its child
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)], capture_output=True)
            else:
                self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(10)
        deadline = time.monotonic() + 10
        while any(_port_open(p) for p in self.ports) and time.monotonic() < deadline:
            time.sleep(0.2)
        for k in self.env:
            os.environ.pop(k, None)


def keep_errors_visible() -> None:
    """qick's make_proxy routes every IPython exception to stderr (to print Pyro's remote traceback), so a failing
    cell no longer *fails* and nbmake passes a broken notebook. Keep the remote traceback and fail the cell too."""
    import Pyro4.util
    from IPython.core.getipython import get_ipython

    ip = get_ipython()
    if ip is None:
        return

    def handler(self, etype, evalue, tb, tb_offset=None):
        if hasattr(evalue, "_pyroTraceback"):
            sys.stderr.write("".join(Pyro4.util.getPyroTraceback(etype, evalue, tb)))
        self.showtraceback((etype, evalue, tb), tb_offset=tb_offset)

    ip.set_custom_exc((Exception,), handler)


def start(profile: str = "qick_zcu216_5q", device: str = "transmon_5q", *, qick: bool = False,
          qibosoq: bool = False, firmware: str = "zcu216_v2_5q", loopback: tuple[str, ...] = (),
          seed: int | None = 1234, deterministic: bool = False, state_dir: str | None = None,
          extra: tuple[str, ...] = (), timeout: float = 60.0) -> Lab:
    """Start `qcss serve` with the faces asked for and wait until every port answers."""
    ports = [GRPC_PORT, ADMIN_PORT] + ([QICK_NS_PORT] if qick else []) + ([BOARD_PORT] if qibosoq else [])
    busy = [p for p in ports if _port_open(p)]
    if busy:
        raise RuntimeError(f"ports {busy} are already in use: another lab (or kernel) is still running; stop it first")
    args = ["serve", "--profile", profile, "--device", device, "--port", str(GRPC_PORT),
            "--admin-listen", f"127.0.0.1:{ADMIN_PORT}", "--admin-token", ADMIN_TOKEN]
    if seed is not None:
        args += ["--seed", str(seed)]
    if deterministic:
        args.append("--deterministic")
    if state_dir:
        args += ["--state-dir", state_dir]
    if qick:
        args += ["--qick-ns", f"127.0.0.1:{QICK_NS_PORT}", "--qick-start-ns", "--qick-firmware", firmware]
        for cable in loopback:
            args += ["--qick-loopback", cable]
    if qibosoq:
        args += ["--board-listen", f"127.0.0.1:{BOARD_PORT}"]
    log = Path(tempfile.gettempdir()) / f"qcss-lab-{os.getpid()}.log"
    proc = subprocess.Popen([*_CLI, *args, *extra], cwd=REPO, env={**os.environ, "PYTHONUNBUFFERED": "1"},
                            stdout=log.open("w"), stderr=subprocess.STDOUT)
    exports = {"QIBOLAB_PLATFORMS": str(REPO / "platforms"),
               "QCSS_QBLOX_5Q_ADDRESS": f"127.0.0.1:{GRPC_PORT}",
               "QCSS_RFSOC_5Q_ADDRESS": f"127.0.0.1:{BOARD_PORT}"}
    lab = Lab(proc, ports, log, exports)
    atexit.register(lab.stop)
    deadline = time.monotonic() + timeout
    while not all(_port_open(p) for p in ports):
        if proc.poll() is not None or time.monotonic() > deadline:
            lab.stop()
            raise RuntimeError(f"qcss serve did not come up; its log:\n{log.read_text()}")
        time.sleep(0.2)
    os.environ.update(exports)
    print(f"Lab up: profile {profile}, device {device}" + (f", QICK board {firmware}" if qick else "")
          + (", qibosoq board" if qibosoq else ""))
    return lab
