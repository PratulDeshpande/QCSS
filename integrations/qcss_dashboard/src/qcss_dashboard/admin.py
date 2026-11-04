"""Links to the chassis (lab link and admin channel) and the admin-channel operations.

The admin channel is the only place hidden truth comes from. Its token never leaves this process: requests are made
here, and only decoded results go to the browser. A token is never sent in cleartext off loopback (same rule as
`qcss admin` and QcssClient).
"""
from __future__ import annotations

import threading
from typing import Any

import grpc
from google.protobuf import json_format

from qcss.admin.v1 import admin_pb2 as apb
from qcss.admin.v1 import admin_pb2_grpc as apbg
from qcss.client import QcssClient, QcssRpcError
from qcss.core.net import is_local_address
from qcss.v1 import job_pb2
from qcss_dashboard.chassis_host import EmbeddedChassis
from qcss_dashboard.settings import Settings

TIER_POLICY = {"requested": job_pb2.FIDELITY_TIER_UNSPECIFIED, "auto": job_pb2.FIDELITY_TIER_AUTO,
               "t0": job_pb2.FIDELITY_TIER_T0_SURROGATE, "t1a": job_pb2.FIDELITY_TIER_T1A_STABILIZER,
               "t1b": job_pb2.FIDELITY_TIER_T1B_STATEVECTOR, "t2": job_pb2.FIDELITY_TIER_T2_LINDBLAD}
FAULTS = {"hang": apb.INSTRUMENT_FAULT_HANG, "drop": apb.INSTRUMENT_FAULT_DROP,
          "reboot": apb.INSTRUMENT_FAULT_REBOOT, "slow_upload": apb.INSTRUMENT_FAULT_SLOW_UPLOAD}
_HTTP = {grpc.StatusCode.INVALID_ARGUMENT: 400, grpc.StatusCode.NOT_FOUND: 404,
         grpc.StatusCode.FAILED_PRECONDITION: 409, grpc.StatusCode.ABORTED: 409,
         grpc.StatusCode.UNAUTHENTICATED: 502, grpc.StatusCode.PERMISSION_DENIED: 502,
         grpc.StatusCode.UNAVAILABLE: 503, grpc.StatusCode.DEADLINE_EXCEEDED: 504,
         grpc.StatusCode.OUT_OF_RANGE: 410}


