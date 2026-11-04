"""The virtual QICK board on the network: a Pyro4 daemon serving QcssQickSoc, as ``qick.pyro.start_server``
serves a real QickSoc.

A QICK user starts a Pyro4 nameserver (``pyro4-ns -n 0.0.0.0 -p 8888``, or ``qick.pyro.start_nameserver``),
the board registers its QickSoc there under a proxy name, and ``qick.pyro.make_proxy`` finds it. This
module does the board's half the same way, with the same Pyro4 settings (pickle, protocol 4, no
REQUIRE_EXPOSE), so the only thing that tells a lab's board from this one is its address. Two things
differ by design and are invisible to a well-behaved client:

- messages are decoded by the allowlisting serializer (``serializer.py``): a pickle gadget is refused;
- an error's remote traceback is the board's: the Pyro4 frame and the qick frame of the method called,
  at the pinned qick's source lines, never this simulator's files.
"""
from __future__ import annotations

import inspect
import json
import threading
import traceback
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import Pyro4
import Pyro4.naming

from qcss.boards.qick import serializer
from qcss.boards.qick.soc import QcssQickSoc

# site-packages of the PYNQ 3.0 image's Python 3.10 venv, where a board's qick and Pyro4 live
BOARD_SITE = "/usr/local/share/pynq-venv/lib/python3.10/site-packages"
_SURFACE = json.loads((Path(__file__).with_name("surface.json")).read_text(encoding="utf-8"))
_PYRO_CALL_LINE = 1424           # Pyro4 4.82 core.py: "data = method(*vargs, **kwargs)" in handleRequest
_SERVED_CODE = {fn.__code__: name for name, fn in inspect.getmembers(QcssQickSoc, inspect.isfunction)
                if not name.startswith("_")}


def configure_pyro() -> None:
    """Pyro4 as qick.pyro configures it, with the allowlisting serializer in place of pickle's decoder."""
    config: Any = Pyro4.config        # its settings are typed by their defaults; Pyro4 means them to be changed
    config.SERIALIZER = "pickle"
    config.SERIALIZERS_ACCEPTED = {"pickle"}
    config.PICKLE_PROTOCOL_VERSION = 4
    config.REQUIRE_EXPOSE = False
    serializer.install()


def _served_method(exc: BaseException) -> str | None:
    tb = exc.__traceback__
    name = None
    while tb is not None:
        name = _SERVED_CODE.get(tb.tb_frame.f_code, name)
        tb = tb.tb_next
    return name


def board_traceback(exc: BaseException, lines: Mapping[str, list[Any]] = _SURFACE["source_lines"]) -> list[str]:
    """The traceback a real board's Pyro daemon would send for ``exc``, as Pyro4's formatTraceback lines."""
    frames = [(f'  File "{BOARD_SITE}/Pyro4/core.py", line {_PYRO_CALL_LINE}, in handleRequest\n'
               "    data = method(*vargs, **kwargs)  # this is the actual method call to the Pyro object\n")]
    method = _served_method(exc)
    if method is not None and method in lines:
        rel, line = lines[method]
        frames.append(f'  File "{BOARD_SITE}/qick/{rel}", line {line}, in {method}\n')
    return ["Traceback (most recent call last):\n", *frames, *traceback.format_exception_only(type(exc), exc)]


class _BoardDaemon(Pyro4.Daemon):
    def _sendExceptionResponse(self, connection, seq, serializer_id, exc_value, tbinfo,
                               flags=0, annotations=None):
        super()._sendExceptionResponse(connection, seq, serializer_id, exc_value, board_traceback(exc_value),
                                       flags, annotations)


class _Loop:
    def __init__(self, daemon: Pyro4.Daemon) -> None:
        self.daemon = daemon
        self.thread = threading.Thread(target=daemon.requestLoop, name="qick-pyro", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.daemon.shutdown()
        self.thread.join(timeout=5)
        self.daemon.close()


def start_nameserver(address: str) -> _Loop:
    """A Pyro4 nameserver at ``host:port`` accepting pickle, as ``qick.pyro.start_nameserver`` runs one."""
    configure_pyro()
    host, port = address.rsplit(":", 1)
    _, daemon, _ = Pyro4.naming.startNS(host=host, port=int(port), enableBroadcast=False)
    return _Loop(daemon)


class QickBoardHost:
    """Serves one QcssQickSoc and registers it with a nameserver under ``name`` (QICK's proxy_name)."""

    def __init__(self, soc: QcssQickSoc, ns_address: str, name: str = "myqick", host: str = "127.0.0.1",
                 port: int = 0) -> None:
        self.soc, self._ns, self._name, self._host, self._port = soc, ns_address, name, host, port
        self._loop: _Loop | None = None

    def start(self) -> None:
        configure_pyro()
        ns_host, ns_port = self._ns.rsplit(":", 1)
        ns = Pyro4.locateNS(host=ns_host, port=int(ns_port))
        daemon = _BoardDaemon(host=self._host, port=self._port)
        ns.register(self._name, daemon.register(self.soc))
        self._loop = _Loop(daemon)

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.stop()
            self._loop = None
