"""QcssQickSoc, the object the virtual board serves: the real QickSoc's remote surface, method for method.

Pyro4 runs with REQUIRE_EXPOSE off (as qick.pyro.start_server sets it), so every public name is callable
remotely: a public name the real board lacks, or a signature that differs, is visible to a client.
"""
from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from qcss.boards.qick.firmware import description
from qcss.boards.qick.soc import NOT_YET_SERVED, QcssQickSoc

SURFACE = json.loads((Path(__file__).resolve().parents[2] / "src/qcss/boards/qick/surface.json").read_text())
REAL = SURFACE["objects"]["soc"]


def _public(cls) -> dict[str, Callable[..., object]]:
    return {n: m for n, m in inspect.getmembers(cls, inspect.isfunction) if not n.startswith("_")}


@pytest.fixture
def soc():
    return QcssQickSoc(description("zcu216_v2_5q"))


def test_every_public_method_is_one_the_real_board_has():
    assert set(_public(QcssQickSoc)) - set(REAL) == set()


def test_every_served_method_has_the_real_signature():
    for name, fn in _public(QcssQickSoc).items():
        params = list(inspect.signature(fn).parameters.values())[1:]
        got = [{"name": p.name, "default": "<required>" if p.default is p.empty else p.default} for p in params]
        assert got == REAL[name], name


def test_every_real_method_is_served_or_tracked_as_not_yet_served():
    served = set(_public(QcssQickSoc))
    assert served.isdisjoint(NOT_YET_SERVED)
    assert served | set(NOT_YET_SERVED) == set(REAL)


def test_every_call_a_qick_program_makes_is_served_or_tracked():
    for call in SURFACE["client_calls"]:
        assert call in _public(QcssQickSoc) or call in NOT_YET_SERVED, call


def test_get_cfg_is_the_firmware_description_and_a_fresh_copy(soc):
    cfg = soc.get_cfg()
    assert cfg == description("zcu216_v2_5q")
    cfg["gens"].clear()
    assert len(soc.get_cfg()["gens"]) == 11


def test_a_loaded_program_is_kept_until_the_board_reboots(soc):
    soc.load_bin_program({"pmem": [[0] * 8], "wmem": None, "dmem": None}, load_mem=True)
    assert soc.state.binprog is not None
    soc._reboot()
    assert soc.state.binprog is None


def test_a_v2_program_is_cast_to_int32_words_as_the_driver_does(soc):
    soc.load_bin_program({"pmem": [[1, 2, 3, 4, 5, 6, 7, 8]], "wmem": [[9] * 8], "dmem": None})
    assert soc.state.binprog["pmem"].dtype == np.int32
    assert soc.state.binprog["wmem"].dtype == np.int32


def test_a_v2_word_above_2_31_is_wrapped_to_32_bits_as_the_boards_numpy_does(soc):
    # a 7 GHz frequency word on a 6.88 Gsps generator exceeds 2**31: the board's numpy 1.x wraps the
    # int32 cast silently, and the tProc reads the same 32 bits either way
    soc.load_bin_program({"pmem": [[0] * 8], "wmem": [[2**32 - 5, 2**31, 0, 0, 0, 0, 0, 0]], "dmem": None})
    assert soc.state.binprog["wmem"][0, :2].tolist() == [-5, -(2**31)]


def test_envelopes_and_generator_settings_are_remembered_per_channel(soc):
    env = np.ones((32, 2), dtype=np.int16)
    soc.load_envelope(ch=3, data=env, addr=0)
    soc.set_nyquist(ch=3, nqz=2)
    soc.config_mux_gen(ch=10, tones=[{"freq_int": 1, "gain_int": 2}])
    assert np.array_equal(soc.state.gens[3].envelope[:32], env)
    assert soc.state.gens[3].nqz == 2
    assert soc.state.gens[10].tones == [{"freq_int": 1, "gain_int": 2}]


def test_the_v2_counter_has_two_addresses_like_the_tprocs_axi_registers(soc):
    soc.clear_tproc_counter(addr=1)
    assert soc.get_tproc_counter(addr=1) == 0
    with pytest.raises(KeyError):
        soc.get_tproc_counter(addr=3)


def test_start_src_takes_the_real_sources_only(soc):
    soc.start_src("external")
    assert soc.state.start_src == "external"
    with pytest.raises(RuntimeError, match="start_src must be internal or external, got bogus"):
        soc.start_src("bogus")                     # the tProc v2 driver's words


def test_an_envelope_beyond_the_generators_memory_is_refused_in_the_drivers_words(soc):
    with pytest.raises(RuntimeError, match=r"AxisSignalGen: buffer length must be 65536 samples or less\."):
        soc.load_envelope(ch=0, data=np.zeros((16, 2), np.int16), addr=65530)


def test_a_mixer_frequency_on_a_generator_without_a_mixer_is_refused(soc):
    with pytest.raises(NotImplementedError, match="This channel does not have a mixer."):
        soc.set_mixer_freq(ch=0, f=1000.0)


def test_a_nyquist_zone_other_than_1_or_2_is_refused(soc):
    with pytest.raises(RuntimeError, match="Nyquist zone must be 1 or 2"):
        soc.set_nyquist(ch=0, nqz=3)