class LinkError(Exception):
    def __init__(self, message: str, status: int = 502, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.details = details or {}

    @classmethod
    def from_rpc(cls, err: QcssRpcError) -> LinkError:
        return cls(f"{err.code.name}: {err.message}", _HTTP.get(err.code, 502),
                   {"code": err.code.name, "field_violations": [{"path": p, "description": d}
                                                                for p, d in err.field_violations],
                    "precondition_failures": [{"type": t, "subject": s, "description": d}
                                              for t, s, d in err.precondition_failures]})




def _numbers(d: Any, desc: Any) -> Any:
    """protobuf's JSON mapping writes 64-bit integers as strings; the browser gets numbers (ticks, epochs < 2^53)."""
    if not isinstance(d, dict):
        return d
    for f in desc.fields:
        if f.name not in d:
            continue
        v = d[f.name]
        if f.message_type is not None and not f.message_type.GetOptions().map_entry:
            d[f.name] = [_numbers(x, f.message_type) for x in v] if isinstance(v, list) else _numbers(v, f.message_type)
        elif f.type in (3, 4, 6, 16, 18):          # int64, uint64, fixed64, sfixed64, sint64
            d[f.name] = [int(x) for x in v] if isinstance(v, list) else int(v)
    return d


def to_dict(msg: Any) -> dict[str, Any]:
    return _numbers(json_format.MessageToDict(msg, preserving_proto_field_name=True,
                                              always_print_fields_with_no_presence=True), msg.DESCRIPTOR)


class Links:
    """Where the chassis is and how to reach it; the embedded chassis, when there is one."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.embedded: EmbeddedChassis | None = None
        self.lock = threading.RLock()
        self._status: dict[str, dict[str, Any]] = {"lab": {"ok": False, "error": "not probed"},
                                                   "admin": {"ok": False, "error": "not probed"}}

    def attach(self, emb: EmbeddedChassis | None) -> None:
        with self.lock:
            self.embedded = emb
            if emb is not None:
                s = self.settings
                s.lab_target, s.admin_target = emb.lab_address, emb.admin_address
                s.lab_token, s.admin_token = emb.lab_token, emb.admin_token

    def _ca(self) -> bytes | None:
        return self.settings.ca_file.read_bytes() if self.settings.ca_file is not None else None

    # ------------------------------------------------------------------ lab link
    def lab(self, timeout_s: float = 30.0) -> QcssClient:
        s = self.settings
        if not s.lab_target:
            raise LinkError("no lab link configured", 503)
        try:
            return QcssClient(s.lab_target, tls_ca=self._ca(), token=s.lab_token, timeout_s=timeout_s)
        except ValueError as exc:
            raise LinkError(str(exc), 400) from exc

    # ------------------------------------------------------------------ admin channel
    def admin(self, method: str, request: Any, timeout_s: float = 10.0) -> Any:
        s = self.settings
        if not s.admin_target:
            raise LinkError("no admin channel configured", 503)
        if s.admin_token and s.ca_file is None and not is_local_address(s.admin_target):
            raise LinkError(f"refusing to send the admin token in cleartext to {s.admin_target}", 400)
        ca = self._ca()
        channel = (grpc.secure_channel(s.admin_target, grpc.ssl_channel_credentials(ca)) if ca
                   else grpc.insecure_channel(s.admin_target))
        md = (("authorization", f"Bearer {s.admin_token}"),) if s.admin_token else ()
        try:
            with channel:
                return getattr(apbg.AdminServiceStub(channel), method)(request, metadata=md, timeout=timeout_s)
        except grpc.RpcError as err:
            raise LinkError.from_rpc(QcssRpcError.from_call(err)) from err

    # ------------------------------------------------------------------ status
    def probe(self) -> None:
        lab: dict[str, Any] = {"target": self.settings.lab_target}
        try:
            with self.lab(timeout_s=3.0) as c:
                lab["ok"] = c.health()
                lab["error"] = None if lab["ok"] else "health check failed"
        except (LinkError, QcssRpcError, grpc.RpcError) as exc:
            lab.update(ok=False, error=str(exc))
        adm: dict[str, Any] = {"target": self.settings.admin_target}
        try:
            self.admin("GetMode", apb.GetModeRequest(), timeout_s=3.0)
            adm.update(ok=True, error=None)
        except LinkError as exc:
            adm.update(ok=False, error=str(exc))
        self._status = {"lab": lab, "admin": adm}

    def lab_status(self) -> dict[str, Any]:
        return self._status["lab"]

    def admin_status(self) -> dict[str, Any]:
        return self._status["admin"]


def admin_state(links: Links) -> dict[str, Any]:
    mode = links.admin("GetMode", apb.GetModeRequest())
    truth = links.admin("ReadTruth", apb.ReadTruthRequest())
    return {"mode": to_dict(mode.mode), "global_seed": str(mode.global_seed), "truth": to_dict(truth)}


def inspect_job(links: Links, job_id: str) -> dict[str, Any]:
    return to_dict(links.admin("InspectJob", apb.InspectJobRequest(job_id=job_id)))


def admin_action(links: Links, body: dict[str, Any]) -> dict[str, Any]:
    """One admin action from the console. Returns a short description of what changed."""
    act = str(body.get("action", ""))
    q = int(body.get("qubit", 0))
    if act == "kill":
        links.admin("KillQubit", apb.KillQubitRequest(qubit_index=q))
        return {"done": f"qubit {q} killed (T1 <= 100 ns, moved -200 MHz)"}
    if act == "revive":
        links.admin("ReviveQubit", apb.ReviveQubitRequest(qubit_index=q))
        return {"done": f"qubit {q} revived"}
    if act == "drift":
        df, f = float(body.get("df_hz", 0.0)), float(body.get("t1_factor", 1.0))
        if f <= 0:
            raise LinkError("t1_factor must be > 0", 400)
        links.admin("DriftStep", apb.DriftStepRequest(qubit_index=q, delta_frequency_hz=df, t1_factor=f))
        return {"done": f"qubit {q}: frequency {df:+g} Hz, T1 x{f:g}"}
    if act == "tls":
        links.admin("TlsCollision", apb.TlsCollisionRequest(
            qubit_index=q, coupling_hz=float(body.get("coupling_hz", 0.0)),
            linewidth_hz=float(body.get("linewidth_hz", 0.0)), detuning_hz=float(body.get("detuning_hz", 0.0))))
        return {"done": f"qubit {q}: TLS defect moved into resonance"}
    if act == "burst":
        links.admin("Burst", apb.BurstRequest(qubit_index=q, peak_gamma_per_s=float(body.get("peak_gamma_per_s", 0))))
        return {"done": f"cosmic-ray burst at qubit {q}"}
    if act == "freeze":
        frozen = bool(body.get("frozen", True))
        links.admin("FreezeDrift", apb.FreezeDriftRequest(frozen=frozen))
        return {"done": "drift frozen" if frozen else "drift resumed"}
    if act == "clear":
        links.admin("ClearScenarios", apb.ClearScenariosRequest())
        return {"done": "scenarios cleared"}
    if act == "mode":
        mode = links.admin("GetMode", apb.GetModeRequest()).mode
        if body.get("time_scale") is not None:
            ts = float(body["time_scale"])
            if ts < 0:
                raise LinkError("time_scale must be >= 0", 400)
            mode.time_scale = ts
        if body.get("deterministic") is not None:
            mode.deterministic = bool(body["deterministic"])
        if body.get("tier") is not None:
            tier = str(body["tier"]).lower()
            if tier not in TIER_POLICY:
                raise LinkError(f"unknown tier '{tier}'", 400)
            mode.tier_policy = TIER_POLICY[tier]
        new = links.admin("SetMode", apb.SetModeRequest(mode=mode)).mode
        return {"done": "mode updated", "mode": to_dict(new)}
    if act == "fault":
        kind = str(body.get("fault", "")).lower()
        if kind not in FAULTS:
            raise LinkError(f"unknown fault '{kind}' (hang, drop, reboot, slow_upload)", 400)
        links.admin("InjectInstrumentFault", apb.InjectInstrumentFaultRequest(
            fault=FAULTS[kind], count=int(body.get("count", 1)), duration_s=float(body.get("duration_s", 0.0))))
        return {"done": f"instrument fault {kind} injected"}
    if act == "clear_faults":
        links.admin("ClearInstrumentFaults", apb.ClearInstrumentFaultsRequest())
        return {"done": "instrument faults cleared"}
    raise LinkError(f"unknown admin action '{act}'", 400)
