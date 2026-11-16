"""Firmware descriptions of the virtual QICK board: what ``soc.get_cfg()`` returns.

A QICK client builds its ``QickConfig`` from this dict and compiles every program against it, so it must
be what the pinned qick software (``QICK_SW_VERSION``) would report for a real ZCU216 bitstream. The
layout is the chip every other QCSS face sees (profile ``qick_zcu216_5q``, device ``transmon_5q``):

- gens 0-4: ``axis_signal_gen_v6`` drive lines, DACs 20-23 and 30;
- gens 5-9: ``axis_signal_gen_v6`` flux lines, DACs 10-13 and 31;
- gen 10: ``axis_sg_mux8_v1`` multiplexed readout tones on DAC 32 (one feedline);
- readouts 0-4: outputs of one ``axis_pfb_readout_v4`` (64-channel PFB) on ADC 20, one per qubit.

Every DAC runs at 6881.28 Msps (fabric 430.08 MHz, the tProc timing clock); the ADC at 2457.6 Msps,
decimated by the PFB to 76.8 MHz (13.02 ns, 448 QCSS ticks: a multiple of the profile's 112-tick grid). Field names, types and derived values follow the qick 0.2.370 drivers
(``drivers/generator.py``, ``drivers/readout.py``) and two published dumps: the QICK testbench
``soccfg.json`` (MIT) and qibosoq's ``tests/qick_config_*.json`` (Apache-2.0). Like the profile's
numbers, they describe one plausible build, not a verified bitstream; a lab can serve its own board's
``soccfg.dump_cfg()`` instead.

The ``zcu111_*`` descriptions are the same layout on a ZCU111's fewer converters (2 flux DACs shared by the
qubits, DACs at 6144 Msps, the ADC at 3072 Msps, a PFB output of 96 MHz: 320 ticks of the profile's 80-tick
grid). They are experimental: nothing about them has been checked against a ZCU111 bitstream.

This module never imports qick: the face is a board, not a client.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

QICK_SW_VERSION = "0.2.370"      # the qick client this description is written for (qibosoq 0.1.5 pins it)
FW_TIMESTAMP = "Tue Mar 10 14:22:05 2026"

F_REF = 245.76                   # RF reference clock, MHz
PFB_NCH = 64                     # PFB channels, adc_fs / 64 apart (ZCU216 38.4 MHz, ZCU111 48 MHz): one per
                                 # resonator of transmon_5q; output adc_fs / (PFB_NCH / 2)
PFB_NOUT = 8                     # axis_pfb_readout_v4 outputs
N_QUBITS = 5


@dataclass(frozen=True)
class BoardParams:
    board: str
    dac_fs: float
    dac_fs_mult: int
    dac_fs_div: int
    dac_fabric: float
    adc_fs: float
    adc_fs_mult: int
    adc_fs_div: int
    adc_fabric: float
    drive_dacs: list[str]
    flux_dacs: list[str]
    mux_dac: str
    ro_adc: str


ZCU216_PARAMS = BoardParams(
    board="ZCU216",
    dac_fs=6881.28, dac_fs_mult=56, dac_fs_div=2, dac_fabric=430.08,
    adc_fs=2457.6, adc_fs_mult=40, adc_fs_div=4, adc_fabric=307.2,
    drive_dacs=["20", "21", "22", "23", "30"],
    flux_dacs=["10", "11", "12", "13", "31"],
    mux_dac="32",
    ro_adc="20",
)

ZCU111_PARAMS = BoardParams(
    board="ZCU111",
    dac_fs=6144.0, dac_fs_mult=50, dac_fs_div=2, dac_fabric=384.0,
    adc_fs=3072.0, adc_fs_mult=25, adc_fs_div=2, adc_fabric=384.0,
    drive_dacs=["00", "01", "02", "03", "10"],
    flux_dacs=["11", "12"],
    mux_dac="13",
    ro_adc="00",
)


def _dac_tiles(p: BoardParams) -> dict[str, Any]:
    blocks: dict[str, list[str]] = {}
    for dac in sorted(p.drive_dacs + p.flux_dacs + [p.mux_dac]):
        blocks.setdefault(dac[0], []).append(dac)
    return {tile: {"coupling": "AC", "fabric_div": 16, "out_div": 1, "blocks": bl, "f_ref": F_REF, "ref_div": 1,
                   "fs_mult": p.dac_fs_mult, "fs_div": p.dac_fs_div, "fs": p.dac_fs, "f_fabric": p.dac_fabric,
                   "f_out": p.dac_fabric} for tile, bl in blocks.items()}


def _rf(p: BoardParams, tproc_path: str, clock: str) -> dict[str, Any]:
    dacs = sorted(p.drive_dacs + p.flux_dacs + [p.mux_dac])
    tiles = _dac_tiles(p)
    return {
        "type": "usp_rf_data_converter", "fullpath": "usp_rf_data_converter_0", "ip_type": 2, "hs_adc": False,
        "tiles": {"dac": tiles,
                  "adc": {p.ro_adc[0]: {"coupling": "AC", "fabric_div": 8, "out_div": 1, "blocks": [p.ro_adc],
                                        "f_ref": F_REF, "ref_div": 1, "fs_mult": p.adc_fs_mult, "fs_div": p.adc_fs_div,
                                        "fs": p.adc_fs, "f_fabric": p.adc_fabric, "f_out": p.adc_fabric}}},
        "dacs": {d: {"index": [int(d[0]), int(d[1])], "coupling": "AC", "f_ref": F_REF, "fs_mult": p.dac_fs_mult,
                     "fs_div": p.dac_fs_div, "fs": p.dac_fs, "f_fabric": p.dac_fabric, "interpolation": 1, "datapath": 4}
                 for d in dacs},
        "adcs": {p.ro_adc: {"index": [int(p.ro_adc[0]), int(p.ro_adc[1])], "coupling": "AC", "f_ref": F_REF,
                            "fs_mult": p.adc_fs_mult, "fs_div": p.adc_fs_div, "fs": p.adc_fs, "f_fabric": p.adc_fabric,
                            "decimation": 1}},
        # every DAC tile shares the tProc timing clock, as the timing-clock source must
        "clk_groups": [[[tproc_path, clock], *[["dac", int(t)] for t in sorted(tiles)]], [["adc", int(p.ro_adc[0])]]],
        "revision": 2, "version": "2.6",
    }


def _full_speed_gen(p: BoardParams, index: int, dac: str, wrapper: str) -> dict[str, Any]:
    return {"type": "axis_signal_gen_v6", "fullpath": f"{wrapper}axis_signal_gen_v6_{index}", "maxlen": 65536,
            "complex_env": True, "samps_per_clk": 16, "maxv_scale": 1.0, "has_dds": True, "b_dds": 32,
            "b_phase": 32, "maxv": 32766, "has_mixer": False, "revision": 6, "version": "1.0", "dac": dac,
            "fs": p.dac_fs, "fs_mult": p.dac_fs_mult, "fs_div": p.dac_fs_div, "interpolation": 1, "f_fabric": p.dac_fabric,
            "f_dds": p.dac_fs, "fdds_div": p.dac_fs_div, "tproc_ch": index}


def _mux_gen(p: BoardParams, index: int, wrapper: str) -> dict[str, Any]:
    # AbsMuxSignalGen + AbsPulsedSignalGen: tones, no envelope memory (so no maxlen or complex_env)
    return {"type": "axis_sg_mux8_v1", "fullpath": f"{wrapper}axis_sg_mux8_v1_0", "revision": 1, "version": "1.0",
            "n_tones": 8, "has_gain": True, "has_phase": True, "has_dds": True, "b_dds": 32, "b_phase": 32,
            "maxv": 32766, "has_mixer": False, "dac": p.mux_dac, "fs": p.dac_fs, "fs_mult": p.dac_fs_mult,
            "fs_div": p.dac_fs_div, "interpolation": 1, "f_fabric": p.dac_fabric, "f_dds": p.dac_fs,
            "fdds_div": p.dac_fs_div, "tproc_ch": index}


def _gens(p: BoardParams, wrapper: str) -> list[dict[str, Any]]:
    gens = [_full_speed_gen(p, i, dac, wrapper) for i, dac in enumerate(p.drive_dacs + p.flux_dacs)]
    return [*gens, _mux_gen(p, len(gens), wrapper)]


def _pfb_readout(p: BoardParams, q: int, trigger: dict[str, Any], buffers: dict[str, Any], wrapper: str) -> dict[str, Any]:
    down = PFB_NCH // 2                  # the PFB is a 50 %-overlap filter bank
    return {"pfb_nch": PFB_NCH, "pfb_nout": PFB_NOUT, "pfb_ch_offset": PFB_NCH // 2, "pfb_dds_on_output": True,
            "pfb_port": q, "tproc_ch": q, **trigger, "adc": p.ro_adc, "b_phase": 32,
            "fs": p.adc_fs, "fs_mult": p.adc_fs_mult, "fs_div": p.adc_fs_div, "decimation": 1, "f_fabric": p.adc_fabric,
            "f_dds": p.adc_fs / down, "fdds_div": p.adc_fs_div * down, "f_output": p.adc_fs / down, "b_dds": 32,
            "iq_offset": -0.5, "has_outsel": False, **buffers,
            # QickSoc.config_mux_readout looks the PFB up with getattr(soc, ro_fullpath): a top-level name
            "avgbuf_fullpath": f"{wrapper}axis_avg_buffer_{q}", "ro_fullpath": "axis_pfb_readout_v4_0",
            "avgbuf_type": "axis_avg_buffer", "ro_type": "axis_pfb_readout_v4", "ro_revision": 1}


def _v2(p: BoardParams) -> dict[str, Any]:
    tproc = {"type": "qick_processor", "fullpath": "qick_processor_0", "pmem_size": 4096, "dmem_size": 16384,
             "wmem_size": 1024, "dreg_qty": 16, "in_port_qty": N_QUBITS, "out_trig_qty": 20, "out_dport_qty": 1,
             "out_dport_dw": 8, "out_wport_qty": 16, "has_lfsr": 1, "has_divider": 1, "has_arith": 1,
             "has_time_read": 1, "has_qcom": 0, "has_custom_periph": 1, "has_io_ctrl": 1, "has_ext_flag": 0,
             "has_qnet": 0, "fifo_depth": 512, "call_depth": 255, "debug": 3,
             "clk_srcs": {"core clock": {"source": ["PS", 0], "f_clk": 200.0, "src_range": [66.66666666666667,
                                                                                            133.33333333333334]},
                          "timing clock": {"source": ["dac", int(p.drive_dacs[0][0])], "f_clk": p.dac_fabric,
                                           "src_range": None}},
             "revision": 27, "version": "2.0", "f_core": 200.0, "f_time": p.dac_fabric,
             "output_pins": [["trig", i, 0, f"PMOD0_{i}_LS"] for i in range(8)], "start_pin": None, "stop_pin": None}
    buffers = {"avg_maxlen": 8192, "buf_maxlen": 4096, "has_edge_counter": True, "has_weights": False,
               "avgbuf_revision": 4, "avgbuf_version": "1.2"}
    ros = [_pfb_readout(p, q, {"trigger_type": "tport", "trigger_port": 10 + q, "trigger_bit": 0}, buffers,
                        "readout_wrapper/") for q in range(N_QUBITS)]
    return {"board": p.board, "sw_version": QICK_SW_VERSION, "extra_description": [], "fw_timestamp": FW_TIMESTAMP,
            "rf": _rf(p, "qick_processor_0", "timing clock"), "refclk_freq": F_REF, "gens": _gens(p, "signal_gen_wrapper/"),
            "iqs": [], "time_taggers": [], "readouts": ros, "tprocs": [tproc]}


def _v1(p: BoardParams) -> dict[str, Any]:
    tproc = {"type": "axis_tproc64x32_x8", "fullpath": "axis_tproc64x32_x8_0", "dmem_size": 4096,
             "clk_srcs": {"clock": {"source": ["dac", int(p.drive_dacs[0][0])], "f_clk": p.dac_fabric, "src_range": None}},
             "revision": 4, "version": "1.0", "f_time": p.dac_fabric,
             "output_pins": [["output", 0, i, f"PMOD0_{i}_LS"] for i in range(8)], "start_pin": "PMOD1_0_LS",
             "pmem_size": 8192}
    buffers = {"avg_maxlen": 16384, "buf_maxlen": 1024, "has_edge_counter": False, "has_weights": False,
               "avgbuf_revision": 6, "avgbuf_version": "1.0"}
    ros = [_pfb_readout(p, q, {"trigger_type": "output", "trigger_port": 0, "trigger_bit": 8 + q}, buffers, "")
           for q in range(N_QUBITS)]
    # The x8 tProc's channel 0 is the trigger register (m1_axis -> axis_set_reg in qick_216.hwh); channels 1-7
    # (m2..m8) drive generators. Drive lines take 1-5, the flux lines share channel 6 through an axis_tmux_v1
    # (the mux address rides in the mode register), and the mux readout generator, which qick cannot address
    # through a tProc mux, has channel 7.
    gens = _gens(p, "")
    n_drive_flux = len(p.drive_dacs) + len(p.flux_dacs)
    for i, g in enumerate(gens):
        if i < N_QUBITS:
            g["tproc_ch"] = 1 + i
        elif i < n_drive_flux:
            g["tproc_ch"], g["tmux_ch"] = 6, i - N_QUBITS
        else:
            g["tproc_ch"] = 7
    return {"board": p.board, "sw_version": QICK_SW_VERSION, "extra_description": [], "fw_timestamp": FW_TIMESTAMP,
            "rf": _rf(p, "axis_tproc64x32_x8_0", "clock"), "refclk_freq": F_REF, "tprocs": [tproc], "gens": gens,
            "iqs": [], "time_taggers": [], "readouts": ros}


FIRMWARES = {
    "zcu216_v2_5q": _v2(ZCU216_PARAMS),
    "zcu216_v1_5q": _v1(ZCU216_PARAMS),
    "zcu111_v2_5q": _v2(ZCU111_PARAMS),
    "zcu111_v1_5q": _v1(ZCU111_PARAMS),
}


def description(name: str = "zcu216_v2_5q") -> dict[str, Any]:
    """The ``get_cfg()`` dict of firmware ``name``, a fresh copy the caller may change."""
    if name not in FIRMWARES:
        raise KeyError(f"unknown QICK firmware {name!r}; known: {', '.join(sorted(FIRMWARES))}")
    return copy.deepcopy(FIRMWARES[name])
