# qcss-qibolab

The Qibolab driver of a QCSS instrument. A platform whose `platform.py` lists a
`QcssController` loads, connects and runs through Qibolab like any lab's platform:
Qibolab compiles circuits from the platform's native-gate definitions, Qibocal
calibrates it and writes `parameters.json`, and the controller plays sequences on the
instrument at `address`.

```python
from qibolab import create_platform          # QIBOLAB_PLATFORMS=<repo>/platforms
platform = create_platform("qcss_qblox_5q")  # QCSS_QBLOX_5Q_ADDRESS=host:port of `qcss serve`
platform.connect()
```

What the controller does with a `play()` call:

- programs the instrument with the platform configs: drive and probe frequencies, and
  the discriminator (`iq_angle`, `threshold`);
- samples every pulse envelope with Qibolab's own code, and sends one job whose program
  points are the points of the sweep grid (amplitude, duration, phase, VirtualZ phase and
  frequency sweepers);
- shapes the results as `ExecutionParameters.results_shape` (single-shot or cyclic;
  discrimination or integration), keyed by acquisition id.

The controller does not support:

- coupler flux lines;
- DC flux offsets and offset sweeps;
- the `drive12` channel.

Asking for any of these is refused with an error.

Instrument tokens come from the environment variable named by `token_env` (default
`QCSS_TOKEN`). TLS is on when `ca_file` is set. `timeout_s` (default 3600) bounds one
`play`.

## Install

```bash
pip install -e integrations/qcss_qibolab     # or, in this repo: uv sync --group lab
```

`qibolab` is pinned to exactly `0.2.17`, because the `Controller` base class lives in the
private `qibolab._core` package; `tests/test_controller_pinning.py` guards that contract.

The package currently depends on the whole `qcss` distribution. At runtime it imports only
`qcss.client`, `qcss.core.ndarray` and the generated `qcss.v1` stubs, but installing it also
installs the simulator's physics dependencies (qutip, stim, scipy, pymatching). Splitting the
client and stubs into a small package of their own is an open decision.

## Behaviour a lab driver would show

- **Calibration pinning.** Each `play` uploads the configs and pins its job to that upload
  (`expected_calibration_epoch`), so a concurrent recalibration ends the job `REJECTED`
  instead of running it on mixed settings.
- **Errors.** An unreachable or rebooting instrument raises `ConnectionError`; a refused or
  failed job raises `RuntimeError` with the instrument's message.
- **No calibration writes.** The controller reads the platform; only Qibocal writes
  `parameters.json` and `calibration.json`.
