"""qcss-dashboard: start the QCSS Explorer bridge (and, by default, an embedded virtual lab).

    qcss-dashboard                           # http://127.0.0.1:8765, embedded chassis on loopback
    qcss-dashboard --no-embedded --lab 192.168.0.20:50051 --admin 192.168.0.20:50052 --ca certs/server.pem

Lab and admin tokens come from QCSS_TOKEN and QCSS_ADMIN_TOKEN (never from the command line, which other users can
read). A non-loopback bind needs TLS (--tls-cert/--tls-key) and a login token (QCSS_DASHBOARD_TOKEN), as the chassis
itself requires, unless --insecure is given on a network you trust.
"""
from __future__ import annotations

import os
import pathlib

import click

from qcss.core.net import is_local_address
from qcss_dashboard.settings import Settings

DEFAULT_STATIC = pathlib.Path(__file__).resolve().parents[2] / "web" / "dist"


class UnsafeBind(click.ClickException):
    pass


def check_bind(host: str, *, tls: bool, token: bool, insecure: bool) -> None:
    if insecure or is_local_address(f"{host}:0"):
        return
    if not (tls and token):
        raise UnsafeBind(f"refusing to serve the dashboard on {host} without TLS (--tls-cert/--tls-key) and a login "
                         "token (QCSS_DASHBOARD_TOKEN); it exposes the chip's hidden truth and admin controls. "
                         "Pass --insecure only on a network you trust.")


def settings_from(*, workspace: str | None, lab: str | None, admin: str | None, ca: str | None,
                  access_token: str | None, read_only: bool, embedded: bool, profile: str, device: str | None,
                  time_scale: float, static: str | None) -> Settings:
    s = Settings()
    if workspace:
        s.workspace = pathlib.Path(workspace)
    s.lab_target, s.admin_target = lab, admin
    s.lab_token = os.environ.get("QCSS_TOKEN") or None
    s.admin_token = os.environ.get("QCSS_ADMIN_TOKEN") or None
    s.ca_file = pathlib.Path(ca) if ca else None
    s.access_token = access_token or os.environ.get("QCSS_DASHBOARD_TOKEN") or None
    s.read_only, s.embedded_chassis = read_only, embedded
    s.chassis_profile, s.chassis_device, s.chassis_time_scale = profile, device, time_scale
    st = pathlib.Path(static) if static else DEFAULT_STATIC
    s.static_dir = st if (st / "index.html").exists() else None
    return s


@click.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Address the dashboard listens on")
@click.option("--port", default=8765, show_default=True, type=int)
@click.option("--workspace", default=None, help="Dashboard home (user configs, audit log, chip state)")
@click.option("--embedded/--no-embedded", default=True, show_default=True,
              help="Run a QCSS chassis inside the bridge, or connect to an existing one")
@click.option("--profile", default="qblox_cluster_5q", show_default=True, help="Embedded chassis hardware profile")
@click.option("--device", default="transmon_5q", show_default=True, help="Embedded chassis device")
@click.option("--time-scale", default=1.0, show_default=True, type=float, help="Embedded lab seconds per wall second")
@click.option("--lab", default="127.0.0.1:50051", show_default=True, help="Lab link of an external chassis")
@click.option("--admin", "admin_", default="127.0.0.1:50052", show_default=True,
              help="Admin channel of an external chassis")
@click.option("--ca", default=None, help="CA/server certificate (PEM) for TLS to an external chassis")
@click.option("--read-only", is_flag=True, help="Refuse every change (configs, admin actions, calibration, jobs)")
@click.option("--static", default=None, help="Built frontend directory (default: integrations/qcss_dashboard/web/dist)")
@click.option("--tls-cert", default=None, help="TLS certificate for the dashboard itself")
@click.option("--tls-key", default=None, help="TLS key for the dashboard itself")
@click.option("--insecure", is_flag=True, help="Allow a non-loopback bind without TLS and a login token")
def main(host: str, port: int, workspace: str | None, embedded: bool, profile: str, device: str, time_scale: float,
         lab: str, admin_: str, ca: str | None, read_only: bool, static: str | None, tls_cert: str | None,
         tls_key: str | None, insecure: bool) -> None:
    """Start the QCSS Explorer dashboard."""
    s = settings_from(workspace=workspace, lab=lab, admin=admin_, ca=ca, access_token=None, read_only=read_only,
                      embedded=embedded, profile=profile, device=device or None, time_scale=time_scale,
                      static=static)
    check_bind(host, tls=bool(tls_cert and tls_key), token=bool(s.access_token), insecure=insecure)
    import uvicorn

    from qcss_dashboard.app import create_app

    scheme = "https" if tls_cert else "http"
    click.echo(f"QCSS Explorer on {scheme}://{host}:{port}  (workspace {s.workspace})")
    if s.static_dir is None:
        click.echo("  frontend not built: run `npm run build` in integrations/qcss_dashboard/web (API only for now)")
    uvicorn.run(create_app(s), host=host, port=port, ssl_certfile=tls_cert, ssl_keyfile=tls_key, log_level="info")


if __name__ == "__main__":
    main()
