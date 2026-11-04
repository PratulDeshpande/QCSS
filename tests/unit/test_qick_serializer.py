"""The QICK face's pickle serializer: wire-compatible with QICK's Pyro4 pickle, minus code execution.

A real QickSoc server unpickles whatever a client sends, so anyone who can reach it can run code on the
board. The virtual board accepts exactly the data QICK clients and the Pyro4 nameserver send.
"""
from __future__ import annotations

import builtins
import os
import pickle
from collections import OrderedDict

import numpy as np
import pytest

Pyro4 = pytest.importorskip("Pyro4")

from qcss.boards.qick.serializer import RestrictedPickleSerializer, install

PROTOCOL = 4                                     # QICK's Pyro4.config.PICKLE_PROTOCOL_VERSION


def _roundtrip(obj):
    return RestrictedPickleSerializer().loads(pickle.dumps(obj, PROTOCOL))


@pytest.mark.parametrize("obj", [
    None, True, 7, 2.5, 1 + 2j, "internal", b"\x00\x01", (1, "a"), [1, 2], {"a": 1}, {1, 2}, frozenset({3}),
    OrderedDict([(0, {"freq": 1})]), range(3), slice(1, 5),
], ids=repr)
def test_plain_python_data_passes_unchanged(obj):
    assert _roundtrip(obj) == obj


def test_a_compiled_tproc_v2_program_passes_with_its_numpy_arrays():
    binprog = {"pmem": np.arange(16, dtype=np.int32).reshape(2, 8), "wmem": None, "dmem": np.zeros(4, np.int32)}
    out = _roundtrip(binprog)
    assert out["pmem"].dtype == np.int32 and np.array_equal(out["pmem"], binprog["pmem"])
    assert out["wmem"] is None


def test_numpy_scalars_and_complex_envelopes_pass():
    out = _roundtrip({"addr": np.int64(3), "env": np.ones((4, 2), dtype=np.int16), "c": np.complex128(1j)})
    assert out["addr"] == 3 and out["env"].dtype == np.int16 and out["c"] == 1j


def test_a_pyro_uri_from_the_nameserver_passes():
    uri = Pyro4.URI("PYRO:obj_1@127.0.0.1:9999")
    assert _roundtrip(uri) == uri


class _RunsShell:
    def __reduce__(self):
        return (os.system, ("echo pwned",))


class _Evals:
    def __reduce__(self):
        return (builtins.eval, ("1+1",))


@pytest.mark.parametrize("gadget", [_RunsShell(), _Evals()], ids=["os.system", "builtins.eval"])
def test_a_code_execution_gadget_is_refused_before_it_runs(gadget):
    with pytest.raises(pickle.UnpicklingError, match="forbidden"):
        _roundtrip({"binprog": gadget})


def test_a_pyro_call_message_is_decoded():
    data = Pyro4.util.PickleSerializer().dumpsCall("obj_1", "load_bin_program", (np.zeros(2, np.int32),),
                                                   {"load_mem": False})
    obj, method, vargs, kwargs = RestrictedPickleSerializer().loadsCall(data)
    assert (obj, method, kwargs) == ("obj_1", "load_bin_program", {"load_mem": False})
    assert np.array_equal(vargs[0], [0, 0])


def test_install_puts_the_restricted_serializer_in_place_of_pyros_pickle():
    install()
    install()                                    # idempotent
    assert isinstance(Pyro4.util.get_serializer("pickle"), RestrictedPickleSerializer)
    assert isinstance(Pyro4.util.get_serializer_by_id(RestrictedPickleSerializer.serializer_id),
                      RestrictedPickleSerializer)
