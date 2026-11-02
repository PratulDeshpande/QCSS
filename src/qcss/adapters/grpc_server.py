"""grpc.aio ControlService with rich status, calibration epochs, health checking, and reflection."""
from __future__ import annotations

import hmac
import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, NoReturn, Protocol

import grpc

from qcss.adapters.errors import failed_precondition_status, invalid_argument_status
from qcss.adapters.instrument_faults import InstrumentFaultInterceptor, InstrumentFaults
from qcss.core.errors import HardwareValidationError, TierRoutingError
from qcss.core.net import is_local_address
from qcss.runtime.calibration_store import CalibrationEpochError, CalibrationStore
from qcss.runtime.jobs import JobManager, ResultsEvictedError
from qcss.v1 import control_service_pb2 as pb
from qcss.v1 import control_service_pb2_grpc as pbg
from qcss.v1 import device_pb2


class ServicerContext(Protocol):
    """The part of grpc.aio.ServicerContext the servicer uses. Both calls end the RPC by raising."""

    async def abort(self, code: grpc.StatusCode, details: str = "") -> NoReturn: ...

    async def abort_with_status(self, status: grpc.Status) -> NoReturn: ...


class ControlService(pbg.ControlServiceServicer):
    def __init__(self, jobs: JobManager, device: pb.DescribeDeviceResponse,
                 calibration: CalibrationStore | None = None,
                 properties: Callable[[], device_pb2.DeviceProperties] | None = None) -> None:
        self.jobs = jobs
        self.device = device
        self.calibration = calibration if calibration is not None else CalibrationStore()
        self.properties = properties

    async def SubmitJob(self, request: pb.SubmitJobRequest, context: ServicerContext) -> pb.SubmitJobResponse:
        try:
            job_id = await self.jobs.submit(request.job)
            info = self.jobs.info(job_id)
            return pb.SubmitJobResponse(job_id=job_id,
                                        calibration_epoch=getattr(info, "calibration_epoch", self.calibration.epoch))
        except HardwareValidationError as err:
            await context.abort_with_status(invalid_argument_status(err))
        except CalibrationEpochError as err:
            await context.abort_with_status(failed_precondition_status("CALIBRATION_EPOCH", "job.expected_calibration_epoch",
                                                                       str(err)))
        except TierRoutingError as err:
            if not self.jobs.expose_diagnostics:            # a lab chassis: the instrument's words, not the engine's
                await context.abort_with_status(failed_precondition_status(
                    "INSTRUMENT_RESOURCES", "job", "the sequence exceeds the instrument's resources"))
            await context.abort_with_status(failed_precondition_status("FIDELITY_TIER", "job.requested_tier", str(err)))

    async def GetJobStatus(self, request: pb.GetJobStatusRequest, context: ServicerContext) -> pb.GetJobStatusResponse:
        try:
            return pb.GetJobStatusResponse(status=self.jobs.status(request.job_id))
        except KeyError:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"unknown job {request.job_id}")

    async def CancelJob(self, request: pb.CancelJobRequest, context: ServicerContext) -> pb.CancelJobResponse:
        try:
            return pb.CancelJobResponse(status=self.jobs.cancel(request.job_id))
        except KeyError:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"unknown job {request.job_id}")

    async def StreamResults(self, request: pb.StreamResultsRequest,
                            context: ServicerContext) -> AsyncIterator[pb.StreamResultsResponse]:
        if not self.jobs.has_job(request.job_id):
            await context.abort(grpc.StatusCode.NOT_FOUND, f"unknown job {request.job_id}")
        try:
            async for chunk in self.jobs.results(request.job_id, request.resume_after_sequence):
                yield pb.StreamResultsResponse(chunk=chunk)
        except ResultsEvictedError as err:
            await context.abort(grpc.StatusCode.OUT_OF_RANGE, str(err))

    async def GetCalibration(self, request: pb.GetCalibrationRequest,
                             context: ServicerContext) -> pb.GetCalibrationResponse:
        return pb.GetCalibrationResponse(snapshot=self.calibration.snapshot(list(request.qubit_indices)))

    async def UpdateCalibration(self, request: pb.UpdateCalibrationRequest,
                                context: ServicerContext) -> pb.UpdateCalibrationResponse:
        try:
            return pb.UpdateCalibrationResponse(new_epoch=self.calibration.update(request.snapshot,
                                                                                  request.expected_epoch))
        except CalibrationEpochError as err:
            await context.abort_with_status(failed_precondition_status("CALIBRATION_EPOCH", "expected_epoch", str(err)))

    async def DescribeDevice(self, request: pb.DescribeDeviceRequest,
                             context: ServicerContext) -> pb.DescribeDeviceResponse:
        return self.device

    async def GetDeviceProperties(self, request: pb.GetDevicePropertiesRequest,
                                  context: ServicerContext) -> pb.GetDevicePropertiesResponse:
        if self.properties is None:
            await context.abort(grpc.StatusCode.UNIMPLEMENTED, "Method not implemented!")
        return pb.GetDevicePropertiesResponse(properties=self.properties())


