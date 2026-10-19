"""grpc.aio ControlService with rich status, calibration epochs, health checking, and reflection."""
from __future__ import annotations

import inspect

import grpc

from qcss.adapters.errors import failed_precondition_status, invalid_argument_status
from qcss.core.errors import HardwareValidationError, TierRoutingError
from qcss.runtime.calibration_store import CalibrationEpochError, CalibrationStore
from qcss.runtime.jobs import JobManager
from qcss.v1 import control_service_pb2 as pb
from qcss.v1 import control_service_pb2_grpc as pbg
from qcss.v1 import device_pb2


class ControlService(pbg.ControlServiceServicer):
    def __init__(self, jobs: JobManager, device: pb.DescribeDeviceResponse,
                 calibration: CalibrationStore | None = None) -> None:
        self.jobs = jobs
        self.device = device
        self.calibration = calibration if calibration is not None else CalibrationStore()

    async def SubmitJob(self, request, context):
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
            await context.abort_with_status(failed_precondition_status("FIDELITY_TIER", "job.requested_tier", str(err)))

    async def GetJobStatus(self, request, context):
        try:
            return pb.GetJobStatusResponse(status=self.jobs.status(request.job_id))
        except KeyError:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"unknown job {request.job_id}")

    async def CancelJob(self, request, context):
        try:
            return pb.CancelJobResponse(status=self.jobs.cancel(request.job_id))
        except KeyError:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"unknown job {request.job_id}")

    async def StreamResults(self, request, context):
        if not self.jobs.has_job(request.job_id):
            await context.abort(grpc.StatusCode.NOT_FOUND, f"unknown job {request.job_id}")
        async for chunk in self.jobs.results(request.job_id):
            if request.resume_after_sequence and chunk.sequence_number <= request.resume_after_sequence:
                continue
            yield pb.StreamResultsResponse(chunk=chunk)

    async def GetCalibration(self, request, context):
        return pb.GetCalibrationResponse(snapshot=self.calibration.snapshot(list(request.qubit_indices)))

    async def UpdateCalibration(self, request, context):
        try:
            return pb.UpdateCalibrationResponse(new_epoch=self.calibration.update(request.snapshot,
                                                                                  request.expected_epoch))
        except CalibrationEpochError as err:
            await context.abort_with_status(failed_precondition_status("CALIBRATION_EPOCH", "expected_epoch", str(err)))

    async def DescribeDevice(self, request, context):
        return self.device


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
                          sample_rate_hz=float(gens[b.generator_id].sample_rate_hz))
    return pb.DescribeDeviceResponse(device=desc)


async def serve(
    address: str, jobs: JobManager, device: pb.DescribeDeviceResponse | None = None,
    calibration: CalibrationStore | None = None,
) -> grpc.aio.Server:
    """address: 'unix:C:/.../qcss.sock' (Windows 10+) or '127.0.0.1:50051'.
    Never bind 0.0.0.0 without TLS.
    """
    device_desc = device if device is not None else pb.DescribeDeviceResponse()
    server = grpc.aio.server(
        options=[
            ("grpc.max_send_message_length", 16 << 20),
            ("grpc.max_receive_message_length", 16 << 20),
        ]
    )
    pbg.add_ControlServiceServicer_to_server(ControlService(jobs, device_desc, calibration), server)
    service_name = pb.DESCRIPTOR.services_by_name["ControlService"].full_name

    # Health checking (grpcio-health-checking): SERVING for the server and ControlService
    try:
        from grpc_health.v1 import health, health_pb2, health_pb2_grpc
        health_servicer = health.aio.HealthServicer() if hasattr(health, "aio") else health.HealthServicer()
        health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
        for name in ("", service_name):
            res = health_servicer.set(name, health_pb2.HealthCheckResponse.SERVING)
            if inspect.isawaitable(res):
                await res
        health_name = health.SERVICE_NAME
    except ImportError:
        health_name = None

    # Server reflection (grpcio-reflection)
    try:
        from grpc_reflection.v1alpha import reflection
        names = [service_name, reflection.SERVICE_NAME] + ([health_name] if health_name else [])
        reflection.enable_server_reflection(names, server)
    except ImportError:
        pass

    port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"could not bind address {address}")
    await server.start()
    return server
