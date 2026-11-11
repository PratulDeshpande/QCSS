# QCSS tutorial notebooks

The official tutorials of QICK, Qibolab and Qibocal, run against QCSS instead of a real instrument, plus a
set of notebooks showing what QCSS adds. Each notebook starts its own simulated lab (`qcss serve`, a separate
process reached only over the network, as a real board would be) and stops it at the end.

## What these notebooks show, and what they don't

| They show | They don't show |
|---|---|
| The official client code (qick, qibolab, qibocal) runs unchanged: only the connect cell differs, and on a real lab it would differ the same way (a different address) | That the numbers are identical to any particular physical board: no real-board reference data is compared |
| The client sees a real-looking instrument: QICK's remote surface has no method a real `QickSoc` lacks; results come back with the shapes, dtypes and scales a board returns | Behaviour QCSS doesn't simulate yet: every such cell is kept, commented out, under a visible **QCSS gap** note |
| Physics checked against the simulator's true chip (`qcss admin truth`), which no real lab can read | |

## Run them

Use one notebook at a time: each starts a lab on the fixed ports 50051, 50052, 8888 and 6000.

| Folder | Install | Upstream source |
|---|---|---|
| [`qick/`](qick/) | `uv sync --extra qick --extra notebooks`, then `uv pip install qick==0.2.370` (after every `uv sync`) | [qick_demos @ 9d98886](https://github.com/openquantumhardware/qick/tree/9d98886/qick_demos) (qick 0.2.370, MIT) |

- Open in JupyterLab: `uv run --no-sync jupyter lab notebooks/`
- Test every notebook in a folder: `uv run --no-sync python -m pytest --nbmake notebooks/qick -n 1 --nbmake-timeout=600`
- Test the helpers: `uv run --no-sync python -m pytest notebooks/test_helpers.py`

## Index

### QICK (`qick/`): tProc v1 firmware `zcu216_v1_5q`, as the demos at qick 0.2.370 expect

| Notebook | Status on QCSS |
|---|---|
| [00 Send/receive pulse](qick/00_Send_receive_pulse.ipynb) | runs fully |
| [01 Phase-coherent readout](qick/01_Phase_coherent_readout.ipynb) | the AveragerProgram measurements run; the fitted cable delay is 0.33 µs on both readouts. The raw-tProc cells are gaps (`soc.tproc` not served) |
| [02 Sweeping variables](qick/02_Sweeping_variables.ipynb) | runs fully |
| [03 Conditional logic](qick/03_Conditional_logic.ipynb) | runs fully: the pulse plays when the register condition holds and not otherwise |
| [04 Reading, math, writing](qick/04_Reading_Math_Writing.ipynb) | the programs run; reading the tProc memory back is a gap (`soc.tproc` not served) |
| [07 N-D sweeps](qick/07_Sweep_ND_variables.ipynb) | runs fully (slow: about 5 minutes, it sweeps thousands of points) |
| [08 Special buffers](qick/08_Special_buffers.ipynb) | mostly gaps: the DDR4 and multi-rate buffers are not served |
| [09 Photon counting](qick/09_photon_counting.ipynb) | gaps: needs a photon-counting firmware build (edge counter); qick itself refuses on a ZCU216 build without one, as on a real standard board |
| [05 Phase coherence](qick/05_PhaseCoherence_QickProgram.ipynb) | runs fully; the phase-vs-frequency slope (~333 ns) matches the 331 ns cable delay QCSS models |

## Known QCSS gaps found by these notebooks

- **`soc.tproc`, `soc.readouts`, `soc.avg_bufs`, DDR4/MR buffers**: not served (`userdocs/reference/qick-surface.md`).
- **Measurement feedback** (tProc v2 external flag): not simulated.

## Notes for maintainers

- `qick.pyro.make_proxy` replaces IPython's exception handler so errors only print to stderr. A failing cell
  then no longer fails, and nbmake passes a broken notebook. Every QICK connect cell therefore calls
  `_lab.keep_errors_visible()` right after `make_proxy`.
- The figures the official demos save go to `qick/images/`, which is git-ignored.