def describe_device(profile, bindings) -> pb.DescribeDeviceResponse:
    """DeviceDescription from the hardware profile and the channel bindings the server offers."""
    kinds = {"drive": device_pb2.CHANNEL_KIND_DRIVE, "flux": device_pb2.CHANNEL_KIND_FLUX,
             "readout": device_pb2.CHANNEL_KIND_READOUT, "cross_resonance": device_pb2.CHANNEL_KIND_CROSS_RESONANCE}
    gens = {g.generator_id: g for g in profile.generators}
    desc = device_pb2.DeviceDescription(profile_name=profile.profile_name, vendor=profile.vendor,
                                        tick_hz=str(profile.clock.tick_hz),
                                        max_discriminated_states=profile.acquisition.max_discriminated_states)
    for b in bindings.values():
        desc.channels.add(channel_id=b.channel_id, kind=kinds[str(b.kind)], generator_id=b.generator_id,
                          port_id=b.port_id, frame_id=b.frame_id, qubits=list(b.qubits),
                          sample_rate_hz=float(gens[b.generator_id].sample_rate_hz),
                          lo_frequency_hz=profile.port(b.port_id).lo_frequency_hz or 0.0)
    return pb.DescribeDeviceResponse(device=desc)


log = logging.getLogger("qcss.grpc")

# Methods reachable without a token: liveness probes must work before a client has credentials.
_PUBLIC_METHOD_PREFIXES = ("/grpc.health.v1.Health/",)


class UnsafeBindError(ValueError):
    """A network-reachable bind without TLS and a token (anyone on the network could submit jobs and rewrite
    calibration)."""


def check_bind_is_safe(address: str, *, tls: bool, token: bool, insecure: bool) -> None:
    """Refuse a non-loopback TCP bind unless it has both TLS and a bearer token, or insecure=True."""
    if (tls and token) or insecure or is_local_address(address):
        return
    missing = " and ".join(m for m, ok in (("TLS", tls), ("a token", token)) if not ok)
    raise UnsafeBindError(f"refusing to bind {address} without {missing}; pass --tls-cert/--tls-key and "
                          "--token, or --insecure on a network you trust")


