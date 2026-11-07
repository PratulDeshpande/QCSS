# QCSS User Manual

## Chapter 4: The physics of the simulated QPU

This chapter is the physics behind the "PHYs" of the simulated **QPU** (quantum processing unit, the chip). It explains what is simulated, at what fidelity, and which imperfections the chip and the signal chain add. Equations are given only where they help; the source files hold the details and literature references.

## 4.1 The transmon in one paragraph

QCSS models superconducting **transmon** qubits (`src/qcss/physics/transmon.py`). A transmon is an anharmonic oscillator: its energy levels 0, 1, 2, ... are not evenly spaced, and the gap between the 1-2 and 0-1 transitions is about the charging energy **E_C** (`ec_ghz`). That small gap is why a strong pulse meant for 0-1 can also excite state 2 (**leakage**). The 0-1 frequency depends on magnetic flux through the qubit's SQUID loop; the code uses the E_C-corrected asymmetric-SQUID form f(Phi) = (f_max + E_C) [cos^2(pi Phi) + d^2 sin^2(pi Phi)]^(1/4) - E_C, with `d_asym` the junction asymmetry. Qubits relax with **T1** and dephase with **T2\*** (Ramsey time). Thermal excitation is set by the effective temperature.

## 4.2 The four fidelity tiers

A **tier** is a physics engine. Cheaper tiers answer faster but ignore effects the costlier tiers include.

| Tier | Engine | Source | Good for | Limit |
|---|---|---|---|---|
| **T0** | Each qubit is a classical bit. A pulse redistributes the bit by its unitary's transition probabilities; idle time relaxes 1 to 0 at T1. | `physics/surrogate_t0.py` | Scheduler and telemetry tests | No coherence at all |
| **T1a** | Stabiliser simulation with **Stim** (Clifford circuits only). Each pulse is lifted to its unitary, snapped to the nearest Clifford, and the residual coherent error is Pauli-twirled; idle noise is the Pauli-twirl approximation of amplitude and phase damping. | `physics/stim_t1a.py`, `pta.py` | Error correction, large Clifford circuits | Every pulse within 1% of a Clifford (process fidelity at least 0.99) |
| **T1b** | Statevector Monte-Carlo with exact amplitude-damping and dephasing trajectories, using the lifted actual unitaries of the rendered pulses. | `physics/statevector_t1b.py` | Gate-level circuits | Up to 26 qubits; leakage at most 3%; no overlapping pulses on a qubit; leakage out of the qubit subspace is not represented |
| **T2** | Multi-qutrit Lindblad master equation (QuTiP 5) under the real rendered pulses, including detuning, drive, exchange coupling and collapse operators. | `physics/lindblad_t2.py` | Pulse calibration: Rabi, Ramsey, ZZ, CZ chevrons, leakage | 4 qutrits |
| T3 | Quantum trajectories | none | | Not built; requests refused |

Terms: **Clifford** gates are the group that maps Pauli operators to Pauli operators (H, S, CNOT...); they can be simulated efficiently. **Pauli twirling** converts a general error into a random Pauli channel. **Lindblad master equation** evolves a density matrix with the Hamiltonian plus decoherence terms; the collapse operators are sqrt(g(1+nbar)) a, sqrt(g nbar) a-dagger and sqrt(2 g_phi) n. A **qutrit** keeps levels 0, 1 and 2.

Details of T2 (docstring): each qubit is simulated in a rotating frame, the detuning is in the Hamiltonian at all times (so Ramsey fringes exist), pulses that overlap in time evolve together, and virtual Z never touches the state (it arrives as the phase of the drive samples).

### Pulse lifting

Gate-level tiers (T0, T1a, T1b) never guess a gate from a waveform name. The executor renders every play into its actual drive samples, then `physics/lifter.py` integrates those on a closed qutrit (or a few coupled qutrits) and returns the computational-subspace unitary plus the leakage. The nearest Clifford is found against the full 1- and 2-qubit Clifford groups. This is the "lift" in the glossary and the "Lifted gates" panel in the Explorer.

### AUTO routing and "never downgrades silently"

`src/qcss/physics/router.py` decides the tier from the requested tier and the lifted gates. The operator sets the policy at the chassis (`--tier auto|t0|t1a|t1b|t2`); a lab client's `requested_tier` is ignored on the lab link.

