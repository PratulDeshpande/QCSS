"""Faults of the instrument itself (hang, dropped connection, reboot, slow upload).

Injected through the admin channel and applied to the lab link by an interceptor, so the
lab's client sees exactly what a misbehaving instrument does: calls that stall, fail as
UNAVAILABLE, or a box that is gone for a while and lost the job it was running.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import grpc

from qcss.admin.v1 import admin_pb2 as apb

_EXEMPT = ("/grpc.health.v1.Health/",)   # liveness probes do not consume injected faults
_RESET = "Connection reset by peer"


class InstrumentFaults:
    def __init__(self, on_reboot: Callable[[str], None] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._on_reboot = on_reboot
        self._clock = clock
        self.clear()

    def clear(self) -> None:
        self._hang: list[float] = []          # one entry per call to stall: its duration
        self._slow: list[float] = []
        self._drop = 0
        self._down_until = 0.0

    def inject(self, fault: int, count: int = 0, duration_s: float = 0.0) -> None:
        if duration_s < 0:
            raise ValueError("duration_s must be >= 0")
        n = max(count, 1)
        if fault == apb.INSTRUMENT_FAULT_HANG:
            self._hang += [duration_s] * n
        elif fault == apb.INSTRUMENT_FAULT_DROP:
            self._drop += n
        elif fault == apb.INSTRUMENT_FAULT_SLOW_UPLOAD:
            self._slow += [duration_s] * n
        elif fault == apb.INSTRUMENT_FAULT_REBOOT:
            self._down_until = self._clock() + duration_s
            if self._on_reboot is not None:
                self._on_reboot("instrument rebooted")
        else:
            raise ValueError(f"unknown instrument fault {fault}")

    async def admit(self, *, uploads: bool = False) -> bool:
        """A lab call starts: False if the instrument drops it; otherwise it may stall first.
        uploads: the call uploads a program (slow uploads apply)."""
        if self._clock() < self._down_until:
            return False
        if self._drop:
            self._drop -= 1
            return False
        if self._hang:
            await asyncio.sleep(self._hang.pop(0))
        if uploads and self._slow:
            await asyncio.sleep(self._slow.pop(0))
        return True

    async def before_call(self, method: str, context: grpc.aio.ServicerContext) -> None:
        """Applied when a gRPC lab call starts: a dropped call ends as UNAVAILABLE."""
        if not await self.admit(uploads=method.endswith("/SubmitJob")):
            await context.abort(grpc.StatusCode.UNAVAILABLE, _RESET)


class InstrumentFaultInterceptor(grpc.aio.ServerInterceptor):
    def __init__(self, faults: InstrumentFaults) -> None:
        self._faults = faults

    async def intercept_service(
        self, continuation: Callable[[grpc.HandlerCallDetails], Awaitable[grpc.RpcMethodHandler | None]],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler | None:
        handler = await continuation(handler_call_details)
        method = handler_call_details.method or ""
        if handler is None or method.startswith(_EXEMPT):
            return handler
        return _gated(handler, self._faults, method)


def _gated(handler: grpc.RpcMethodHandler, faults: InstrumentFaults, method: str) -> grpc.RpcMethodHandler:
    """The same handler, with the faults applied when the call starts (not when it is looked up)."""
    kw = {"request_deserializer": handler.request_deserializer, "response_serializer": handler.response_serializer}
    if handler.unary_unary:
        inner_uu: Any = handler.unary_unary

        async def unary(request: Any, context: grpc.aio.ServicerContext) -> Any:
            await faults.before_call(method, context)
            return await inner_uu(request, context)
        return grpc.unary_unary_rpc_method_handler(unary, **kw)
    if handler.unary_stream:
        inner_us: Any = handler.unary_stream

        async def stream(request: Any, context: grpc.aio.ServicerContext) -> AsyncIterator[Any]:
            await faults.before_call(method, context)
            async for item in inner_us(request, context):
                yield item
        return grpc.unary_stream_rpc_method_handler(stream, **kw)
    return handler
