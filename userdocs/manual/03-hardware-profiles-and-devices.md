# QCSS User Manual

## Chapter 3: Hardware profiles and devices

QCSS separates **the instrument** from **the chip**.

- A **profile** describes one instrument: its clock, ports, generators, memory sizes, acquisition limits and feedback latencies. Files: `src/qcss/config/profiles/*.yaml`.
- A **device** describes the chip: qubit frequencies, T1/T2, couplings, resonators, optional drift settings and hidden faults. Files: `src/qcss/config/devices/*.yaml`.
- A **platform** is a Qibolab folder (chapter 2) that maps qubits to channels.

You choose them at start-up: `qcss serve --profile NAME --device NAME`. A name or a path is accepted.

## 3.1 Inspecting them

```
uv run qcss profile list
uv run qcss profile show <name>
uv run qcss device show <name>
```
(`qcss device` has only `show`; verified with `--help`.)

Real output of `qcss profile list` (verified):

```
  * qblox_cluster_5q       [vendor: qblox      clock: 1e9 Hz, generators: 15, ports: 11]
  * qick_zcu216_4q         [vendor: qick       clock: 34406.4e6 Hz, generators: 2, ports: 2]
  * qick_zcu216_5q         [vendor: qick       clock: 34406.4e6 Hz, generators: 15, ports: 11]
  * test_ideal_1q          [vendor: test_ideal clock: 1e9 Hz, generators: 2, ports: 2]
  * zi_shfqc_5q            [vendor: zurich_instruments clock: 2e9 Hz, generators: 2, ports: 2]
```

## 3.2 Shipped profiles

| Profile | Models | Verified from `qcss profile show` |
|---|---|---|
| `qblox_cluster_5q` | A Qblox Cluster: one drive sequencer and one flux sequencer per qubit, five readout sequencers sharing one feedline. 1 GS/s. | 11 ports, 15 generators, 16384-sample waveform memory each; feedback latency 390 ticks (intra), 388 (inter), 160 (self), 270 (a further intra entry) |
| `qick_zcu216_5q` | A QICK ZCU216 board: a drive DAC and flux DAC per qubit, muxed readout on one DAC. DACs 6881.28 Msps. | 11 ports (`rf_direct` and `baseband`), 15 generators, 65536-sample waveform memory, 4096 instruction memory; feedback latency 6400 ticks |
| `qick_zcu216_4q` | A minimal QICK ZCU216: one drive generator and one readout generator. | 2 ports, 2 generators |
| `zi_shfqc_5q` | A Zurich Instruments SHFQC+: a signal generator and a quantum analyzer (readout) output. 2 GS/s. | 2 ports, 2 generators; latency 700 (self, intra) and 1100 (inter) ticks; reports "All profile fields verified" |
| `test_ideal_1q` | An idealized single-qubit instrument for tests. 1 GS/s. | 2 ports; latency 100 ticks; all verified |

A **tick** is the profile's integer time unit. For the QICK profile the tick is `34406.4e6` Hz, a common multiple of the tProc cycle, DAC sample and decimated ADC sample clocks (80 ticks per tProc cycle, 5 per DAC sample, 112 per decimated ADC sample, from the YAML comment). QICK timing is described at https://docs.qick.dev/latest/topics/timing.html.

## 3.3 What `verified: false` means

Every profile value carries a `provenance` block: a source URL, a firmware version where relevant, and `verified`. `verified: true` means the value was checked against the vendor documentation or specification. `verified: false` means **it is a calibration parameter, not a fact**: it follows one example build or an estimate, and you must check it against your own bitstream or instrument. The `qcss profile show` output lists them under "Unverified Provenance Fields".

Counts of `verified:` entries in the YAML files (verified by `grep`): `qblox_cluster_5q` 11 true / 1 false (the five RF ports, per `profile show`); `qick_zcu216_5q` and `qick_zcu216_4q` 0 true / 8 false per file by line count, and `profile show` lists 30 and 8 unverified fields for them; `zi_shfqc_5q` and `test_ideal_1q` all verified. The QICK YAML says its numbers come from "the notes' example build" and "every rate below must be checked against the bitstream in use". The README adds that the QICK profiles "follow one example firmware build".

Consequence: a simulation using `qick_zcu216_*` tells you how a QICK-like board of that build behaves, not how yours does. If your firmware differs, copy and edit a profile (you can pass a path to `--profile`) or serve your own board's `soccfg.dump_cfg()` (the QICK firmware module notes a lab can do that; Unverified in practice).

## 3.4 Shipped devices