Reading the router code:

- `AUTO` picks **T1b** when every pulse lifts to a gate, there are at most 26 qubits and leakage is not needed. It never picks T0.
- Otherwise `AUTO` tries **T1a** (all Clifford, only Pauli feedback, no leakage or non-unital noise needed).
- Otherwise `AUTO` goes to **T2** if there are at most 4 qubits ("pulse-level").
- A raw ADC trace acquisition exists only in T2's physical readout, so it forces T2 (or refuses).
- `T0` runs only when requested.
- `T3`, or a tier that cannot honour the job (T1a with a non-Clifford pulse, T1b with leakage, T2 with more than 4 qutrits), is **refused with a reason**. The job fails at submission (`FAILED_PRECONDITION`), not by quietly running a cheaper tier.

The README adds: jobs whose pulses leak more than 3% out of the qubit subspace, or that overlap a drive and a flux pulse on one qubit, need T2. On the lab link a routing refusal does not name tiers (a regression test is titled "routing refusals on the lab link say nothing about tiers").

`qcss run job.json -d transmon_5q -t T2` (the in-process runner) honours the tier you pass; verified here with a pi-pulse job on T1b: `Tier: T1B (lifts to gates)`, 198 of 200 shots in state 1.

Cost warning (README): a flux pulse on one qubit pulls its neighbours into a 4-qutrit T2 run of about 17 s per sweep point, so a full CZ calibration takes hours.

## 4.3 Readout

Readout turns the qubit state into a reported label. QCSS counts each readout error exactly once and uses two models (`src/qcss/readout/model.py`):

- **PhysicalReadout** (pulse-level tier T2): the true level drives a simulated resonator (`readout/resonator.py`), producing complex ADC traces with a per-level frequency shift, time of flight, quantum-efficiency noise (`eta`), and T1 jumps during the readout (|1> to |0> at about 1/T1, |2> to |1> at about 2/T1). Traces are integrated with weights (`readout/integrator.py`) over the window starting at the acquisition delay, then classified by the discriminator the client configured. There is no confusion matrix on this path.
- **SurrogateReadout** (gate-level tiers): true level, then a **confusion matrix**, then a label, with I/Q points drawn consistently with the label. The matrix is *derived from the physical model* by simulated calibration shots, so fast tiers report the same readout error as T2.
- **Phenomenological** (`readout/phenomenological.py`): the confusion-matrix sampler itself. The label's I/Q is drawn from that label's cloud inside its decision region, so label and I/Q never contradict.

**Discriminators** (`readout/discriminator.py`): `BinaryDiscriminator` rotates the I/Q plane and thresholds on the real axis (Qblox convention); `MultistateDiscriminator` picks the nearest centroid for up to 4 states (ZI convention). The client's rotation and threshold come from the calibration (chapter 5).

## 4.4 Chip effects (what makes the chip a moving target)

`DeviceState` (`src/qcss/device/state.py`) advances these on the **lab clock**. If a device file has no `dynamics:` block, every parameter is static.

| Effect | Model | Defaults in `transmon_5q` |
|---|---|---|
| **Frequency drift** | 1/f flux noise on f01 | `flux_noise_ghz: 1e-4` |
| **T1 drift** | Log-normal Ornstein-Uhlenbeck process (OU: a mean-reverting random walk with exact update for any step) | `t1_sigma_ln 0.08`, `t1_tau_s 7200` |
| **Two-level defects (TLS)** | Each qubit has a bath of defects (coupling 0.05-0.5 MHz, linewidth 0.5-20 MHz, telegraph jumps, switching slowly, spectral diffusion); T1 loss follows a Lorentzian: Gamma1(f_q) = Gamma_bg + sum 2 g^2 gamma / (gamma^2 + (f_q - f_k)^2). A defect landing on the qubit's frequency shortens T1 sharply. | `tls_per_qubit: 5` |
| **Cosmic-ray bursts** | Poisson quasiparticle bursts (impact rate 0.035 per cm^2 per s, rise 10 us, recovery 25 ms, spatial spread over the chip using `xy_mm`, peak extra decay 0.05-2 per us) | `bursts: true` |
| **Hidden mixer and flux-line faults** | Optional `faults:` block: per-qubit IQ mixer gain/phase/DC imbalance and flux-line exponential tails. The client sees only the effect and calibrates against it. | not present in the shipped `transmon_5q.yaml` |
| **Scenarios** | Operator-injected events via the admin channel (chapter 6): kill (T1 100 ns and a 200 MHz shift down), frequency/T1 steps, forced TLS, forced burst | none at start |

