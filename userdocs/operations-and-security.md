# Operations and security

QCSS is alpha and a local development/test tool, not a hardened network service (SECURITY.md). Facts below are from SECURITY.md and the bind/token code (`src/qcss/adapters/grpc_server.py`, `src/qcss/cli.py`, `integrations/qcss_dashboard/.../cli.py`, `src/qcss/core/net.py`). Nothing here was tested on a real network.

## Listeners

| Listener | Flag | TLS | Token | Off-loopback rule |
|---|---|---|---|---|
| Instrument link (gRPC) | `--host/--port` or `--listen` (default `127.0.0.1:50051`) | `--tls-cert` + `--tls-key` | `--token` / `QCSS_TOKEN` | refused unless TLS and token, or `--insecure` |
| Admin channel (gRPC) | `--admin-listen` (off by default) | same cert as the lab link | `--admin-token` / `QCSS_ADMIN_TOKEN`; must differ from the lab token; required when the lab link has a token | same check, with the admin token |
| Qibosoq board face | `--board-listen` (TCP only) | none (protocol has none) | none | refused unless `--insecure` |
| Native QICK face | `--qick-ns`, `--qick-listen`, `--qick-start-ns` | none | none | refused unless `--insecure` |
| Explorer bridge | `qcss-dashboard --host/--port` (default `127.0.0.1:8765`) | `--tls-cert/--tls-key` | `QCSS_DASHBOARD_TOKEN` | refused without TLS and login token unless `--insecure` |

"Local" means loopback IPs, `localhost`, and `unix:` sockets; any other hostname counts as non-local (`is_local_address`). Health checks (`grpc.health.v1`) need no token.

Other `qcss serve` checks: both or neither of `--tls-cert/--tls-key`; `--admin-token` must differ from `--token`; `--admin-listen` must differ from the instrument address; `--board-listen` must be TCP `host:port`.

## Deployment topologies

1. Single machine, everything on loopback (default). No TLS/token needed. `qcss-dashboard` embeds a chassis on loopback (embedded default on).
2. Two machines (server and client, as docs/remote-testing.md): server binds a LAN IP with TLS + token; client gets the server certificate (`--ca server.pem`) and token (`QCSS_TOKEN`). Dev certificate: `python scripts/make_dev_cert.py <ip> [names]` writes `server.pem` and `server.key` (365 days default; refuses to overwrite an existing key without `--force`; owner-only key mode on Linux/macOS). Needs `cryptography`.
3. Lab-style: chassis with `--state-dir`, `--admin-listen` on a separate port and token, technician running next to a Qibolab platform folder, operator/CI using `qcss admin`.
4. Explorer against an external chassis: `qcss-dashboard --no-embedded --lab HOST:50051 --admin HOST:50052 --ca server.pem`, with `QCSS_TOKEN` / `QCSS_ADMIN_TOKEN` in the environment. Off-loopback dashboard also needs `--allowed-host` names browsers use (Host-header allow list).
5. Board faces (Qibosoq, QICK) on a network only on a trusted network with `--insecure`; there is no way to add TLS or a token to them.

## Secrets handling
- Tokens come from flags or environment (`QCSS_TOKEN`, `QCSS_ADMIN_TOKEN`); the dashboard reads them only from the environment, never a flag (visible to other users in process lists), and never sends them to the browser (`Settings.public()` reports only `has_lab_token` booleans).
- Comparison is constant-time (`hmac.compare_digest`).
- Clients (`QcssClient`, `qcss remote`, `qcss admin`) refuse to send a token without TLS to a non-loopback address unless `insecure=True` / `--insecure`.
- One token per channel; no per-user accounts, no mutual TLS. Anyone holding the lab token can submit jobs and overwrite calibration. The admin token is the more sensitive one (reveals true chip state, injects faults).
- Server private key: keep on the server; `/certs/` contents in this repo (`server.key`, `.bak` copies) are dev material; `/certs/` is gitignored (.gitignore line 66).
- Report vulnerabilities privately through the repository's GitHub Security tab (SECURITY.md); acknowledgement within a week.

## Threat-model summary
In scope per SECURITY.md: ways around these protections, remote code execution, memory-safety problems in QCSS code.

| Surface | Handling |
|---|---|
| Untrusted input | protobuf, JSON, and allowlisted pickle only. Board face parses JSON. State file (`--state-dir`) and technician spool are plain JSON; a pickle in place of the state file is refused. |
| Native QICK face | Must speak pickle (QICK clients send nothing else). Decoder resolves only an allowlist (plain data, numpy, `OrderedDict`, Pyro URIs, exceptions); other globals refused before execution. |
| `pickle` elsewhere | Only parent-to-child inside the server's own `--workers` pool. |
| Resource limits | gRPC messages 16 MiB; hardware-rule checks reject oversized programs; one job at a time, others queue; 256 MiB per job and 256 most recent finished jobs retained (older: `OUT_OF_RANGE` / `NOT_FOUND`). Board face: refuses requests over 16 MiB unread, drops clients taking over 30 s to send, refuses sweeps beyond 2^18 points x elements; `reps` is not capped (memory risk). |
| Explorer | Refuses unknown `Host` names (DNS rebinding), cross-origin mutations and WebSocket upgrades; bounds request sizes; 503 when sandbox busy; `--read-only` refuses every change. |
| Technician | Runs Qibocal as a subprocess with the platform folder and the environment you give (`--env`); protect the spool folder like lab config. |
| Indistinguishability | Lab link must not reveal tier, noise fidelity, true parameters, simulator class names or seeds; simulator knobs live only on the admin channel (CONTRIBUTING.md). |
| Not covered | per-user access control, mutual TLS, rate limiting per client, a hardened public service. |

## Operating notes
- State: `--state-dir DIR` saves drift, defects, scenarios, lab clock and random state as JSON (every 60 s and at shutdown per README); restart restores it and counts downtime as lab time.
- Pacing: `--time-scale 1` (default) real time; `0` freezes the chip and runs unpaced (tests).
- Reproducibility: add `--deterministic` and a `--seed` only for CI; real-lab behaviour uses entropy.
- Faults to rehearse: `qcss admin fault hang|drop|reboot|slow-upload`, `qcss admin kill N`.
- Laptop limit (project memory): tests at most `-n 2`.

Sources: SECURITY.md, README.md, src/qcss/cli.py (serve), src/qcss/adapters/grpc_server.py, src/qcss/core/net.py, integrations/qcss_dashboard/src/qcss_dashboard/{cli,settings}.py, scripts/make_dev_cert.py, CONTRIBUTING.md, docs/remote-testing.md.
