"""QcssQickSoc: the object the virtual QICK board serves over Pyro4, in place of qick's QickSoc.

Every public method has the real QickSoc's name and signature (``surface.json``, frozen from the pinned
qick) and fails the way the real one does, in its words: a client cannot tell from a call or an error
which board it reached. ``qick.pyro.start_server`` turns REQUIRE_EXPOSE off, so every public name here
is remotely callable; anything private starts with an underscore.

The board keeps what the FPGA keeps (program memory, envelope memories, generator and readout settings,
counters) in ``state``, and loses all of it when the board reboots (``_reboot``), as a power cycle does.
The real board's other methods are listed in ``NOT_YET_SERVED`` until the face serves them.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from qcss.boards.qick.results import ChassisLink, Round, start_round

# Real QickSoc methods (and the tproc/streamer properties) the face does not serve yet. Execution and
# readout (start_tproc, start_readout, poll_data, get_*) arrive with the tProc emulators; the unit
# helpers QickSoc inherits from QickConfig (freq2reg, us2cycles, ...) and the hardware extras (DDR4, MR
# buffer, time taggers, clocks, attenuators) after that. tests/unit/test_qick_soc.py keeps this in step
# with surface.json, so a qick upgrade that adds a method shows up here.
NOT_YET_SERVED = frozenset({
    "tproc", "streamer",
    "load_mem", "read_mem",
    "adcfreq", "calc_fstep", "calc_fstep_int", "calc_mixer_freq", "calc_muxgen_regs", "calc_ro_freq",
    "calc_ro_regs", "ch_fstep", "check_pfb_collisions", "cycles2us", "deg2int", "deg2reg", "description",
    "dump_cfg", "freq2int", "freq2reg", "freq2reg_adc", "get_maxv", "int2deg", "int2freq", "reg2deg",
    "reg2freq", "reg2freq_adc", "roundfreq", "us2cycles",
    "arm_ddr4", "arm_mr", "clear_ddr4", "get_ddr4", "get_mr", "clocks_locked", "config_clocks",
    "freeze_adc_cals", "unfreeze_adc_cals", "get_adc_attenuator", "set_adc_attenuator", "get_sample_rates",
    "map_signal_paths", "round_sample_rate", "set_all_clks", "set_iq", "tt_arm", "tt_config", "tt_disarm",
    "tt_readmem", "tt_reset", "valid_sample_rates",
})

# the qick driver class behind each firmware block type: its name is in the driver's error messages
_DRIVER = {"axis_signal_gen_v6": "AxisSignalGen", "axis_sg_mux8_v1": "AxisSgMux8V1"}
_V2_COUNTERS = (1, 2)            # tProc v2's two AXI-readable registers (axi_r_dt1, axi_r_dt2)


@dataclass
class GenState:
    cfg: dict[str, Any]
    envelope: np.ndarray | None = None            # (maxlen, 2) int16 I/Q, allocated on first load
    nqz: int | None = None
    tones: list[Any] | None = None                # mux generators: register dicts from calc_muxgen_regs


@dataclass
class ReadoutState:
    cfg: dict[str, Any]
    regs: Any = None                              # tProc-less readout registers (configure_readout)
    pfb: Any = None                               # PFB output configuration (config_mux_readout)
    avg: dict[str, Any] | None = None
    buf: dict[str, Any] | None = None
    enabled: tuple[bool, bool] = (False, False)   # (accumulated, decimated) capture


@dataclass
class BoardState:
    gens: list[GenState]
    readouts: list[ReadoutState]
    binprog: Any = None
    mem_loaded: bool = False
    start_src: str = "internal"
    running: bool = False
    counters: dict[int, int] = field(default_factory=dict)   # v2: AXI registers; v1: data-memory words
    tproc_cfg: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def power_on(cls, cfg: dict[str, Any]) -> BoardState:
        return cls([GenState(copy.deepcopy(g)) for g in cfg["gens"]],
                   [ReadoutState(copy.deepcopy(r)) for r in cfg["readouts"]], tproc_cfg=copy.deepcopy(cfg["tprocs"][0]))


class QcssQickSoc:
    """What a QICK client's ``soc`` proxy reaches."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self._cfg = copy.deepcopy(cfg)
        self._tproc_version = {"axis_tproc64x32_x8": 1, "qick_processor": 2}[cfg["tprocs"][0]["type"]]
        self.state = BoardState.power_on(self._cfg)
        self._link: ChassisLink | None = None
        self._round: Round | None = None
        self._stream: tuple[int, list[int], list[int]] | None = None

    def _attach(self, link: ChassisLink) -> None:
        """Connect the board's outputs and inputs to the chassis (the chip on the other end of the cables)."""
        self._link = link

    def _reboot(self) -> None:
        """A power cycle: the FPGA forgets everything it was given (the chip does not)."""
        self.state = BoardState.power_on(self._cfg)
        self._round, self._stream = None, None

    # -- configuration ---------------------------------------------------------------------------------

    def get_cfg(self):
        return copy.deepcopy(self._cfg)

    def start_src(self, src):
        if src not in ("internal", "external"):
            if self._tproc_version == 1:
                raise KeyError(src)                        # the v1 driver looks src up in a dict
            raise RuntimeError(f"start_src must be internal or external, got {src}")
        self.state.start_src = src

    def stop_tproc(self, lazy=False):
        if self._tproc_version == 2 or not lazy:
            self.state.running = False

    def start_tproc(self):
        if self._tproc_version == 2 and self.state.start_src != "internal":
            return                                     # armed: it starts on the external trigger
        if self.state.binprog is None:
            raise RuntimeError("no program loaded")
        self._round = start_round(self.state, self._link)
        self.state.running = True

    def load_bin_program(self, binprog, load_mem=True):
        if self._tproc_version == 1:
            prog: Any = np.array(binprog, dtype=np.uint64)
        else:
            # the driver casts with np.array(v, dtype=np.int32): numpy 1.x (a board's) wraps words >= 2**31
            # silently where numpy 2 raises, so wrap explicitly: the tProc reads the same 32 bits either way
            prog = {k: None if v is None else np.asarray(v, dtype=np.int64).astype(np.int32)
                    for k, v in dict(binprog).items()}
        self.state.binprog, self.state.running = prog, False
        self.state.mem_loaded = bool(load_mem)

    def reload_mem(self):
        if self._tproc_version == 2:
            self.state.mem_loaded = True

    def reset_gens(self):
        self.state.running = False                      # a zero-output program runs and ends

    def load_envelope(self, ch, data, addr):
        gen = self.state.gens[ch]
        data = np.array(data, dtype=np.int16)
        maxlen = gen.cfg.get("maxlen")
        if maxlen is None:
            raise AttributeError(f"'{_DRIVER.get(gen.cfg['type'], gen.cfg['type'])}' object has no attribute 'load'")
        if data.shape[0] + addr > maxlen:
            raise RuntimeError(f"{_DRIVER[gen.cfg['type']]}: buffer length must be {maxlen} samples or less.")
        if not gen.cfg["complex_env"] and np.any(data[:, 1]):
            raise NotImplementedError("This channel does not support complex envelopes.")
        if gen.envelope is None:
            gen.envelope = np.zeros((maxlen, 2), dtype=np.int16)
        gen.envelope[addr:addr + data.shape[0]] = data

    def set_nyquist(self, ch, nqz, force=False):
        if nqz not in [1, 2]:
            raise RuntimeError("Nyquist zone must be 1 or 2")
        self.state.gens[ch].nqz = nqz

    def set_mixer_freq(self, ch, f, ro_ch=None, phase_reset=True):
        self.state.gens[ch]
        raise NotImplementedError("This channel does not have a mixer.")    # no generator of these builds has one

    def config_mux_gen(self, ch, tones):
        gen = self.state.gens[ch]
        if len(tones) > gen.cfg["n_tones"]:
            raise RuntimeError("Too many tones defined for this mux generator.")
        gen.tones = list(tones)

    def config_mux_readout(self, pfbpath, cfgs, sel=None):
        ros = [r for r in self.state.readouts if r.cfg.get("ro_fullpath") == pfbpath]
        if not ros:
            raise AttributeError(f"'QickSoc' object has no attribute '{pfbpath}'")
        if not ros[0].cfg["has_outsel"] and sel is not None:
            raise RuntimeError(f"this readout doesn't support configuring sel, you have sel={sel}")
        for c in cfgs:
            for r in ros:
                if r.cfg["pfb_port"] == c["pfb_port"]:
                    r.pfb = dict(c)

    def configure_readout(self, ch, ro_regs):
        self.state.readouts[ch].regs = ro_regs

    def load_weights(self, ch, data, addr=0):
        self.state.readouts[ch]
        raise KeyError("wgt_maxlen")                   # no avg buffer of these builds has a weights memory

    def config_avg(self, ch, address=0, length=1, edge_counting=False, high_threshold=1000, low_threshold=0):
        self.state.readouts[ch].avg = {"address": address, "length": length, "edge_counting": edge_counting,
                                       "high_threshold": high_threshold, "low_threshold": low_threshold}

    def config_buf(self, ch, address=0, length=1):
        self.state.readouts[ch].buf = {"address": address, "length": length}

    def enable_buf(self, ch, enable_avg=True, enable_buf=True):
        self.state.readouts[ch].enabled = (bool(enable_avg), bool(enable_buf))

    # -- rounds and counters ---------------------------------------------------------------------------

    def clear_tproc_counter(self, addr):
        if self._tproc_version == 1:
            self.state.counters[addr] = 0
        else:
            self.state.counters = dict.fromkeys(_V2_COUNTERS, 0)   # a v2 tProc reset zeroes all registers
            self.state.running = False
        self._round = None

    def get_tproc_counter(self, addr):
        if self._tproc_version == 2 and addr not in _V2_COUNTERS:
            raise KeyError(addr)                       # the v2 driver maps addr to axi_r_dt1/2 with a dict
        rnd = self._round
        if rnd is None or addr != 1:
            return self.state.counters.get(addr, 0)
        seen = rnd.counter
        rnd.wait(lambda: rnd.counter != seen, 0.005)   # a register read over the bus takes its time
        if rnd.error is not None:
            raise RuntimeError("exception in readout loop") from rnd.error
        return rnd.counter

    # -- readout buffers ------------------------------------------------------------------------------

    def get_accumulated(self, ch, address=0, length=None):
        ro = self.state.readouts[ch]
        if length is None:
            length = ro.cfg["avg_maxlen"]
        if length >= ro.cfg["avg_maxlen"]:
            raise RuntimeError(f"length={length:d} longer than {ro.cfg['avg_maxlen']:d}")
        if self._round is None:
            return np.zeros((length, 2), dtype=np.int32)
        return self._round.ring(ch, address, length)

    def get_decimated(self, ch, address=0, length=None):
        ro = self.state.readouts[ch]
        if length is None:
            length = ro.cfg["buf_maxlen"]
        if length >= ro.cfg["buf_maxlen"]:
            raise RuntimeError(f"requested length={length:d} longer or equal to decimated buffer size="
                               f"{ro.cfg['buf_maxlen']:d}")
        if self._round is None:
            return np.zeros((length, 2), dtype=np.int16)
        buf = self._round.dec[ch]
        return np.take(buf, np.arange(address, address + length) % len(buf), axis=0)

    def start_readout(self, total_shots, counter_addr=1, ch_list=None, reads_per_shot=1, stride=None):
        if ch_list is None:
            ch_list = [0, 1]
        ch_list = list(ch_list)
        if isinstance(reads_per_shot, int):
            reads_per_shot = [reads_per_shot] * len(ch_list)
        self._stream = (int(total_shots), ch_list, list(reads_per_shot))
        self.start_tproc()
        if self._round is not None:
            self._round.stream = self._stream

    def poll_data(self, totaltime=0.1, timeout=None):
        rnd, stream = self._round, self._stream
        if rnd is None or stream is None:
            return []
        total, ch_list, reads = stream
        time_end = time.time() + totaltime
        new_data = []
        while totaltime < 0 or (rnd.streamed < total and time.time() < time_end):
            if rnd.error is not None:
                raise RuntimeError("exception in readout loop") from rnd.error
            if not rnd.wait(lambda: rnd.counter > rnd.streamed, timeout) or rnd.counter <= rnd.streamed:
                if rnd.error is not None:
                    raise RuntimeError("exception in readout loop") from rnd.error
                break                                  # timed out, or the program ended with nothing new
            shots = min(rnd.counter, total)
            newshots = shots - rnd.streamed
            if newshots <= 0:
                break
            bufs = [rnd.history(ch, rnd.streamed * n, newshots * n) for ch, n in zip(ch_list, reads, strict=True)]
            addr = rnd.streamed * reads[-1] % self.state.readouts[ch_list[-1]].cfg["avg_maxlen"]
            rnd.streamed = shots
            new_data.append((newshots, (bufs, (time.time() - rnd.t_start, shots, addr, newshots))))
        return new_data

    def prepare_round(self):
        pass

    def cleanup_round(self):
        pass
