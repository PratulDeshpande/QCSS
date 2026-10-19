# quark-qcss

Reference Layer-7 driver for Quark-QOS (see `reports/high-level-design.md` §5.7): a `DeviceProvider`
(HAL) and an `ExecutionDriver` that talk to any server implementing `qcss.v1.ControlService`, which is
QCSS today and a lab's control-stack gateway later. The full design is in
[docs/hal-driver-design.md](../../docs/hal-driver-design.md).

| Module | Role |
| --- | --- |
| `quark_qcss.provider.QcssDeviceProvider` | `describe()`, `calibration_stream()`, `request_calibration()` |
| `quark_qcss.driver.QcssExecutionDriver` | `submit()`, `status()`, `result()`, `cancel()`, `preview()` |
| `quark_qcss.errors` | gRPC failures classified as transient, permanent, stale-calibration or configuration |
| `quark_qcss.contracts` | pydantic mirrors of the HLD Appendix B contracts (swap for `quark.contracts`) |
| `quark_qcss.lab` | **Lab-owned**: physical OpenQASM 3 parser, pulse library schema, translator |
| `quark_qcss.conformance` | L1/L3/L4 conformance checks, also runnable as `python -m quark_qcss.conformance` |

```bash
python -m pip install -e . -e integrations/quark_qcss      # from the repository root
python -m quark_qcss.conformance --target 127.0.0.1:50051 \
    --profile integrations/quark_qcss/lab_examples/qcss_transmon_5q/device_profile.yaml \
    --pulse-library integrations/quark_qcss/lab_examples/qcss_transmon_5q/pulse_library.yaml
```
