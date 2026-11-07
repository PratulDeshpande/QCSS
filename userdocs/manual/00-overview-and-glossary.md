# QCSS User Manual

## Chapter 0: Overview and glossary

**Audience:** a lab scientist or engineer who is new to this simulator, and possibly new to QICK and Qibolab. Every term is explained where it first appears, and again in the glossary at the end of this chapter.

**How to read this manual.** Chapters 1 to 3 get you installed and tell you what you can plug into the simulator. Chapter 4 explains the physics it simulates. Chapters 5 and 6 explain how it behaves like a lab (jobs, calibration, faults). Chapter 7 is the dashboard. Chapters 8 and 9 are security and limits. For copy-paste walkthroughs see `userdocs/quickstart/`.

Status: QCSS is alpha software (version 0.1.0). Things marked **Unverified** in this manual were read from code or documentation but not run.

---

## 0.1 What QCSS is

QCSS (Quantum Control Stack Simulator) is a **virtual superconducting-qubit lab**. It pretends to be two things at once:

1. the **control electronics** a lab buys (for example a Qblox Cluster, a Zurich Instruments SHFQC+, or a QICK board built on an AMD RFSoC), and
2. the **chip** (the qubits in the fridge) behind those electronics.

Software written for real hardware, such as a quantum operating system, Qibolab, Qibocal or a QICK program, can talk to QCSS and be tested before, or alongside, real hardware. The software should not be able to tell it is talking to a simulator.

Three design ideas (taken from the project README):

1. **It enforces real hardware rules.** Timing grid, waveform memory, oscillator ranges and feedback latency come from a YAML description of a real instrument (a *profile*, chapter 3), and each value records where it came from.
2. **It hides the truth.** The simulated chip drifts, has defects, and has hidden impairments. A client is never handed the true parameters. The only calibration anyone sees is what a calibration tool *measured* against the virtual lab.
3. **It behaves like a lab, not like a simulator.** Results use fresh randomness, jobs take (simulated) instrument time, the chip keeps ageing while idle and survives restarts, and simulator-only controls live on a separate admin channel that the lab interface never exposes.

## 0.2 The pieces

| Piece | What it is | Where it is described |
|---|---|---|
| **Chassis** | The long-lived process started by `qcss serve`. It owns the chip, the physics and the clocks. Restarting it is like rebooting the electronics: uploaded settings are lost, the chip carries on. | chapters 5, 8 |
| **Instrument link** | A gRPC service (`qcss.v1.ControlService`) on the chassis. Also called the *lab link*. | chapter 2, 5 |
| **Faces** | The different "plugs" through which clients reach the same chip: the Qibolab driver over gRPC, a Qibosoq-compatible board, and a native QICK board. | chapter 2 |
| **Profile** | A YAML description of one instrument (clock, ports, generators, memory, latencies). | chapter 3 |
| **Device** | A YAML description of the chip (frequencies, T1/T2, couplings, resonators, optional drift and hidden faults). | chapter 3 |
| **Platform** | A Qibolab platform folder (`platforms/qcss_qblox_5q`, `platforms/qcss_rfsoc_5q`). | chapter 2 |
| **Technician** | `qcss technician`: runs the real Qibocal on a schedule and writes the calibration. | chapter 5 |
| **Admin channel** | A second gRPC service on its own address and token, for scenarios, modes and faults. | chapter 6 |
| **QCSS Explorer** | A web dashboard that explains and visualises every layer. | chapter 7 |

## 0.3 How a job flows

A *job* is a program to run on the instrument: pulses to play and measurements to take, repeated for a number of *shots*. Inside the chassis a job goes through five stages (README, "How a job runs inside the chassis"):

1. **Plan.** The job is compiled and checked against the hardware profile. Mistakes (a pulse off the timing grid, too much waveform memory) are refused immediately, before a job id exists. The planner also decides which physics tier will simulate it (chapter 4).
2. **Render.** Each programmed pulse is turned into the drive the qubit would actually receive, including oscillator phase, mixer errors and, for flux lines, filter tails.
3. **Evolve.** The chosen physics tier advances the quantum state under that drive.
4. **Read out.** The qubit state becomes the measurement result (a 0/1/2 label or an I/Q point), with realistic readout error.
5. **Stream.** Results go back in fixed 1024-shot chunks.

## 0.4 What is and is not built

Built and tested (README status): the simulator core, four physics tiers, the chassis, the Qibolab driver and platforms, the Qibosoq-compatible board, the native QICK board (Pyro4, tProc v1 and v2), the admin channel, the Qibocal technician and the Explorer dashboard.

Not built: quantum trajectories (tier T3), the Qblox Q1Simulator face, and the QCoDeS mirror. See chapter 9.

## 0.5 Where to go next

