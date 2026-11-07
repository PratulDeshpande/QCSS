# Native QICK face: what it supports and refuses

Reference for `qcss serve --qick-ns ...` (`src/qcss/boards/qick/`). The face is a `QickSoc` stand-in (`QcssQickSoc`) served over Pyro4 the way `qick.pyro.start_server` serves a real ZCU216, so unmodified `qick` programs run against the simulated chip. Facts below come from the code and `surface.json`; none were exercised on real hardware. For a walk-through see `../quickstart/qick-from-a-host.md`.

## Versions
- Client the face is written for and its surface frozen against: `qick==0.2.370` (`QICK_SW_VERSION`, `surface.json: qick_version`). A manual install: its `pynq` dependency cannot be resolved by uv's universal lock.
- Server needs the `qick` extra: `Pyro4>=4.82,<5`, `psutil>=5.9`. The face never imports `qick`.
- Pyro4 settings as `qick.pyro` sets them: serializer `pickle` only, protocol 4, `REQUIRE_EXPOSE=False`. The serializer is an allowlist decoder (`serializer.py`): only plain data, numpy arrays/dtypes/scalars, `OrderedDict`, Pyro URIs and exception classes unpickle; any other global (for example `os.system`) is refused.
- No TLS, no token (QICK's own server has neither). Non-loopback `--qick-listen`, or `--qick-ns` with `--qick-start-ns`, needs `--insecure`.

## Serve flags
`--qick-ns host:port` (turns the face on), `--qick-name` (default `myqick`, the `make_proxy` proxy name), `--qick-listen host[:port]` (default `127.0.0.1`, free port), `--qick-firmware zcu216_v2_5q|zcu216_v1_5q` (default `zcu216_v2_5q`), `--qick-start-ns` (run the nameserver in-process), `--qick-loopback GEN:RO` (repeatable; needs `--qick-ns`). Full text in `cli.md`.

## Firmware descriptions (`firmware.py`)
Two builds, same chip as profile `qick_zcu216_5q` + device `transmon_5q`. They describe one plausible build, not a verified bitstream.

| Item | `zcu216_v2_5q` (tProc v2) | `zcu216_v1_5q` (tProc v1) |
|---|---|---|
| Board | ZCU216 | ZCU216 |
| Processor | `qick_processor` (pmem 4096, dmem 16384, wmem 1024, 16 dregs, core 200 MHz) | `axis_tproc64x32_x8` (pmem 8192, dmem 4096) |
| Generators 0-4 | `axis_signal_gen_v6` drive lines, DACs 20-23 and 30 | same; tProc channels 1-5 |
| Generators 5-9 | `axis_signal_gen_v6` flux lines, DACs 10-13 and 31 | same; share tProc channel 6 through a tmux |
| Generator 10 | `axis_sg_mux8_v1`, 8 multiplexed readout tones, DAC 32 (one feedline) | same; tProc channel 7 |
| Readouts 0-4 | five outputs of one `axis_pfb_readout_v4` (64-channel PFB) on ADC 20 | same |
| Readout trigger | tport (`trigger_port` 10+q) | output register bit 8+q |
| Avg buffer | `avg_maxlen` 8192, `buf_maxlen` 4096, edge counter | `avg_maxlen` 16384, `buf_maxlen` 1024 |
| Rates | DAC 6881.28 Msps (fabric 430.08 MHz); ADC 2457.6 Msps decimated by the PFB to 76.8 MHz (448 ticks) | same |
| Firmware timestamp | `Tue Mar 10 14:22:05 2026` (fixed string) | same |

Both can be replaced by a lab serving its own `soccfg.dump_cfg()` (docstring claim; no CLI flag for it: Unverified).

## Supported
Remote methods the face implements (`QcssQickSoc`; names and signatures follow `surface.json`):
- config: `get_cfg`, `start_src`, `set_nyquist`, `set_mixer_freq` (refuses, see below), `config_mux_gen`, `config_mux_readout`, `configure_readout`, `config_avg`, `config_buf`, `enable_buf`, `load_weights`.
- program: `load_bin_program`, `reload_mem`, `load_envelope`, `reset_gens`, `start_tproc`, `stop_tproc`, `clear_tproc_counter`, `get_tproc_counter`.
- readout: `start_readout`, `poll_data`, `get_accumulated`, `get_decimated`, `prepare_round`, `cleanup_round`.
- the 23 calls an unmodified QICK program's client code sends (`surface.json: client_calls`): `cleanup_round, clear_tproc_counter, config_avg, config_buf, config_mux_gen, config_mux_readout, configure_readout, enable_buf, get_accumulated, get_decimated, get_tproc_counter, load_bin_program, load_envelope, load_weights, poll_data, prepare_round, reload_mem, set_mixer_freq, set_nyquist, start_readout, start_src, start_tproc, stop_tproc`.
- tProc v1: 64-bit word decode and execution (`seti`/`set`/`waiti`/`synci`/`pushi`/`popi` etc.; counter word 1 marks shot end). tProc v2: 72-bit instruction decode, ALU, branches, timed port writes, `TIME inc_ref/set_ref/updt`, TRIG, DPORT; the WAIT-time busy loop is skipped, not spun. A late output is queued, not dropped.
- Generators: full-speed DDS x envelope (outsel product/dds/input/zero); mux tones masked by `conf`. Readout: PFB output, decimated and accumulated acquisition, feedback.
- Programs become chassis jobs: identical shots fold into one program point; the gap between shots becomes the repetition delay; pulses on a busy generator are queued as hardware does.
- Bench loopback: `--qick-loopback GEN:RO` takes both ends off the chip: that generator reaches no qubit line and the readout captures the cable (delay `CABLE_DELAY_S = 331 ns`, ADC noise added). The cable parameters are from QICK demo 00 recorded on a ZCU111; ZCU216 PFB may differ (`verified: false`).
- ADC counts: `ADC_COUNTS_PER_UNIT = 100.0` model units to counts (`verified: false`).
- Board reboot (admin fault) loses all board state (`_reboot`).

## Refused or not served
- Not served yet (`NOT_YET_SERVED`, 51 names), including: `tproc`, `streamer` attributes, `load_mem`, `read_mem`, `adcfreq`, `calc_*`, `ch_fstep`, `check_pfb_collisions`, `cycles2us`/`us2cycles`, `freq2reg`/`reg2freq` families, `deg2reg` family, `get_maxv`, `description`, `dump_cfg`, `roundfreq`, DDR4 (`arm_ddr4`, `clear_ddr4`, `get_ddr4`), MR (`arm_mr`, `get_mr`), clocks (`clocks_locked`, `config_clocks`, `set_all_clks`), ADC calibration/attenuator (`freeze_adc_cals`, `unfreeze_adc_cals`, `get/set_adc_attenuator`), `get_sample_rates`, `map_signal_paths`, `round_sample_rate`, `set_iq`, time tagger (`tt_*`), `valid_sample_rates`. Many are client-side helpers a program normally computes locally from `get_cfg()`.
- Errors the face raises, worded as the real board's: `start_src` not internal/external; `start_tproc` with no program ("no program loaded"); envelope longer than `maxlen` ("buffer length must be ... samples or less") or on a channel without complex envelopes (`NotImplementedError`); Nyquist zone other than 1 or 2; `set_mixer_freq` ("This channel does not have a mixer": no generator has one); too many tones for the mux generator; `config_mux_readout` with an unknown PFB path (AttributeError) or an unsupported `sel`; `load_weights` (`KeyError wgt_maxlen`: no avg buffer has a weights memory); averaging length above `avg_maxlen`; decimated length not below `buf_maxlen`; "exception in readout loop" when the chassis job fails.
- Instructions the interpreters do not emulate raise `NotImplementedError`: unknown tProc v1 instructions ("is not emulated yet"), tProc v2 instructions outside the implemented set, and ALU operations beyond `+ - AND OR XOR NOT ASR SL SR ABS`. The v2 external flag is never raised (conditions `F` false, `NF` true). A tProc v1 data write to a non-trigger channel without a pulse produces no output.
- Hardware rules still apply: a program that violates the profile (`qick_zcu216_5q`: 80-tick grid, memory) is refused as the chassis refuses any job.
- Qibosoq board face (`--board-listen`) is a different face: it refuses RAW (decimated) acquisition and nonzero DC bias.
- tProc v2 `qick` programs on `zcu216_v1_5q` and v1 averager programs on `zcu216_v2_5q` are not meant to match (firmware picks the processor). Mixed use: Unverified.

## Keeping the surface in sync
`python scripts/qick_surface.py` rewrites `surface.json` for the installed qick; `--check` exits 1 if out of date. Tests in `tests/integration/test_qick_*.py` compare the face to it, so a qick upgrade that adds a remote call fails a test.

Sources: src/qcss/boards/qick/{firmware,soc,gens,readouts,results,serializer,pyro_host,tproc_v1,tproc_v2,tproc_v2_run,translate}.py, src/qcss/boards/qick/surface.json, scripts/qick_surface.py, src/qcss/cli.py (serve options), SECURITY.md, CHANGELOG.md, pyproject.toml.
