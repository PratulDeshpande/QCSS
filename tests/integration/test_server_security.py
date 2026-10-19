"""Bearer-token auth, TLS and the safe-bind guard of the gRPC server."""
from __future__ import annotations

import datetime
import ipaddress
from typing import Any, cast

import grpc
import pytest

from qcss.adapters.grpc_server import UnsafeBindError, check_bind_is_safe, serve
from qcss.runtime.jobs import JobManager
from qcss.v1 import control_service_pb2 as pb
from qcss.v1 import control_service_pb2_grpc as pbg
from qcss.v1 import job_pb2
from tests.integration.test_grpc_end_to_end import _can_connect_loopback, _free_port, fake_runner, fake_validator

TOKEN = "s3cret-token"
pytestmark = pytest.mark.anyio


def _self_signed_cert() -> tuple[bytes, bytes]:
    """PEM (cert, key) for 127.0.0.1 / localhost; skips when `cryptography` is missing."""
    x509 = pytest.importorskip("cryptography.x509")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "qcss-test")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1)).not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                                                        x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                           critical=False)
            .sign(key, hashes.SHA256()))
    return (cert.public_bytes(serialization.Encoding.PEM),
            key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption()))


@pytest.fixture
async def token_server():
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    jobs = JobManager(fake_runner, fake_validator)
    addr = f"127.0.0.1:{_free_port()}"
    server = await serve(addr, jobs, token=TOKEN)
    try:
        yield addr
    finally:
        await server.stop(None)
        await jobs.close()


async def test_missing_token_is_unauthenticated(token_server):
    async with grpc.aio.insecure_channel(token_server) as ch:
        stub = pbg.ControlServiceStub(ch)
        with pytest.raises(grpc.aio.AioRpcError) as err:
            await stub.DescribeDevice(pb.DescribeDeviceRequest())
        assert err.value.code() == grpc.StatusCode.UNAUTHENTICATED


async def test_wrong_token_is_unauthenticated_on_streaming_rpc(token_server):
    async with grpc.aio.insecure_channel(token_server) as ch:
        stub = pbg.ControlServiceStub(ch)
        call = stub.StreamResults(pb.StreamResultsRequest(job_id="x"), metadata=[("authorization", "Bearer nope")])
        with pytest.raises(grpc.aio.AioRpcError) as err:
            async for _ in call:
                pass
        assert err.value.code() == grpc.StatusCode.UNAUTHENTICATED


async def test_correct_token_reaches_the_service(token_server):
    async with grpc.aio.insecure_channel(token_server) as ch:
        stub = pbg.ControlServiceStub(ch)
        md = [("authorization", f"Bearer {TOKEN}")]
        r = await stub.SubmitJob(pb.SubmitJobRequest(job=job_pb2.Job(num_shots=12)), metadata=md)
        assert r.job_id


async def test_health_check_needs_no_token(token_server):
    from grpc_health.v1 import health_pb2, health_pb2_grpc

    async with grpc.aio.insecure_channel(token_server) as ch:
        hc: Any = health_pb2_grpc.HealthStub(cast(Any, ch))
        r = await hc.Check(health_pb2.HealthCheckRequest(service=""))
        assert r.status == health_pb2.HealthCheckResponse.SERVING


async def test_tls_server_accepts_a_client_that_trusts_its_certificate():
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    cert, key = _self_signed_cert()
    jobs = JobManager(fake_runner, fake_validator)
    addr = f"127.0.0.1:{_free_port()}"
    server = await serve(addr, jobs, tls=(cert, key))
    try:
        creds = grpc.ssl_channel_credentials(root_certificates=cert)
        async with grpc.aio.secure_channel(addr, creds) as ch:
            r = await pbg.ControlServiceStub(ch).DescribeDevice(pb.DescribeDeviceRequest())
            assert r is not None
    finally:
        await server.stop(None)
        await jobs.close()


@pytest.mark.parametrize("address", ["127.0.0.1:50051", "localhost:50051", "[::1]:50051",
                                     "unix:C:/tmp/qcss.sock"])
def test_loopback_and_unix_binds_are_safe_without_tls(address):
    check_bind_is_safe(address, tls=False, insecure=False)


@pytest.mark.parametrize("address", ["0.0.0.0:50051", "192.168.1.20:50051", "[::]:50051"])
def test_network_bind_without_tls_is_refused(address):
    with pytest.raises(UnsafeBindError):
        check_bind_is_safe(address, tls=False, insecure=False)


def test_network_bind_is_allowed_with_tls_or_explicit_insecure():
    check_bind_is_safe("0.0.0.0:50051", tls=True, insecure=False)
    check_bind_is_safe("0.0.0.0:50051", tls=False, insecure=True)
