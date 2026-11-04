"""The bridge's HTTP API. The browser talks only to this; this talks to QCSS (in process, lab link, admin channel).

Guards, applied to every /api route:
  * access token: when set (required off loopback), every call except /api/health needs X-Dashboard-Token;
  * CSRF: every mutating call needs the X-QCSS-Dashboard header, which a cross-site form or image cannot send;
  * read-only mode: every mutating call is refused.
Tokens for the lab and admin channels stay in Settings and are never serialized.
"""
from __future__ import annotations

import contextlib
import hmac
import pathlib
import threading
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from google.protobuf.json_format import ParseError

import qcss
from qcss.core.errors import TierRoutingError
from qcss.runtime.calibration_store import CalibrationEpochError
from qcss_dashboard import __version__
from qcss_dashboard.admin import LinkError, Links, admin_action, admin_state, inspect_job
from qcss_dashboard.architecture import architecture
from qcss_dashboard.audit import Audit
from qcss_dashboard.chassis_host import EmbeddedChassis
from qcss_dashboard.configs import ConfigError, ConfigStore
from qcss_dashboard.events import stream
from qcss_dashboard.experiments import EXPERIMENTS, run_in_sandbox
from qcss_dashboard.hardware import hardware_view
from qcss_dashboard.lab import LabBench
from qcss_dashboard.physics_views import chip_view, readout_view, signal_view
from qcss_dashboard.registry import build_registry
from qcss_dashboard.sandbox import explain
from qcss_dashboard.settings import Settings

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "x-qcss-dashboard"
TOKEN_HEADER = "x-dashboard-token"
OPEN_PATHS = {"/api/health"}
JsonBody = Annotated[dict[str, Any], Body()]
EXAMPLES = pathlib.Path(qcss.__file__).resolve().parents[2] / "examples" / "jobs"
SANDBOX_SLOTS = threading.BoundedSemaphore(2)      # heavy simulations at most two at a time (laptop-friendly)
SANDBOX_WAIT_S = 5.0                               # then answer 503 instead of parking a worker thread
LOOPBACK_NAMES = ("127.0.0.1", "localhost", "::1")


@contextlib.contextmanager
def _sandbox_slot():
    if not SANDBOX_SLOTS.acquire(timeout=SANDBOX_WAIT_S):
        raise HTTPException(503, "the sandbox is busy with other simulations; try again shortly")
    try:
        yield
    finally:
        SANDBOX_SLOTS.release()


def _num(body: dict[str, Any], key: str, default: float, lo: float, hi: float, cast: Any = float) -> Any:
    """A bounded number from a request body; a cleared field (null) means the default."""
    v = body.get(key, default)
    if v is None:
        v = default
    try:
        v = cast(v)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number") from None
    if not lo <= v <= hi:
        raise ValueError(f"{key} must be between {lo:g} and {hi:g}")
    return v


def _same_origin(origin: str | None, host: str | None) -> bool:
    """True when there is no Origin (non-browser client) or it names this very host:port."""
    return origin is None or (host is not None and urlsplit(origin).netloc.lower() == host.lower())


