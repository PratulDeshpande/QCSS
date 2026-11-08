# About the Author & Project

**QCSS (Quantum Control Stack Simulator)** was conceived, designed, and developed by **Pratul Deshpande**.

---

## The Vision Behind QCSS

Developing quantum control software, operating systems, and calibration pipelines typically requires continuous access to multimillion-dollar dilution refrigerators and specialized room-temperature control electronics (such as Qblox clusters, Zurich Instruments SHFQC, or AMD Xilinx RFSoC boards running QICK). 

Access to physical quantum hardware is scarce, expensive, and fragile:
- Calibrations drift continuously.
- Hardware is booked for physics experiments and cannot easily be used for software integration testing.
- Software bugs can damage expensive cryogenic components or misconfigure amplifiers.

**Pratul Deshpande** created QCSS to provide a **virtual superconducting-qubit laboratory**. QCSS acts as a hardware-faithful drop-in emulator that stands in for real control electronics and transmon chips. It allows engineers and researchers to develop, test, and validate quantum operating systems (such as Quark) and control libraries (such as Qibolab) from their laptops or in continuous integration (CI) environments without physical hardware.

---

## Architectural Principles

Under Pratul's design, QCSS adheres to three foundational rules:

1. **Hardware-Faithful Constraints:** Every constant—timing grids, sampling rates, NCO ranges, waveform memories, and loopback latencies—mirrors real instrument profiles (Qblox, Zurich Instruments, and QICK RFSoC).
2. **Hidden Physical Truth:** The simulator maintains hidden physical drift, flux crosstalk, and mixer imperfections. Clients (such as Qibolab or Qibocal) never see the "true" parameters; they must calibrate against the virtual lab just as they would against a real dilution fridge.
3. **Lab-Like Behavior:** Physics simulations run with fresh quantum entropy, experiments take realistic instrument execution time, and chip state persists across reboots.

---

## Ecosystem

The QCSS ecosystem created and maintained by Pratul Deshpande includes:

- **`qcss`**: The core simulator, physics engines (Lindblad, stochastic, Hamiltonian, oracle), gRPC services, and chassis runtime.
- **`qcss-qibolab`**: Native driver integration allowing Qibolab platforms to treat QCSS as physical lab hardware.
- **`qcss-dashboard` (QCSS Explorer)**: Modern web-based dashboard and visualization suite for inspecting chip state, calibrations, and waveforms.
- **`userdocs`**: Comprehensive documentation following the Diátaxis framework (tutorials, how-tos, reference, and manual).

---

## Connect & Citation

- **GitHub:** [@PratulDeshpande](https://github.com/PratulDeshpande)
- **Repository:** [github.com/PratulDeshpande/QCSS](https://github.com/PratulDeshpande/QCSS)
- **Issues & Contributions:** [github.com/PratulDeshpande/QCSS/issues](https://github.com/PratulDeshpande/QCSS/issues)

If you use QCSS in academic research, educational coursework, or industrial benchmarking, please cite the project using the metadata in [CITATION.cff](https://github.com/PratulDeshpande/QCSS/blob/main/CITATION.cff):

```bibtex
@software{Deshpande_QCSS_2026,
  author  = {Deshpande, Pratul},
  title   = {QCSS: Quantum Control Stack Simulator},
  year    = {2026},
  url     = {https://github.com/PratulDeshpande/QCSS},
  license = {Apache-2.0}
}
```
