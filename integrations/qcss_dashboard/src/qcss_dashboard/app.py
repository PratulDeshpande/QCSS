"""The bridge's HTTP API. The browser talks only to this; this talks to QCSS (in process, lab link, admin channel).

Guards, applied to every /api route:
  * access token: when set (required off loopback), every call except /api/health needs X-Dashboard-Token;
  * CSRF: every mutating call needs the X-QCSS-Dashboard header, which a cross-site form or image cannot send;
  * read-only mode: every mutating call is refused.
Tokens for the lab and admin channels stay in Settings and are never serialized.
"""
from __future__ import annotations

import hmac
import pathlib
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from qcss_dashboard import __version__
from qcss_dashboard.architecture import architecture
from qcss_dashboard.configs import ConfigError, ConfigStore
from qcss_dashboard.registry import build_registry
from qcss_dashboard.settings import Settings

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "x-qcss-dashboard"
TOKEN_HEADER = "x-dashboard-token"
OPEN_PATHS = {"/api/health"}
JsonBody = Annotated[dict[str, Any], Body()]


def create_app(config: Settings | None = None) -> FastAPI:
    settings: Settings = config if config is not None else Settings()
    app = FastAPI(title="QCSS Explorer bridge", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.configs = ConfigStore(settings.workspace)

    @app.middleware("http")
    async def guards(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        if path.startswith("/api/") and path not in OPEN_PATHS and settings.access_token:
            given = request.headers.get(TOKEN_HEADER) or request.query_params.get("token") or ""
            if not hmac.compare_digest(given.encode(), settings.access_token.encode()):
                return JSONResponse({"detail": "dashboard access token required"}, status_code=401)
        if path.startswith("/api/") and request.method in MUTATING:
            if request.headers.get(CSRF_HEADER) != "1":
                return JSONResponse({"detail": f"missing {CSRF_HEADER} header (CSRF guard)"}, status_code=403)
            if settings.read_only:
                return JSONResponse({"detail": "the dashboard runs in read-only mode"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(ConfigError)
    async def _config_error(_: Request, exc: ConfigError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    # ------------------------------------------------------------------ meta
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        hub = getattr(app.state, "links", None)
        return {"ok": True, "version": __version__,
                "lab": hub.lab_status() if hub is not None else None,
                "admin": hub.admin_status() if hub is not None else None}

    @app.get("/api/settings")
    def public_settings() -> dict[str, Any]:
        return settings.public()

    @app.get("/api/registry")
    def registry() -> dict[str, Any]:
        return build_registry()

    @app.get("/api/architecture")
    def arch() -> dict[str, Any]:
        return architecture()

    # ------------------------------------------------------------------ configs
    store: ConfigStore = app.state.configs

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

    @app.put("/api/configs/{kind}/{name}")
    def save_config(kind: str, name: str, body: JsonBody) -> dict[str, Any]:
        return store.save(kind, name, str(body.get("yaml", "")))

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