- Want to run unmodified QICK code against it? `userdocs/quickstart/qick-from-a-host.md`.
- Want to use a Qibolab platform? `userdocs/quickstart/qibolab-from-a-host.md`.
- Official upstream docs: QICK https://docs.qick.dev/ and Qibolab https://qibo.science/qibolab/stable/. This manual links to them and does not copy them.

---

## 0.6 Glossary

**ADC / DAC.** Analog-to-digital and digital-to-analog converter. The DAC makes the pulse; the ADC digitises the readout signal.

**Admin channel.** QCSS-only gRPC service for the operator: kill a qubit, read the truth, inject instrument faults. Own address, own token (chapter 6).

**Assignment (confusion) matrix.** Table of P(reported label | true level). It describes readout error.

**Calibration.** The numbers a control system uses to drive the chip correctly (qubit frequency, pi-pulse amplitude, readout threshold...). In QCSS the chip's true values are hidden; the calibration is only what was measured.

**Calibration epoch.** A counter that increases whenever the calibration changes. Writes are compare-and-swap, and a job can be pinned to an epoch (chapter 5).

**Chassis.** The `qcss serve` process.

**Chunk.** A group of 1024 shots. Results stream in chunks, and random streams are keyed by chunk so results do not depend on worker count (chapter 4).

**Compare-and-swap.** An update that succeeds only if the caller's idea of the current version is still correct.

**Cosmic-ray burst.** A short spike of quasiparticles that shortens T1 on nearby qubits (chapter 4).

**Deterministic mode.** `--deterministic`: the chassis honours a job's `random_seed` so a test can replay shots. A real instrument never does.

**Device.** The chip description (YAML). Not to be confused with a hardware profile.

**Discriminator.** Turns an integrated I/Q point into a state label, usually by rotating the plane and applying a threshold.

**Face.** One way for a client to reach the simulated lab (Qibolab gRPC, Qibosoq TCP/JSON, native QICK Pyro4).

**Feedback.** Choosing the next operation from a measurement result within the same shot. Limited by feedback latency.

**Firmware (QICK).** The FPGA bitstream on an RFSoC board. QCSS offers `zcu216_v2_5q` (tProc v2) and `zcu216_v1_5q` (tProc v1).

**Generator.** One output channel of an instrument that plays waveforms (Qblox "sequencer", QICK "signal generator").

**Instrument link.** The main gRPC service; same as lab link.

**IQ mixer.** Hardware that up-converts I and Q signals to a microwave frequency. Imperfect mixers leak the local oscillator and an image tone.

**Leakage.** A qubit pulse that excites the third level (state 2) of the transmon.

**Lab clock.** The simulated lab time. Lab time = wall time x `--time-scale`.

**Lindblad master equation.** The equation that evolves a quantum state including decoherence, used by tier T2.

**Lift.** Reducing a rendered pulse to the gate it performs (a unitary matrix plus leakage), so gate-level tiers can use it.

**NCO.** Numerically controlled oscillator: the digital oscillator that sets a pulse's carrier frequency and phase.

**Profile.** The instrument description (YAML).

**Pyro4.** The Python remote-object library QICK uses between a PC and the board.

**QICK.** Quantum Instrumentation Control Kit: open-source firmware and Python software for RFSoC boards. https://docs.qick.dev/

**Qibolab / Qibocal / Qibosoq.** Qibo-ecosystem packages: Qibolab controls hardware (https://qibo.science/qibolab/stable/), Qibocal runs calibration routines, Qibosoq is a server that exposes a QICK-based RFSoC board over TCP.

**Qutrit.** A three-level system. Transmons are simulated with 3 levels (0, 1, 2) in tier T2.

**Shot.** One run of the program from start to measurement.

**Surrogate.** A cheaper stand-in model; tier T0 and the confusion-matrix readout are surrogates.

**Tick.** The integer time unit of the simulator: a common multiple of every clock in a profile, so all scheduling is exact integer arithmetic.

**Tier.** A physics engine of a given fidelity: T0, T1a, T1b, T2 (chapter 4).

**Time of flight (ToF).** Delay of the readout signal through cables and filters.

**TLS (two-level system).** A microscopic defect that can absorb energy from a qubit when their frequencies match.

**tProc.** QICK's on-board timed processor. tProc v1 and v2 are two generations with different instruction sets.

**Truth.** The real, hidden state of the simulated chip. Only the admin channel can read it.

**Virtual Z.** A Z rotation applied by changing the phase of later pulses, taking no time.

---
Sources: `README.md`, `SECURITY.md`, `src/qcss/runtime/jobs.py`, `src/qcss/runtime/runner.py`, `src/qcss/boards/qick/firmware.py`, `src/qcss/core/timebase.py` (read via graph), `integrations/qcss_dashboard/web/src/views/Learn.tsx` (concept list).
