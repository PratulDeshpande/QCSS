# Environment variables and ports

Reference. Every default below was read from code (file given); nothing here was measured on a running server.

## Environment variables

| Variable | Read by | Meaning | Default when unset |
|---|---|---|---|
| `QCSS_TOKEN` | `qcss serve --token`, `qcss remote *` (`--token`), `qcss-dashboard` (lab link token), `QcssController` (Qibolab driver; variable name is the `token_env` field) | Bearer token of the instrument (lab) link. Sent as `authorization: Bearer <token>`. | No token. A non-loopback bind is then refused unless `--insecure`. |
| `QCSS_ADMIN_TOKEN` | `qcss serve --admin-token`, `qcss admin *` (`--token`), `qcss-dashboard` (admin link token) | Token of the admin channel. Must differ from the lab token; required when the lab link has a token and `--admin-listen` is set. | No token. |
| `QCSS_DASHBOARD_TOKEN` | `qcss-dashboard` | Login token for the Explorer itself. Required, with TLS, for a non-loopback `--host` unless `--insecure`. | No login token. |
| `QCSS_DASHBOARD_HOME` | `qcss-dashboard` (`Settings.workspace`) | Dashboard workspace: user configs, audit log, chip state. `--workspace` overrides it. | `~/.qcss-dashboard` |
| `QIBOLAB_PLATFORMS` | Qibolab (platform lookup), Qibocal; the technician sets it for its Qibocal subprocess to `--platforms-dir` | Folder holding the platform folders (`platforms/`). | Qibolab's own default (Unverified). |
| `QCSS_QBLOX_5Q_ADDRESS` | `platforms/qcss_qblox_5q/platform.py` | `host:port` of the chassis instrument link. | `192.168.0.20:50051` |
| `QCSS_RFSOC_5Q_ADDRESS` | `platforms/qcss_rfsoc_5q/platform.py` | `host:port` of the Qibosoq board face. | `192.168.0.81:6000` |
| `MPLCONFIGDIR` | set by `qcss.runtime.runner` via `setdefault` | Matplotlib config dir (qutip imports matplotlib; avoids a Windows problem). | system temp dir |
| `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS` | set to `1` inside `--workers` process-pool workers | One BLAS thread per worker. | n/a |

Notes:
- Tokens are never passed to the dashboard as CLI flags (they are visible to other users in the process list). `qcss-dashboard` never serializes them to the browser.
- `qcss technician run --env NAME=VALUE` adds variables to Qibocal's environment (for example `QCSS_QBLOX_5Q_ADDRESS`).
- The Qibolab driver reads the token from the variable named by `QcssController.token_env` (default `"QCSS_TOKEN"`); `None` disables it.

## Default ports and addresses

| Port | What | Set by | Default bind | Notes |
|---|---|---|---|---|
| 50051 | Instrument link (gRPC `qcss.v1.ControlService`) | `qcss serve --port/--host/--listen`; `qcss remote --target` | `127.0.0.1:50051` | Also `qcss-dashboard --lab` default and the qblox platform default host port. TLS + token needed off loopback. |
| 50052 | Admin channel (gRPC `qcss.admin.v1.AdminService`) | `qcss serve --admin-listen` (no default: off unless given); `qcss admin --target`; `qcss-dashboard --admin` | client default `127.0.0.1:50052`; server: not served unless `--admin-listen` | Own token. |
| 6000 | Qibosoq-compatible board face (TCP, 4-byte length + JSON) | `qcss serve --board-listen` (no default; the CLI help example is `127.0.0.1:6000`) | not served unless given | No TLS, no token. Non-loopback needs `--insecure`. rfsoc platform default `192.168.0.81:6000`. |
| 8888 | Pyro4 nameserver for the native QICK face | `qcss serve --qick-ns host:port` (no default; help example `127.0.0.1:8888`); `--qick-start-ns` runs the nameserver in-process | not served unless given | No TLS, no token. 8888 is the port used in the docs/examples, not a code default. |
| (free) | QICK board's Pyro4 daemon | `--qick-listen host[:port]` | `127.0.0.1`, port 0 = a free port | Clients connect here after the nameserver lookup. |
| 8765 | QCSS Explorer bridge (FastAPI/uvicorn) | `qcss-dashboard --host/--port` | `127.0.0.1:8765` | Non-loopback needs TLS + `QCSS_DASHBOARD_TOKEN`. |
| 5173 | Explorer frontend dev server (Vite) | `integrations/qcss_dashboard/web/vite.config.ts` | Vite default host | Proxies `/api` (with websockets) to `http://127.0.0.1:8765`. Development only; the built frontend is served by the bridge at 8765. |

Unix sockets: `qcss serve --listen unix:/path` (or `unix:C:/Users/me/qcss.sock` on Windows 10+) is treated as local by the bind check.

Not ports of QCSS: tests bind to port 0 or a free-port helper rather than fixed ports (CONTRIBUTING.md).

Sources: src/qcss/cli.py (serve, admin, remote options), integrations/qcss_dashboard/src/qcss_dashboard/{cli,settings}.py, integrations/qcss_dashboard/web/vite.config.ts, platforms/qcss_qblox_5q/platform.py, platforms/qcss_rfsoc_5q/platform.py, integrations/qcss_qibolab/src/qcss_qibolab/controller.py, src/qcss/technician/__init__.py, src/qcss/runtime/runner.py, src/qcss/core/net.py.
