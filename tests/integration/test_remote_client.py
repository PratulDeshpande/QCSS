"""QcssClient against a real simulation server on loopback, with the token and TLS a LAN deployment uses."""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from typing import Self

import grpc
import numpy as np
import pytest

from qcss.adapters.grpc_server import describe_device, serve
from qcss.client import QcssClient, QcssRpcError, counts
from qcss.config.loader import load_device, load_profile
from qcss.core.ndarray import to_proto
from qcss.core.timebase import TimeBase
from qcss.runtime.jobs import JobManager
from qcss.runtime.runner import SimulationContext, create_simulation_runner, create_simulation_validator
from qcss.v1 import job_pb2, result_pb2
from tests.conftest import PROFILES_DIR, REPO_ROOT
from tests.integration.test_grpc_end_to_end import _can_connect_loopback, _free_port
from tests.integration.test_server_security import _self_signed_cert

TOKEN = "lan-token"


class _ServerThread:
    """A real `qcss serve` equivalent on its own event loop, so the synchronous client can call it."""

    def __init__(self, tls: tuple[bytes, bytes] | None = None) -> None:
        self.addr = f"127.0.0.1:{_free_port()}"
        self._tls = tls
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self) -> None:
        prof = load_profile(PROFILES_DIR / "qblox_cluster_5q.yaml")
        dev = load_device(REPO_ROOT / "src" / "qcss" / "config" / "devices" / "transmon_5q.yaml")
        tb = TimeBase.from_clocks(prof.clock.tick_hz)
        ctx = SimulationContext(prof, dev, tb, global_seed=1)
        jobs = JobManager(create_simulation_runner(prof, dev, tb, context=ctx),
                          create_simulation_validator(prof, tb, dev, context=ctx))
        server = await serve(self.addr, jobs, describe_device(prof, ctx.bindings), ctx.calibration,
                             tls=self._tls, token=TOKEN, properties=ctx.device_properties)
        self._stop = asyncio.Event()
        self._ready.set()
        await self._stop.wait()
        await server.stop(None)
        await jobs.close()

    def __enter__(self) -> Self:
        self._thread.start()
        assert self._ready.wait(30), "server did not start"
        return self

    def __exit__(self, *exc: object) -> None:
        assert self._stop is not None
        self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(30)


@pytest.fixture(scope="module")
def server() -> Iterator[_ServerThread]:
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    with _ServerThread() as s:
        yield s


@pytest.fixture
def client(server) -> Iterator[QcssClient]:
    with QcssClient(server.addr, token=TOKEN) as c:
        yield c


def pi_job(shots: int = 200, *, qubit: int = 0, amplitude: float = 0.5) -> job_pb2.Job:
    job = job_pb2.Job(num_shots=shots, requested_tier=job_pb2.FIDELITY_TIER_T1B_STATEVECTOR, random_seed=7,
                      waveform_library={"pi": job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE,
                                                               length_samples=20)})
    job.main.instructions.add(play=job_pb2.Play(channel_id=f"xy_q{qubit}", waveform_id="pi", amplitude=amplitude))
    job.main.instructions.add(start_tick=24, acquire=job_pb2.Acquire(
        channel_id=f"ro_q{qubit}", integration_ticks=1000, mode=job_pb2.ACQUISITION_MODE_DISCRIMINATED,
        result_key=f"q{qubit}"))
    return job


def test_health_describe_and_properties(client):
    assert client.health()
    assert any(c.channel_id == "xy_q0" for c in client.describe().channels)
    assert len(client.properties().qubits) == 5


def test_pi_pulse_reads_out_mostly_one(client):
    job_id, _ = client.submit(pi_job(), quark_job_id="quark-123")
    assert client.wait(job_id).state == result_pb2.JOB_STATE_COMPLETED
    c = counts(list(client.results(job_id)))
    assert sum(c.values()) == 200
    assert c.get("1", 0) > 150


def test_hardware_violation_carries_field_paths(client):
    bad = pi_job()
    bad.main.instructions[0].play.channel_id = "xy_q99"
    with pytest.raises(QcssRpcError) as err:
        client.submit(bad)
    assert err.value.code == grpc.StatusCode.INVALID_ARGUMENT
    assert err.value.field_violations and all(f for f, _ in err.value.field_violations)


def test_stale_job_epoch_is_a_failed_precondition(client):
    job = pi_job()
    job.expected_calibration_epoch = client.get_calibration().calibration_epoch + 100
    with pytest.raises(QcssRpcError) as err:
        client.submit(job)
    assert err.value.code == grpc.StatusCode.FAILED_PRECONDITION
    assert [t for t, _, _ in err.value.precondition_failures] == ["CALIBRATION_EPOCH"]


def test_calibration_update_is_compare_and_swap(client):
    snap = client.get_calibration([0])
    new_epoch = client.update_calibration(snap, expected_epoch=snap.calibration_epoch)
    assert new_epoch == snap.calibration_epoch + 1
    with pytest.raises(QcssRpcError) as err:
        client.update_calibration(snap, expected_epoch=snap.calibration_epoch)
    assert err.value.code == grpc.StatusCode.FAILED_PRECONDITION


def test_results_resume_after_a_sequence_number(client):
    job_id, _ = client.submit(pi_job(shots=2500))
    client.wait(job_id)
    assert [c.sequence_number for c in client.results(job_id)] == [1, 2, 3]
    assert [c.sequence_number for c in client.results(job_id, resume_after=1)] == [2, 3]


def test_cancel_returns_a_status(client):
    job_id, _ = client.submit(pi_job(shots=20_000))
    assert client.cancel(job_id).job_id == job_id


def test_wrong_token_is_unauthenticated(server):
    with QcssClient(server.addr, token="wrong") as c, pytest.raises(QcssRpcError) as err:
        c.describe()
    assert err.value.code == grpc.StatusCode.UNAUTHENTICATED


def test_tls_client_trusts_the_server_certificate():
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    cert, key = _self_signed_cert()
    with _ServerThread(tls=(cert, key)) as s, QcssClient(s.addr, tls_ca=cert, token=TOKEN) as c:
        assert c.health()
        assert len(c.describe().channels) > 0


def _chunk(seq: int, **states: list[int]) -> result_pb2.ResultChunk:
    return result_pb2.ResultChunk(sequence_number=seq, num_shots_in_chunk=len(next(iter(states.values()))),
                                  acquisitions=[result_pb2.AcquisitionResult(
                                      result_key=k, states=to_proto(np.asarray(v, dtype=np.uint8)))
                                      for k, v in states.items()])


def test_counts_join_keys_with_the_first_key_as_the_rightmost_bit():
    chunks = [_chunk(1, c0=[1, 0, 1], c1=[0, 0, 1]), _chunk(2, c0=[1], c1=[1])]
    assert counts(chunks, ["c0", "c1"]) == {"01": 1, "00": 1, "11": 2}
    assert counts(chunks, ["c1"]) == {"0": 2, "1": 2}