| Device | Description |
|---|---|
| `transmon_5q` | A 5-qubit transmon chip, 2.25 cm^2, effective temperature 60 mK, drift enabled |
| `test_ideal_1q` | One qubit with T1 = T2* = 1000 us, 20 mK, no couplers, no drift |

`qcss device show transmon_5q` (verified):

```
Qubits (5):
  - Q0: f_max=5.050 GHz, Ec=0.280 GHz, T1=65.0 us, T2*=45.0 us, P_exc=0.017
  - Q1: f_max=5.200 GHz, Ec=0.290 GHz, T1=58.0 us, T2*=40.0 us, P_exc=0.017
  - Q2: f_max=4.950 GHz, Ec=0.280 GHz, T1=70.0 us, T2*=50.0 us, P_exc=0.017
  - Q3: f_max=5.300 GHz, Ec=0.300 GHz, T1=52.0 us, T2*=35.0 us, P_exc=0.017
  - Q4: f_max=5.120 GHz, Ec=0.280 GHz, T1=60.0 us, T2*=42.0 us, P_exc=0.017
Couplers (6): Q0-Q1 3.5 MHz, Q0-Q2 3.8, Q1-Q2 4.0, Q1-Q3 3.6, Q2-Q4 3.9, Q3-Q4 3.7
Resonators (5): f_r 7.02 to 7.40 GHz, kappa about 1.1 to 1.3 MHz, chi about -0.75 to -0.85 MHz
```

### Device fields (`src/qcss/config/device.py`)

| Field | Meaning |
|---|---|
| `f_max_ghz` | Qubit frequency at its flux sweet spot (maximum) |
| `ec_ghz` | Charging energy E_C; the transmon anharmonicity is about -E_C |
| `d_asym` | SQUID junction asymmetry in [0, 1] |
| `phi_offset` | Flux offset in flux quanta |
| `t1_us`, `t2_star_us` | Energy relaxation time and Ramsey dephasing time |
| `t_eff_mk`, `p_excited` | Effective temperature and thermal excited population |
| `rabi_max_ghz` | Rabi frequency at full-scale drive amplitude |
| `xy_mm` | Position on chip (used by the cosmic-ray burst model) |
| couplers: `j_mhz` | Exchange coupling; tunable-coupler fields optional |
| resonators: `f_r_ghz`, `kappa_mhz`, `pulls_mhz`, `cable_delay_ns`, `eta`, `readout_photons` | Readout resonator frequency, linewidth, frequency shift per qubit level, cable delay, measurement efficiency, probe photon number |
| `dynamics` | Optional slow drift: `t1_sigma_ln`, `t1_tau_s`, `flux_noise_ghz`, `tls_per_qubit`, `bursts` |
| `faults` | Optional hidden impairments: `drive_mixers` (gain, phase, DC offsets per qubit) and `flux_lines` (exponential-tail terms, bias-tee time constant) |

Files are validated by frozen Pydantic models with extra fields forbidden. Note (read from the YAML): the shipped `transmon_5q.yaml` has a `dynamics:` block but **no `faults:` block**, so it carries no hidden mixer or flux impairments unless you add one. `test_ideal_1q` has neither, so it is static.

Observed (verified): a fresh chassis does not start at exactly the YAML T1. `qcss admin truth` on a new `transmon_5q` chassis showed T1 59.12, 38.08, 37.84, 12.54, 29.49 us for qubits 0 to 4 against 65, 58, 70, 52, 60 in the file. The drift model draws a log-normal T1 wander and TLS defects at start (chapter 4).

## 3.5 Platforms

`platforms/qcss_qblox_5q` and `platforms/qcss_rfsoc_5q` hold `platform.py` and `parameters.json` (initial "last cooldown" values from `scripts/make_platform_parameters.py`: frequencies off the truth, an imperfect pi amplitude); the technician later adds `calibration.json` (chapter 5).

## 3.6 Making your own

Copy a YAML, edit, and run `qcss validate job.json -p <profile-or-path> -d <device-or-path>`. The Explorer's Config Studio (chapter 7) edits and validates the same schemas with per-field explanations and saves copies into its workspace without overwriting shipped files.

---
Sources: `src/qcss/config/profiles/*.yaml`, `src/qcss/config/devices/*.yaml`, `src/qcss/config/device.py`, `README.md` (Hardware profiles), `src/qcss/boards/qick/firmware.py`, `platforms/*`. Run: `qcss profile list`, `qcss profile show` (all five), `qcss device show transmon_5q`, `qcss admin truth`.
