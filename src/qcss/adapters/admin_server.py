"""AdminService: the operator's and CI's controls of the simulated lab.

Served on its own address with its own token (never on the instrument link), so nothing a
lab client can reach reveals or changes the simulation.
"""
from __future__ import annotations

from collections.abc import Callable

import grpc
from grpc.aio import ServicerContext

from qcss.adapters.grpc_server import BearerTokenInterceptor
from qcss.adapters.instrument_faults import InstrumentFaults
from qcss.admin.v1 import admin_pb2 as apb
from qcss.admin.v1 import admin_pb2_grpc as apbg
from qcss.device.state import DeviceState
from qcss.runtime.jobs import JobManager
from qcss.runtime.runner import REQUESTED, SimulationContext
from qcss.v1 import job_pb2

_TIER_ENUM = {name: enum for enum, name in REQUESTED.items()}


class AdminService(apbg.AdminServiceServicer):
    def __init__(self, ctx: SimulationContext, jobs: JobManager, faults: InstrumentFaults) -> None:
        self.ctx, self.jobs, self.faults = ctx, jobs, faults

    async def _scenario(self, context: ServicerContext, change: Callable[[DeviceState], None]) -> None:
        state = self.ctx.device_state
        if state is None:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, "the chassis runs without a device file")
            return
        try:
            with self.ctx.device_lock:
                self.ctx.device_parameters(self.ctx.lab_time_s)       # bring the chip to now first
                change(state)
        except KeyError as err:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(err.args[0]) if err.args else str(err))
        except ValueError as err:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(err))

    # ------------------------------------------------------------------ physics scenarios
    async def KillQubit(self, request: apb.KillQubitRequest, context: ServicerContext) -> apb.KillQubitResponse:
        await self._scenario(context, lambda s: s.kill_qubit(request.qubit_index))
        return apb.KillQubitResponse()

    async def ReviveQubit(self, request: apb.ReviveQubitRequest,
                          context: ServicerContext) -> apb.ReviveQubitResponse:
        await self._scenario(context, lambda s: s.revive_qubit(request.qubit_index))
        return apb.ReviveQubitResponse()

    async def DriftStep(self, request: apb.DriftStepRequest, context: ServicerContext) -> apb.DriftStepResponse:
        await self._scenario(context, lambda s: s.drift_step(
            request.qubit_index, df_ghz=request.delta_frequency_hz * 1e-9, t1_factor=request.t1_factor or 1.0))
        return apb.DriftStepResponse()

    async def TlsCollision(self, request: apb.TlsCollisionRequest,
                           context: ServicerContext) -> apb.TlsCollisionResponse:
        await self._scenario(context, lambda s: s.tls_collision(
            request.qubit_index, g_mhz=request.coupling_hz * 1e-6 or 0.5,
            gamma_mhz=request.linewidth_hz * 1e-6 or 1.0, detuning_mhz=request.detuning_hz * 1e-6))
        return apb.TlsCollisionResponse()

    async def Burst(self, request: apb.BurstRequest, context: ServicerContext) -> apb.BurstResponse:
        await self._scenario(context, lambda s: s.burst(
            request.qubit_index, peak_gamma_per_us=request.peak_gamma_per_s * 1e-6 or 2.0))
        return apb.BurstResponse()

    async def FreezeDrift(self, request: apb.FreezeDriftRequest,
                          context: ServicerContext) -> apb.FreezeDriftResponse:
        await self._scenario(context, lambda s: s.freeze(request.frozen))
        return apb.FreezeDriftResponse()

    async def ClearScenarios(self, request: apb.ClearScenariosRequest,
                             context: ServicerContext) -> apb.ClearScenariosResponse:
        await self._scenario(context, lambda s: s.clear_scenarios())
        return apb.ClearScenariosResponse()

    # ------------------------------------------------------------------ mode
    def _mode(self) -> apb.Mode:
        tier = _TIER_ENUM.get(self.ctx.tier_policy or "", job_pb2.FIDELITY_TIER_UNSPECIFIED)
        return apb.Mode(time_scale=self.ctx.time_scale, deterministic=self.ctx.honour_job_seed, tier_policy=tier)

    async def GetMode(self, request: apb.GetModeRequest, context: ServicerContext) -> apb.GetModeResponse:
        return apb.GetModeResponse(mode=self._mode(), global_seed=self.ctx.global_seed)

    async def SetMode(self, request: apb.SetModeRequest, context: ServicerContext) -> apb.SetModeResponse:
        m = request.mode
        if m.time_scale < 0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "time_scale must be >= 0")
        if m.tier_policy not in REQUESTED:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"unknown tier {m.tier_policy}")
        self.ctx.set_time_scale(m.time_scale)
        self.ctx.honour_job_seed = m.deterministic
        # UNSPECIFIED is what GetMode reports with no policy set: each job's requested tier is honoured.
        # Mapping it to AUTO (as the job channel does) would make a GetMode/SetMode round trip change it.
        self.ctx.tier_policy = (None if m.tier_policy == job_pb2.FIDELITY_TIER_UNSPECIFIED
                                else REQUESTED[m.tier_policy])
        return apb.SetModeResponse(mode=self._mode())

    # ------------------------------------------------------------------ what only the simulator knows
    async def ReadTruth(self, request: apb.ReadTruthRequest, context: ServicerContext) -> apb.ReadTruthResponse:
        lab_t = self.ctx.lab_time_s
        f_ghz, t1_ns = self.ctx.device_parameters(lab_t)
        state = self.ctx.device_state
        dead = {state.device.qubits[r].qubit_index for r in state.scenarios.dead} if state is not None else set()
        out = apb.ReadTruthResponse(lab_time_s=lab_t, properties=self.ctx.device_properties())
        for q, f, t1 in zip(self.ctx.qdef, f_ghz, t1_ns, strict=True):
            out.qubits.add(qubit_index=q, frequency_hz=f * 1e9, t1_s=t1 * 1e-9, dead=q in dead)
        return out

    async def InspectJob(self, request: apb.InspectJobRequest, context: ServicerContext) -> apb.InspectJobResponse:
        if not self.jobs.has_job(request.job_id):
            await context.abort(grpc.StatusCode.NOT_FOUND, f"unknown job {request.job_id}")
        info = self.jobs.info(request.job_id)
        failure = self.jobs.failure_detail(request.job_id)
        notes = [f"failed: {failure}"] if failure else []
        if info is None:
            return apb.InspectJobResponse(warnings=notes)
        return apb.InspectJobResponse(tier_used=info.tier_used, noise_fidelity=info.noise_fidelity,
                                      calibration_epoch=info.calibration_epoch, warnings=list(info.warnings) + notes)

    # ------------------------------------------------------------------ instrument faults
    async def InjectInstrumentFault(self, request: apb.InjectInstrumentFaultRequest,
                                    context: ServicerContext) -> apb.InjectInstrumentFaultResponse:
        try:
            self.faults.inject(request.fault, request.count, request.duration_s)
        except ValueError as err:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(err))
        return apb.InjectInstrumentFaultResponse()

    async def ClearInstrumentFaults(self, request: apb.ClearInstrumentFaultsRequest,
                                    context: ServicerContext) -> apb.ClearInstrumentFaultsResponse:
        self.faults.clear()
        return apb.ClearInstrumentFaultsResponse()


async def serve_admin(address: str, servicer: AdminService, *, tls: tuple[bytes, bytes] | None = None,
                      token: str | None = None) -> grpc.aio.Server:
    """Bind the admin channel. Keep it on loopback, or behind TLS and its own token (check_bind_is_safe)."""
    server = grpc.aio.server(interceptors=[BearerTokenInterceptor(token)])
    apbg.add_AdminServiceServicer_to_server(servicer, server)
    if tls is not None:
        port = server.add_secure_port(address, grpc.ssl_server_credentials([(tls[1], tls[0])]))
    else:
        port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"could not bind address {address}")
    await server.start()
    return server
