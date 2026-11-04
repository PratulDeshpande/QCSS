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

This module never imports qick: the face is a board, not a client.
"""
from __future__ import annotations

import copy
from typing import Any

QICK_SW_VERSION = "0.2.370"      # the qick client this description is written for (qibosoq 0.1.5 pins it)
FW_TIMESTAMP = "Tue Mar 10 14:22:05 2026"

F_REF = 245.76                   # RF reference clock, MHz
DAC_FS, DAC_FS_MULT, DAC_FS_DIV, DAC_FABRIC = 6881.28, 56, 2, 430.08
ADC_FS, ADC_FS_MULT, ADC_FS_DIV, ADC_FABRIC = 2457.6, 40, 4, 307.2
PFB_NCH = 64                     # PFB channels, 38.4 MHz apart: one per resonator of transmon_5q (their
                                 # folded tones are 60-130 MHz apart); output ADC_FS / (PFB_NCH / 2) = 76.8 MHz
PFB_NOUT = 8                     # axis_pfb_readout_v4 outputs
DRIVE_DACS = ["20", "21", "22", "23", "30"]
FLUX_DACS = ["10", "11", "12", "13", "31"]
MUX_DAC = "32"
RO_ADC = "20"
N_QUBITS = 5


def _dac_tiles() -> dict[str, Any]:
    blocks: dict[str, list[str]] = {}
    for dac in sorted(DRIVE_DACS + FLUX_DACS + [MUX_DAC]):
        blocks.setdefault(dac[0], []).append(dac)
    return {tile: {"coupling": "AC", "fabric_div": 16, "out_div": 1, "blocks": bl, "f_ref": F_REF, "ref_div": 1,
                   "fs_mult": DAC_FS_MULT, "fs_div": DAC_FS_DIV, "fs": DAC_FS, "f_fabric": DAC_FABRIC,
                   "f_out": DAC_FABRIC} for tile, bl in blocks.items()}


def _rf(tproc_path: str, clock: str) -> dict[str, Any]:
    dacs = sorted(DRIVE_DACS + FLUX_DACS + [MUX_DAC])
    tiles = _dac_tiles()
    return {
        "type": "usp_rf_data_converter", "fullpath": "usp_rf_data_converter_0", "ip_type": 2, "hs_adc": False,
        "tiles": {"dac": tiles,
                  "adc": {RO_ADC[0]: {"coupling": "AC", "fabric_div": 8, "out_div": 1, "blocks": [RO_ADC],
                                      "f_ref": F_REF, "ref_div": 1, "fs_mult": ADC_FS_MULT, "fs_div": ADC_FS_DIV,
                                      "fs": ADC_FS, "f_fabric": ADC_FABRIC, "f_out": ADC_FABRIC}}},
        "dacs": {d: {"index": [int(d[0]), int(d[1])], "coupling": "AC", "f_ref": F_REF, "fs_mult": DAC_FS_MULT,
                     "fs_div": DAC_FS_DIV, "fs": DAC_FS, "f_fabric": DAC_FABRIC, "interpolation": 1, "datapath": 4}
                 for d in dacs},
        "adcs": {RO_ADC: {"index": [int(RO_ADC[0]), int(RO_ADC[1])], "coupling": "AC", "f_ref": F_REF,
                          "fs_mult": ADC_FS_MULT, "fs_div": ADC_FS_DIV, "fs": ADC_FS, "f_fabric": ADC_FABRIC,
                          "decimation": 1}},
        # every DAC tile shares the tProc timing clock, as the timing-clock source must
        "clk_groups": [[[tproc_path, clock], *[["dac", int(t)] for t in sorted(tiles)]], [["adc", int(RO_ADC[0])]]],
        "revision": 2, "version": "2.6",
    }


def _full_speed_gen(index: int, dac: str, wrapper: str) -> dict[str, Any]:
    return {"type": "axis_signal_gen_v6", "fullpath": f"{wrapper}axis_signal_gen_v6_{index}", "maxlen": 65536,
            "complex_env": True, "samps_per_clk": 16, "maxv_scale": 1.0, "has_dds": True, "b_dds": 32,
            "b_phase": 32, "maxv": 32766, "has_mixer": False, "revision": 6, "version": "1.0", "dac": dac,
            "fs": DAC_FS, "fs_mult": DAC_FS_MULT, "fs_div": DAC_FS_DIV, "interpolation": 1, "f_fabric": DAC_FABRIC,
            "f_dds": DAC_FS, "fdds_div": DAC_FS_DIV, "tproc_ch": index}


def _mux_gen(index: int, wrapper: str) -> dict[str, Any]:
    # AbsMuxSignalGen + AbsPulsedSignalGen: tones, no envelope memory (so no maxlen or complex_env)
    return {"type": "axis_sg_mux8_v1", "fullpath": f"{wrapper}axis_sg_mux8_v1_0", "revision": 1, "version": "1.0",
            "n_tones": 8, "has_gain": True, "has_phase": True, "has_dds": True, "b_dds": 32, "b_phase": 32,
            "maxv": 32766, "has_mixer": False, "dac": MUX_DAC, "fs": DAC_FS, "fs_mult": DAC_FS_MULT,
            "fs_div": DAC_FS_DIV, "interpolation": 1, "f_fabric": DAC_FABRIC, "f_dds": DAC_FS,
            "fdds_div": DAC_FS_DIV, "tproc_ch": index}


def _gens(wrapper: str) -> list[dict[str, Any]]:
    gens = [_full_speed_gen(i, dac, wrapper) for i, dac in enumerate(DRIVE_DACS + FLUX_DACS)]
    return [*gens, _mux_gen(len(gens), wrapper)]


def _pfb_readout(q: int, trigger: dict[str, Any], buffers: dict[str, Any], wrapper: str) -> dict[str, Any]:
    down = PFB_NCH // 2                  # the PFB is a 50 %-overlap filter bank
    return {"pfb_nch": PFB_NCH, "pfb_nout": PFB_NOUT, "pfb_ch_offset": PFB_NCH // 2, "pfb_dds_on_output": True,
            "pfb_port": q, "tproc_ch": q, **trigger, "adc": RO_ADC, "b_phase": 32,
            "fs": ADC_FS, "fs_mult": ADC_FS_MULT, "fs_div": ADC_FS_DIV, "decimation": 1, "f_fabric": ADC_FABRIC,
            "f_dds": ADC_FS / down, "fdds_div": ADC_FS_DIV * down, "f_output": ADC_FS / down, "b_dds": 32,
            "iq_offset": -0.5, "has_outsel": False, **buffers,
            # QickSoc.config_mux_readout looks the PFB up with getattr(soc, ro_fullpath): a top-level name
            "avgbuf_fullpath": f"{wrapper}axis_avg_buffer_{q}", "ro_fullpath": "axis_pfb_readout_v4_0",
            "avgbuf_type": "axis_avg_buffer", "ro_type": "axis_pfb_readout_v4", "ro_revision": 1}


def _v2() -> dict[str, Any]:
    tproc = {"type": "qick_processor", "fullpath": "qick_processor_0", "pmem_size": 4096, "dmem_size": 16384,
             "wmem_size": 1024, "dreg_qty": 16, "in_port_qty": N_QUBITS, "out_trig_qty": 20, "out_dport_qty": 1,
             "out_dport_dw": 8, "out_wport_qty": 16, "has_lfsr": 1, "has_divider": 1, "has_arith": 1,
             "has_time_read": 1, "has_qcom": 0, "has_custom_periph": 1, "has_io_ctrl": 1, "has_ext_flag": 0,
             "has_qnet": 0, "fifo_depth": 512, "call_depth": 255, "debug": 3,
             "clk_srcs": {"core clock": {"source": ["PS", 0], "f_clk": 200.0, "src_range": [66.66666666666667,
                                                                                            133.33333333333334]},
                          "timing clock": {"source": ["dac", int(DRIVE_DACS[0][0])], "f_clk": DAC_FABRIC,
                                           "src_range": None}},
             "revision": 27, "version": "2.0", "f_core": 200.0, "f_time": DAC_FABRIC,
             "output_pins": [["trig", i, 0, f"PMOD0_{i}_LS"] for i in range(8)], "start_pin": None, "stop_pin": None}
    buffers = {"avg_maxlen": 8192, "buf_maxlen": 4096, "has_edge_counter": True, "has_weights": False,
               "avgbuf_revision": 4, "avgbuf_version": "1.2"}
    ros = [_pfb_readout(q, {"trigger_type": "tport", "trigger_port": 10 + q, "trigger_bit": 0}, buffers,
                        "readout_wrapper/") for q in range(N_QUBITS)]
    return {"board": "ZCU216", "sw_version": QICK_SW_VERSION, "extra_description": [], "fw_timestamp": FW_TIMESTAMP,
            "rf": _rf("qick_processor_0", "timing clock"), "refclk_freq": F_REF, "gens": _gens("signal_gen_wrapper/"),
            "iqs": [], "time_taggers": [], "readouts": ros, "tprocs": [tproc]}


def _v1() -> dict[str, Any]:
    tproc = {"type": "axis_tproc64x32_x8", "fullpath": "axis_tproc64x32_x8_0", "dmem_size": 4096,
             "clk_srcs": {"clock": {"source": ["dac", int(DRIVE_DACS[0][0])], "f_clk": DAC_FABRIC, "src_range": None}},
             "revision": 4, "version": "1.0", "f_time": DAC_FABRIC,
             "output_pins": [["output", 0, i, f"PMOD0_{i}_LS"] for i in range(8)], "start_pin": "PMOD1_0_LS",
             "pmem_size": 8192}
    buffers = {"avg_maxlen": 16384, "buf_maxlen": 1024, "has_edge_counter": False, "has_weights": False,
               "avgbuf_revision": 6, "avgbuf_version": "1.0"}
    ros = [_pfb_readout(q, {"trigger_type": "output", "trigger_port": 0, "trigger_bit": 8 + q}, buffers, "")
           for q in range(N_QUBITS)]
    # The x8 tProc's channel 0 is the trigger register (m1_axis -> axis_set_reg in qick_216.hwh); channels 1-7
    # (m2..m8) drive generators. Drive lines take 1-5, the flux lines share channel 6 through an axis_tmux_v1
    # (the mux address rides in the mode register), and the mux readout generator, which qick cannot address
    # through a tProc mux, has channel 7.
    gens = _gens("")
    for i, g in enumerate(gens):
        if i < N_QUBITS:
            g["tproc_ch"] = 1 + i
        elif i < 2 * N_QUBITS:
            g["tproc_ch"], g["tmux_ch"] = 6, i - N_QUBITS
        else:
            g["tproc_ch"] = 7
    return {"board": "ZCU216", "sw_version": QICK_SW_VERSION, "extra_description": [], "fw_timestamp": FW_TIMESTAMP,
            "rf": _rf("axis_tproc64x32_x8_0", "clock"), "refclk_freq": F_REF, "tprocs": [tproc], "gens": gens,
            "iqs": [], "time_taggers": [], "readouts": ros}


FIRMWARES = {"zcu216_v2_5q": _v2(), "zcu216_v1_5q": _v1()}


def description(name: str = "zcu216_v2_5q") -> dict[str, Any]:
    """The ``get_cfg()`` dict of firmware ``name``, a fresh copy the caller may change."""
    if name not in FIRMWARES:
        raise KeyError(f"unknown QICK firmware {name!r}; known: {', '.join(sorted(FIRMWARES))}")
    return copy.deepcopy(FIRMWARES[name])
