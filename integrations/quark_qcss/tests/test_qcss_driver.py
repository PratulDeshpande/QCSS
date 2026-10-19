"""QcssDeviceProvider (HAL) and QcssExecutionDriver against a real QCSS server, plus the conformance kit."""
from __future__ import annotations

import pathlib
from collections.abc import Iterator

import pytest

from qcss.client import QcssClient
from quark_qcss.conformance import run_conformance
from quark_qcss.contracts import JobStatus, NativeJob
from quark_qcss.driver import QcssExecutionDriver
from quark_qcss.errors import (
    DriverConfigurationError,
    PermanentDriverError,
    StaleCalibrationError,
    TransientDriverError,
)
from quark_qcss.lab.pulse_library import load_pulse_library
from quark_qcss.lab.translator import Translator
from quark_qcss.provider import QcssDeviceProvider
from tests.integration.test_grpc_end_to_end import _can_connect_loopback, _free_port
from tests.integration.test_remote_client import TOKEN, _ServerThread

EXAMPLE = pathlib.Path(__file__).parents[1] / "lab_examples" / "qcss_transmon_5q"


@pytest.fixture(scope="module")
def server() -> Iterator[_ServerThread]:
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    with _ServerThread() as s:
        yield s


@pytest.fixture(scope="module")
def client(server) -> Iterator[QcssClient]:
    with QcssClient(server.addr, token=TOKEN) as c:
        yield c


@pytest.fixture(scope="module")
def provider(client) -> QcssDeviceProvider:
    return QcssDeviceProvider(client, EXAMPLE / "device_profile.yaml")


@pytest.fixture(scope="module")
def driver(client) -> QcssExecutionDriver:
    return QcssExecutionDriver(client, Translator(load_pulse_library(EXAMPLE / "pulse_library.yaml")))


def native(program: str, shots: int = 200, **kw) -> NativeJob:
    return NativeJob(job_id="quark-test", program=program, shots=shots, seed=5, **kw)


def test_conformance_levels_l1_l3_l4_pass(provider, driver):
    checks = run_conformance(provider, driver, shots=200)
    failed = [c for c in checks if not c.passed]
    assert not failed, "\n".join(f"{c.level} {c.name}: {c.detail}" for c in failed)
    assert {c.level for c in checks} == {"L1", "L3", "L4"}


def test_describe_merges_the_profile_with_the_live_device(provider):
    d = provider.describe()
    assert (d.device_id, d.modality, d.maturity_level) == ("qcss-transmon-5q", "superconducting", "L4")
    assert [s["id"] for s in d.sites] == [0, 1, 2, 3, 4]
    assert {op.name for op in d.native_ops} == {"x", "sx", "rz", "measure"}
    assert d.capabilities["submission_level"] == "native-circuit"
    assert d.capabilities["server_transformations"] == []
    assert d.control_stack["profile_name"] == "qblox_cluster_5q"
    assert d.profile_source.startswith("device_profile.yaml@sha256:")


def test_calibration_events_carry_the_device_model_values(client):
    fresh = QcssDeviceProvider(client, EXAMPLE / "device_profile.yaml")       # first poll reports everything
    events = {(e.resource, e.parameter): e for e in fresh.poll_once()}
    props = {q.qubit_index: q for q in client.properties().qubits}
    t1 = events[("q0", "t1")]
    assert t1.value == pytest.approx(props[0].t1_s) and t1.unit == "s"
    assert t1.raw_name == "QubitProperties.t1_s" and t1.adapter == "qcss@v1"
    assert ("q0", "readout_p0_given_1") in events and ("q0-q1", "2q_error") in events
    assert ("device", "custom.calibration_epoch") in events
    assert all(not e.quality_flags for e in events.values())


def test_a_calibration_update_emits_a_new_epoch_event(provider, client):
    provider.poll_once()
    snap = client.get_calibration([0])
    client.update_calibration(snap, expected_epoch=snap.calibration_epoch)
    epoch_events = [e for e in provider.poll_once() if e.parameter == "custom.calibration_epoch"]
    assert [e.value for e in epoch_events] == [snap.calibration_epoch + 1]


def test_counts_use_qasm_bit_order(driver):
    h = driver.submit(native("bit[2] c;\nx $1;\nc[0] = measure $0;\nc[1] = measure $1;"))
    r = driver.result(h)
    assert sum(r.counts.values()) == 200
    assert max(r.counts, key=lambda k: r.counts[k]) == "10"
    assert r.executed_as_submitted and r.calibration_epoch == h.calibration_epoch


def test_unmeasured_bits_read_zero(driver):
    r = driver.result(driver.submit(native("bit[3] c;\nx $0;\nc[0] = measure $0;")))
    assert set(r.counts) <= {"000", "001"}
    assert r.counts.get("001", 0) > 150


def test_status_reaches_completed(driver):
    h = driver.submit(native("bit[1] c;\nc[0] = measure $0;"))
    driver.result(h)
    assert driver.status(h) is JobStatus.COMPLETED


def test_planned_epoch_older_than_the_live_one_is_stale_before_submission(driver, client):
    live = client.get_calibration().calibration_epoch
    with pytest.raises(StaleCalibrationError):
        driver.submit(native("x $0;", calibration_epoch=live + 7))


def test_unsupported_program_is_permanent_and_does_not_trip_the_breaker(driver):
    with pytest.raises(PermanentDriverError) as err:
        driver.submit(native("h $0;"))
    assert not err.value.counts_toward_breaker
    assert "line 1" in str(err.value)


def test_preview_shows_the_pulse_schedule(driver):
    sched = driver.preview(native("bit[1] c;\nx $0;\nc[0] = measure $0;"))
    assert [(e["op"], e["channel"]) for e in sched] == [("play", "xy_q0"), ("acquire", "ro_q0")]


def test_wrong_token_is_a_configuration_error_that_trips_the_breaker(server):
    with QcssClient(server.addr, token="wrong") as c:
        d = QcssExecutionDriver(c, Translator(load_pulse_library(EXAMPLE / "pulse_library.yaml")))
        with pytest.raises(DriverConfigurationError) as err:
            d.submit(native("x $0;"))
    assert err.value.counts_toward_breaker


def test_unreachable_control_stack_is_transient():
    with QcssClient(f"127.0.0.1:{_free_port()}", timeout_s=1.0) as c:
        d = QcssExecutionDriver(c, Translator(load_pulse_library(EXAMPLE / "pulse_library.yaml")))
        with pytest.raises(TransientDriverError) as err:
            d.submit(native("x $0;"))
    assert err.value.transient and err.value.counts_toward_breaker


def test_a_crashing_lab_translator_fails_the_job_not_the_worker(client):
    class Broken:
        def translate(self, *args, **kwargs):
            raise KeyError("bug in lab code")

    d = QcssExecutionDriver(client, Broken())  # type: ignore[arg-type]
    with pytest.raises(PermanentDriverError, match="lab translator failed: KeyError"):
        d.submit(native("x $0;"))


def test_simultaneous_gates_on_a_shared_drive_sequencer_run(driver):
    h = driver.submit(native("bit[2] c;\nrz(0.3) $0;\nrz(0.3) $1;\nx $0;\nx $1;\nc[0] = measure $0;\nc[1] = measure $1;"))
    r = driver.result(h)
    assert r.counts.get("11", 0) > 150