The **lab clock** (`device/labclock.py`) never goes backwards. Lab time = wall time x `--time-scale`. It keeps running between jobs, and with `--state-dir` the downtime of a restart counts as lab time (chapter 5). With `--time-scale 0` the chip is frozen and jobs run unpaced.

## 4.5 Signal chain (the "render" stage)

`src/qcss/signal/` turns programmed samples into what the qubit feels, in this order (docstring of `port_renderer.py`):

1. NCO-modulated DAC stream at the intermediate frequency with frame phase (virtual Z, `set_phase`, `set_frequency`).
2. The client's own IQ correction (offsets, gain ratio, phase).
3. The **hidden mixer truth** `x = mu*m + nu*conj(m) + d` (image tone at -2 f_IF, LO leakage at -f_IF, both far off resonance in the qubit frame, as on hardware). Image-to-signal power is about ((g-1)^2 + phi^2)/4 for small errors.
4. Rotation into the qubit frame times the Rabi rate.

Flux ports keep one continuous stream per port. The client's **predistortion** (`predistortion.py`, exponential inverse filters) followed by the hidden **line response** (`filters.py`, Rol-form `s(t) = g[1 + sum A_k e^{-t/tau_k}]`) are stateful IIR filters, so tails leak from pulse to pulse and shot to shot. LO leakage is applied only while a pulse plays, not as a continuous tone between pulses (README limit).

## 4.6 Timing

`src/qcss/timing/`: a job's wall time is an upload latency (log-normal, median 20 ms) plus shots x (sequence + relaxation), divided by `--time-scale`; `host_latency.py` adds log-normal RPC latency (median 1 ms) at the RPC boundary; `jitter.py` adds integer-tick jitter to feedback and sequencer timing. Feedback latency and readout time of flight (cables, filters) are added to the profile's latency figure and checked by the validator, so a branch cannot be scheduled earlier than ready time + latency. Qubits are never silently reset between shots; leave `repetition_delay_ticks` unset to wait 10 x T1 (`runner.py`).

## 4.7 Determinism, seeds and chunks

- **Default: fresh entropy.** `qcss serve --seed N` sets the global seed; without it the chassis draws entropy (`chassis_seed`), as a real lab never repeats. A job's `random_seed` is **ignored** unless `--deterministic` (or `qcss admin mode --deterministic`).
- **Random streams** are keyed by *(domain, sweep index, chunk index)* under a root built from (global seed, job key). Domains: shots, readout, signal, drift, bursts, jitter, stim (`core/seeding.py`).
- **Chunks** are a fixed 1024 shots (`CHUNK_SHOTS`), so with a fixed seed a job reproduces exactly for any worker count or arrival order. Changing it would change golden outputs, so it is a constant, not an option.
- `qcss run` is the in-process tool for physics experiments and **honours the job's seed and tier**, unlike the chassis.

## 4.8 Where the physics is checked

The README states that `tests/oracles/` checks Rabi, Ramsey, T1, Hahn echo, ZZ, CZ, phase fringes, flux offsets and chevrons against analytic formulas at 5 sigma, and `tests/cross_tier/` checks that tiers agree where domains overlap. This manual did not re-run them.

---
Sources: `src/qcss/physics/{router,lifter,surrogate_t0,stim_t1a,statevector_t1b,lindblad_t2,transmon,pta,populations}.py`, `src/qcss/readout/{model,resonator,integrator,discriminator,phenomenological}.py`, `src/qcss/device/{state,drift,tls,bursts,labclock,scenarios}.py`, `src/qcss/signal/{port_renderer,mixer,predistortion,filters}.py`, `src/qcss/timing/*.py`, `src/qcss/core/seeding.py`, `src/qcss/runtime/runner.py`, `src/qcss/config/device.py`, `README.md`. Run: `qcss run` / `qcss validate` on the README job.
