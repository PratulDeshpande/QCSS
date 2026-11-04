"""The QICK face's Pyro4 pickle serializer: QICK's wire format, without pickle's code execution.

QICK runs Pyro4 with ``SERIALIZER = "pickle"`` (protocol 4), so a client can only talk to a board in
pickle. A real QickSoc server unpickles whatever it is sent, which lets anyone who reaches it run code on
the board. This serializer decodes the same messages but resolves only an allowlist of globals: plain
data, numpy arrays, dtypes and scalars, ``OrderedDict``, Pyro URIs and exception classes. That is all a
QICK client (programs, envelopes, register dicts) or the nameserver (URIs, naming errors) ever sends. Any
other global, ``os.system`` or ``builtins.eval`` included, is refused before it can be called.

``install()`` swaps it in for Pyro4's pickle serializer, which Pyro4 keeps in one process-wide table, so
it covers the daemon and this process's own nameserver calls alike.
"""
from __future__ import annotations

import builtins
import io
import pickle
from typing import Any

import Pyro4.errors
import Pyro4.util

_SAFE_BUILTINS = frozenset({"bool", "bytearray", "bytes", "complex", "dict", "float", "frozenset", "int", "list",
                            "range", "set", "slice", "str", "tuple", "NoneType"})
# numpy 1.x pickles name numpy.core, numpy 2.x numpy._core: a client PC may run either. Protocol 4 (QICK's)
# rebuilds arrays with _reconstruct; protocol 5 (Pyro's default) with _frombuffer, which only wraps bytes.
_NUMPY = frozenset({(f"numpy.{core}.multiarray", name) for core in ("core", "_core") for name in ("_reconstruct", "scalar")}
                   | {(f"numpy.{core}.numeric", "_frombuffer") for core in ("core", "_core")}
                   | {("numpy", "ndarray"), ("numpy", "dtype")})
_ALLOWED = (_NUMPY | {("builtins", n) for n in _SAFE_BUILTINS}
            | {("collections", "OrderedDict"), ("Pyro4.core", "URI")})


def _is_exception_class(module: str, name: str) -> bool:
    """Exception classes (a nameserver's NamingError, a KeyError): building one runs no code."""
    if module not in ("builtins", "Pyro4.errors"):
        return False
    obj = getattr(builtins if module == "builtins" else Pyro4.errors, name, None)
    return isinstance(obj, type) and issubclass(obj, BaseException)


class _Unpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> Any:
        if (module, name) in _ALLOWED or _is_exception_class(module, name):
            return super().find_class(module, name)
        raise pickle.UnpicklingError(f"global '{module}.{name}' is forbidden")


def _loads(data: bytes) -> Any:
    return _Unpickler(io.BytesIO(data)).load()


class RestrictedPickleSerializer(Pyro4.util.PickleSerializer):
    """Pyro4's pickle serializer (same id, same encoder) with an allowlisting decoder."""

    def loadsCall(self, data: Any) -> Any:
        return _loads(self._convertToBytes(data))

    def loads(self, data: Any) -> Any:
        return _loads(self._convertToBytes(data))


def install() -> None:
    """Use the restricted serializer for every pickle message this process sends or receives."""
    ser = RestrictedPickleSerializer()
    Pyro4.util._serializers["pickle"] = ser                        # type: ignore[attr-defined]
    Pyro4.util._serializers_by_id[ser.serializer_id] = ser         # type: ignore[attr-defined]