class BearerTokenInterceptor(grpc.aio.ServerInterceptor):
    """Rejects calls without `authorization: Bearer <token>` (health checks exempt); logs the OS's trace ids."""

    def __init__(self, token: str | None) -> None:
        self._expected = f"Bearer {token}".encode() if token else None

    async def intercept_service(
        self, continuation: Callable[[grpc.HandlerCallDetails], Awaitable[grpc.RpcMethodHandler | None]],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler | None:
        md = {k: v for k, v in (handler_call_details.invocation_metadata or ())}
        method = handler_call_details.method or ""
        job_id, trace = md.get("x-quark-job-id"), md.get("traceparent")
        if job_id or trace:
            log.info("rpc %s quark_job_id=%s traceparent=%s", method, job_id, trace)
        handler = await continuation(handler_call_details)
        if handler is None or self._expected is None or method.startswith(_PUBLIC_METHOD_PREFIXES):
            return handler
        got = md.get("authorization", "")
        if hmac.compare_digest(str(got).encode(), self._expected):
            return handler
        return _deny(handler)


def _deny(handler: grpc.RpcMethodHandler) -> grpc.RpcMethodHandler:
    """A handler of the same streaming kind that ends the call with UNAUTHENTICATED."""
    async def abort(_request: Any, context: grpc.aio.ServicerContext) -> Any:
        await context.abort(grpc.StatusCode.UNAUTHENTICATED, "missing or invalid bearer token")

    async def abort_stream(_request: Any, context: grpc.aio.ServicerContext) -> AsyncIterator[Any]:
        await context.abort(grpc.StatusCode.UNAUTHENTICATED, "missing or invalid bearer token")
        yield  # pragma: no cover  (makes this an async generator)

    kw = {"request_deserializer": handler.request_deserializer, "response_serializer": handler.response_serializer}
    if handler.unary_unary:
        return grpc.unary_unary_rpc_method_handler(abort, **kw)
    if handler.unary_stream:
        return grpc.unary_stream_rpc_method_handler(abort_stream, **kw)
    if handler.stream_unary:
        return grpc.stream_unary_rpc_method_handler(abort, **kw)
    return grpc.stream_stream_rpc_method_handler(abort_stream, **kw)


async def serve(
    address: str, jobs: JobManager, device: pb.DescribeDeviceResponse | None = None,
    calibration: CalibrationStore | None = None, *,
    tls: tuple[bytes, bytes] | None = None, token: str | None = None,
    properties: Callable[[], device_pb2.DeviceProperties] | None = None,
    reflection: bool = False,
    faults: InstrumentFaults | None = None,
) -> grpc.aio.Server:
    """address: 'unix:C:/.../qcss.sock' (Windows 10+) or '127.0.0.1:50051'.
    tls: PEM (certificate chain, private key); token: required as `authorization: Bearer <token>`.
    Never bind 0.0.0.0 without TLS (see check_bind_is_safe).
    reflection: advertise the services (debugging only; an instrument does not describe its own API).
    faults: instrument faults injected through the admin channel, applied to every call but health checks.
    """
    device_desc = device if device is not None else pb.DescribeDeviceResponse()
    server = grpc.aio.server(
        interceptors=[BearerTokenInterceptor(token)] + ([InstrumentFaultInterceptor(faults)] if faults else []),
        options=[
            ("grpc.max_send_message_length", 16 << 20),
            ("grpc.max_receive_message_length", 16 << 20),
            # Clients may ping idle connections every 20 s or more; tighter pings get GOAWAY too_many_pings.
            ("grpc.keepalive_permit_without_calls", 1),
            ("grpc.http2.min_ping_interval_without_data_ms", 10_000),
            ("grpc.http2.max_pings_without_data", 0),
        ],
    )
    pbg.add_ControlServiceServicer_to_server(ControlService(jobs, device_desc, calibration, properties), server)
    service_name = pb.DESCRIPTOR.services_by_name["ControlService"].full_name

    # Health checking (grpcio-health-checking): SERVING for the server and ControlService
    try:
        from grpc_health.v1 import health, health_pb2, health_pb2_grpc
        aio_health = getattr(health, "aio", None)          # async servicer only in newer grpcio-health-checking
        health_servicer = aio_health.HealthServicer() if aio_health is not None else health.HealthServicer()
        health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
        for name in ("", service_name):
            res = health_servicer.set(name, health_pb2.HealthCheckResponse.SERVING)
            if inspect.isawaitable(res):
                await res
        health_name = health.SERVICE_NAME
    except ImportError:
        health_name = None

    if reflection:
        try:
            from grpc_reflection.v1alpha import reflection as grpc_reflection
            names = [service_name, grpc_reflection.SERVICE_NAME] + ([health_name] if health_name else [])
            grpc_reflection.enable_server_reflection(names, server)
        except ImportError:
            pass

    if tls is not None:
        port = server.add_secure_port(address, grpc.ssl_server_credentials([(tls[1], tls[0])]))
    else:
        port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"could not bind address {address}")
    await server.start()
    return server