def create_app(config: Settings | None = None) -> FastAPI:
    settings: Settings = config if config is not None else Settings()
    store = ConfigStore(settings.workspace)
    links = Links(settings)
    bench = LabBench(links)
    audit = Audit(settings.workspace)

    def make_embedded(profile: str, device: str | None, time_scale: float) -> EmbeddedChassis:
        emb = EmbeddedChassis(store.load_profile(profile), store.load_device(device), profile_name=profile,
                              device_name=device, time_scale=time_scale,
                              state_dir=pathlib.Path(settings.workspace) / "chip-state" / f"{profile}__{device}")
        try:
            emb.start()
        except BaseException:
            with contextlib.suppress(Exception):
                emb.stop()
            raise
        return emb

    def adopt(emb: EmbeddedChassis, profile: str, device: str | None, time_scale: float) -> None:
        settings.chassis_profile, settings.chassis_device, settings.chassis_time_scale = profile, device, time_scale
        links.attach(emb)

    def start_embedded(profile: str, device: str | None, time_scale: float) -> None:
        adopt(make_embedded(profile, device, time_scale), profile, device, time_scale)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        if settings.embedded_chassis:
            start_embedded(settings.chassis_profile, settings.chassis_device, settings.chassis_time_scale)
        try:
            yield
        finally:
            if links.embedded is not None:
                links.embedded.stop()

    app = FastAPI(title="QCSS Explorer bridge", version=__version__, docs_url="/api/docs",
                  openapi_url="/api/openapi.json", lifespan=lifespan)
    app.state.settings, app.state.configs, app.state.links = settings, store, links

    allowed_hosts = {h.lower() for h in (settings.allowed_hosts or LOOPBACK_NAMES)}

    def host_ok(hostname: str | None) -> bool:
        return (hostname or "").strip("[]").lower() in allowed_hosts

    def token_ok(given: str) -> bool:
        return not settings.access_token or hmac.compare_digest(given.encode(), settings.access_token.encode())

    @app.middleware("http")
    async def guards(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        if not host_ok(request.url.hostname):           # DNS-rebinding guard: only names this bridge answers to
            return JSONResponse({"detail": "unknown host"}, status_code=400)
        if (path.startswith("/api/") and path not in OPEN_PATHS
                and not token_ok(request.headers.get(TOKEN_HEADER) or "")):
            return JSONResponse({"detail": "dashboard access token required"}, status_code=401)
        if path.startswith("/api/") and request.method in MUTATING:
            if request.headers.get(CSRF_HEADER) != "1":
                return JSONResponse({"detail": f"missing {CSRF_HEADER} header (CSRF guard)"}, status_code=403)
            if not _same_origin(request.headers.get("origin"), request.headers.get("host")):
                return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
            if settings.read_only and not path.startswith(("/api/sandbox/", "/api/views/")):
                return JSONResponse({"detail": "the dashboard runs in read-only mode"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(ConfigError)
    async def _config_error(_: Request, exc: ConfigError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(LinkError)
    async def _link_error(_: Request, exc: LinkError) -> JSONResponse:
        return JSONResponse({"detail": str(exc), **exc.details}, status_code=exc.status)

    @app.exception_handler(ValueError)
    async def _value_error(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(ParseError)
    async def _parse_error(_: Request, exc: ParseError) -> JSONResponse:
        return JSONResponse({"detail": f"invalid message: {exc}"}, status_code=400)

    @app.exception_handler(TypeError)
    async def _type_error(_: Request, exc: TypeError) -> JSONResponse:
        return JSONResponse({"detail": f"invalid input: {exc}"}, status_code=400)

    @app.exception_handler(TierRoutingError)
    async def _tier_error(_: Request, exc: TierRoutingError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(CalibrationEpochError)
    async def _epoch_error(_: Request, exc: CalibrationEpochError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    # ------------------------------------------------------------------ meta
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        if settings.lab_target or settings.admin_target:
            links.probe()
        return {"ok": True, "version": __version__,
                "lab": links.lab_status() if settings.lab_target else None,
                "admin": links.admin_status() if settings.admin_target else None}

    @app.get("/api/settings")
    def public_settings() -> dict[str, Any]:
        return settings.public()

    @app.get("/api/registry")
    def registry() -> dict[str, Any]:
        return build_registry()

    @app.get("/api/architecture")
    def arch() -> dict[str, Any]:
        return architecture()

    @app.get("/api/experiments")
    def experiments() -> dict[str, Any]:
        return {"experiments": EXPERIMENTS}

    @app.get("/api/examples")
    def examples() -> dict[str, Any]:
        import json

        out = {}
        if EXAMPLES.exists():
            for p in sorted(EXAMPLES.glob("*.json")):
                out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        return {"jobs": out}

    # ------------------------------------------------------------------ configs
    @app.get("/api/configs")
    def list_configs() -> dict[str, Any]:
        return {"profile": store.list("profile"), "device": store.list("device")}

    @app.get("/api/configs/{kind}/{name}")
    def read_config(kind: str, name: str) -> dict[str, Any]:
        return store.read(kind, name)

    @app.post("/api/configs/{kind}/validate")
    def validate_config(kind: str, body: JsonBody) -> dict[str, Any]:
        return store.validate(kind, str(body.get("yaml", "")))

    @app.post("/api/configs/{kind}/diff")
    def diff_config(kind: str, body: JsonBody) -> dict[str, Any]:
        return store.diff(kind, str(body.get("base", "")), str(body.get("yaml", "")))

    @app.post("/api/configs/{kind}/dump")
    def dump_config(kind: str, body: JsonBody) -> dict[str, Any]:
        import yaml

        store.list(kind)                                   # validates the kind
        return {"yaml": yaml.safe_dump(body.get("data") or {}, sort_keys=False, allow_unicode=True, width=120)}

    @app.put("/api/configs/{kind}/{name}")
    def save_config(kind: str, name: str, body: JsonBody) -> dict[str, Any]:
        out = store.save(kind, name, str(body.get("yaml", "")))
        audit.record("save_config", {"kind": kind, "name": name}, True)
        return out

    # ------------------------------------------------------------------ views (computed from QCSS code)
    def _models(body: dict[str, Any]) -> tuple[Any, Any]:
        profile = store.profile_from(body.get("profile") or settings.chassis_profile, body.get("profile_yaml"))
        dev_name = body.get("device", settings.chassis_device)
        device = store.device_from(dev_name, body.get("device_yaml"))
        return profile, device

    @app.get("/api/views/hardware")
    def hw_get(profile: str | None = None, device: str | None = None) -> dict[str, Any]:
        return hardware_view(*_models({"profile": profile, "device": device or settings.chassis_device}))

    @app.post("/api/views/hardware")
    def hw_post(body: JsonBody) -> dict[str, Any]:
        return hardware_view(*_models(body))

    @app.get("/api/views/chip")
    def chip_get(device: str | None = None, hours: float = 24.0, steps: int = 96, seed: int = 1) -> dict[str, Any]:
        return chip_post({"device": device or settings.chassis_device, "hours": hours, "steps": steps,  # same bounds
                          "seed": seed})

    @app.post("/api/views/chip")
    def chip_post(body: JsonBody) -> dict[str, Any]:
        _, dev = _models(body)
        if dev is None:
            raise ConfigError("the chip view needs a device")
        return chip_view(dev, hours=_num(body, "hours", 24.0, 0.01, 720.0), steps=_num(body, "steps", 96, 2, 1000, int),
                         seed=_num(body, "seed", 1, 0, 2**31, int))

    @app.get("/api/views/readout")
    def ro_get(profile: str | None = None, device: str | None = None, qubit: int = 0, shots: int = 300,
               seed: int = 1) -> dict[str, Any]:
        return ro_post({"profile": profile, "device": device or settings.chassis_device, "qubit": qubit,   # same bounds
                        "shots": shots, "seed": seed})

    @app.post("/api/views/readout")
    def ro_post(body: JsonBody) -> dict[str, Any]:
        p, d = _models(body)
        if d is None:
            raise ConfigError("the readout view needs a device")
        return readout_view(p, d, qubit=_num(body, "qubit", 0, 0, 1023, int),
                            shots=_num(body, "shots", 300, 1, 2000, int), seed=_num(body, "seed", 1, 0, 2**31, int),
                            integration_ns=_num(body, "integration_ns", 1000.0, 10.0, 20_000.0))

    @app.post("/api/views/signal")
    def signal(body: JsonBody) -> dict[str, Any]:
        return signal_view(body)

    # ------------------------------------------------------------------ sandbox (in-process QCSS, nothing hidden)
    @app.post("/api/sandbox/explain")
    def sandbox_explain(body: JsonBody) -> dict[str, Any]:
        p, d = _models(body)
        with _sandbox_slot():
            return explain(p, d, body.get("job") or {}, tier=str(body.get("tier", "AUTO")),
                           seed=_num(body, "seed", 1, 0, 2**31, int), shots=_num(body, "shots", 200, 1, 2000, int),
                           point=_num(body, "point", 0, 0, 100_000, int))

    @app.post("/api/sandbox/experiment")
    def sandbox_experiment(body: JsonBody) -> dict[str, Any]:
        p, d = _models(body)
        params = {k: body[k] for k in ("pi_amplitude", "max_delay_us", "span_mhz", "detuning_mhz")
                  if body.get(k) is not None}
        with _sandbox_slot():
            return run_in_sandbox(str(body.get("kind", "rabi")), p, d, qubit=_num(body, "qubit", 0, 0, 1023, int),
                                  points=_num(body, "points", 21, 2, 101, int),
                                  shots=_num(body, "shots", 300, 1, 5000, int),
                                  seed=_num(body, "seed", 1, 0, 2**31, int), tier=str(body.get("tier", "AUTO")), **params)

    # ------------------------------------------------------------------ admin channel (ground truth, knobs)
    @app.get("/api/admin/state")
    def adm_state() -> dict[str, Any]:
        return admin_state(links)

    @app.post("/api/admin/action")
    def adm_action(body: JsonBody) -> dict[str, Any]:
        args = {k: v for k, v in body.items() if k != "action"}
        try:
            out = admin_action(links, body)
        except LinkError as exc:
            audit.record(str(body.get("action")), args, False, str(exc))
            raise
        audit.record(str(body.get("action")), args, True, out.get("done", ""))
        return out

    @app.get("/api/admin/inspect/{job_id}")
    def adm_inspect(job_id: str) -> dict[str, Any]:
        return inspect_job(links, job_id)

    # ------------------------------------------------------------------ lab link (what a client sees)
    @app.get("/api/lab/describe")
    def lab_describe() -> dict[str, Any]:
        return bench.describe()

    @app.get("/api/lab/calibration")
    def lab_calibration() -> dict[str, Any]:
        return bench.calibration()

    @app.put("/api/lab/calibration")
    def lab_update_calibration(body: JsonBody) -> dict[str, Any]:
        out = bench.update_calibration(body.get("snapshot") or {}, int(body.get("expected_epoch", 0)))
        audit.record("update_calibration", {"expected_epoch": body.get("expected_epoch")}, True,
                     f"epoch {out['new_epoch']}")
        return out

    @app.post("/api/lab/run")
    def lab_run(body: JsonBody) -> dict[str, Any]:
        profile = (links.embedded.chassis.config.profile if links.embedded is not None
                   else store.load_profile(settings.chassis_profile))
        return bench.run_experiment(profile, body)

    @app.get("/api/lab/jobs")
    def lab_jobs() -> dict[str, Any]:
        return {"jobs": bench.list_jobs()}

    # ------------------------------------------------------------------ chassis and audit
    @app.get("/api/chassis")
    def chassis_info() -> dict[str, Any]:
        return {"embedded": links.embedded.describe() if links.embedded is not None else None,
                "settings": settings.public()}

    @app.post("/api/chassis/restart")
    def chassis_restart(body: JsonBody) -> dict[str, Any]:
        if not settings.embedded_chassis:
            raise ConfigError("only the embedded chassis can be restarted from the dashboard", 409)
        profile = str(body.get("profile") or settings.chassis_profile)
        device = body.get("device", settings.chassis_device)
        ts = float(body.get("time_scale", settings.chassis_time_scale))
        store.load_profile(profile)                       # fail before stopping the running chassis
        store.load_device(device)
        try:
            new = make_embedded(profile, device, ts)          # the running chassis keeps serving meanwhile
        except Exception as exc:
            audit.record("restart_chassis", {"profile": profile, "device": device, "time_scale": ts}, False, str(exc))
            raise ConfigError(f"the new chassis did not start ({exc}); the running chassis is unchanged", 409) from exc
        with links.lock:
            old = links.embedded
            adopt(new, profile, device, ts)
        if old is not None:
            with contextlib.suppress(Exception):
                old.stop()
        audit.record("restart_chassis", {"profile": profile, "device": device, "time_scale": ts}, True)
        return chassis_info()

    @app.get("/api/audit")
    def audit_log() -> dict[str, Any]:
        return {"entries": audit.tail()}

    @app.websocket("/api/events")
    async def events(ws: WebSocket) -> None:
        if not host_ok(ws.url.hostname) or not _same_origin(ws.headers.get("origin"), ws.headers.get("host")):
            await ws.close(code=4403)                 # cross-site WebSocket hijacking guard (browsers skip CORS here)
            return
        if not token_ok(ws.query_params.get("token", "")):
            await ws.close(code=4401)
            return
        await stream(ws, links, bench.list_jobs, settings.poll_interval_s)

    _mount_frontend(app, settings.static_dir)
    return app


def _mount_frontend(app: FastAPI, static_dir: pathlib.Path | None) -> None:
    """Serve the built single-page app; unknown non-API paths fall back to index.html (client-side routing)."""
    if static_dir is None or not (static_dir / "index.html").exists():
        return
    index = static_dir / "index.html"
    assets = static_dir / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path.startswith("api/"):
            raise HTTPException(404)
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and static_dir.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)
