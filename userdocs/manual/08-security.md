# QCSS User Manual

## Chapter 8: Security

QCSS is a **local development and test tool**, not a hardened network service (`SECURITY.md`). This chapter explains the rules it enforces. The authoritative text is `SECURITY.md` in the repo root; vulnerabilities are reported privately through GitHub's "Report a vulnerability" under the repository's Security tab. Only the latest `0.x` release and `main` get fixes.

## 8.1 Four listeners (plus the dashboard)

`qcss serve` can open up to four listeners. Every one binds to loopback by default.

| Listener | Option | TLS | Token |
|---|---|---|---|
| Instrument link (gRPC) | `--listen` / `--host`, `--port` | optional (`--tls-cert`, `--tls-key`) | `--token` or `QCSS_TOKEN` |
| Admin channel (gRPC) | `--admin-listen` | same TLS cert | `--admin-token` or `QCSS_ADMIN_TOKEN` |
| Qibosoq board face (TCP/JSON) | `--board-listen` | none, the protocol has none | none |
| Native QICK face (Pyro4) | `--qick-ns`, `--qick-listen`, `--qick-start-ns` | none, QICK's has none | none |

The Explorer bridge is a separate process following the same rule (chapter 7).

## 8.2 Bind rules

- **Loopback** (`127.0.0.1`, `localhost`, `::1`, unix sockets) is always allowed (`core/net.py: is_local_address`).
- A **network bind of the instrument or admin link** is refused unless it has **TLS and a token**, or `--insecure` is given (`check_bind_is_safe`). Example:
  ```
  qcss serve --host 192.168.1.20 --tls-cert server.pem --tls-key server.key --token "$QCSS_TOKEN"
  ```
- A **network bind of the Qibosoq or QICK face** is **always** refused without `--insecure` ("the qibosoq protocol has no TLS and no token"; "Pyro4 has no TLS and no token (QICK's own boards neither)"). This also applies to `--qick-start-ns`'s nameserver address. Use a trusted network only.
- A hostname other than `localhost` is treated as possibly remote.
- `--insecure` is an explicit override; it removes protection, it does not add any.
- `scripts/make_dev_cert.py <ip>` makes a self-signed certificate for tests. Copy `server.pem` to the client machine and pass it as `--ca`.

## 8.3 Tokens

- One **bearer token per channel**: clients send `authorization: Bearer <token>`. Every call except the gRPC health check needs it when a token is set. There are no per-user accounts and no mutual TLS; anyone holding the lab token can submit jobs and overwrite calibration.
- The **admin token must differ** from the lab token (`--admin-token must differ from --token`) and is **required whenever the lab link has a token**. It can read the chip's true state and inject faults, so treat it as the more sensitive one. The lab listener never serves admin RPCs.
- **Client token guard:** `QcssClient`, `qcss remote` and `qcss admin` refuse to send a token without TLS to a non-loopback address unless `insecure=True` / `--insecure` is given (verified in `cli.py`: "refusing to send the admin token in cleartext to ...; pass --ca or --insecure").
- Prefer environment variables to `--token` so tokens do not appear in shell history or process lists.
- The dashboard holds the lab and admin tokens itself and never sends them to the browser; it takes them only from environment variables, and its own login token from `QCSS_DASHBOARD_TOKEN`.

## 8.4 Untrusted input

- The board face parses JSON; the chip state file (`--state-dir`) and the technician's request spool are plain JSON. A pickle in place of the state file is refused, not executed.
- **The QICK face must speak pickle**, because QICK clients send nothing else (QICK sets Pyro4 `SERIALIZER = "pickle"`, protocol 4). A real board unpickles anything it is sent, which allows code execution. QCSS's decoder (`src/qcss/boards/qick/serializer.py`) resolves only an **allowlist** of globals: plain builtins (bool, bytes, complex, dict, float, int, list, range, set, slice, str, tuple...), numpy array reconstruction helpers, `OrderedDict`, Pyro `URI`, and exception classes of `builtins`/`Pyro4.errors`. Any other global (`os.system`, `builtins.eval`) is refused before it can run. `install()` swaps it into Pyro4's process-wide table, so it covers both the daemon and this process's nameserver calls.
- Otherwise pickle is used only for parent-to-child communication inside the server's own worker pool.
- The technician runs Qibocal as a **subprocess** with the platform folder and environment you give it (`--env`); protect the request spool like lab-side configuration.

## 8.5 Resource limits

gRPC messages are capped at 16 MiB and hardware-rule checks reject oversized programs, but a client can submit many large jobs (they queue). Per job 256 MiB of results kept; 256 finished jobs kept. The board face refuses requests over 16 MiB without reading them, drops a client slower than 30 s, refuses sweeps beyond 2^18 points x sequence elements, and does **not** cap `reps`: a long unaveraged run's reply is held in memory.

## 8.6 Indistinguishability as a security property

The lab link must never reveal that it is a simulator: no tier in `JobStatus`, no reflection unless `--debug-reflection`, no true parameters, failures read as "instrument fault", results from fresh entropy. Debug options (`--debug-reflection`, `--deterministic`) weaken this on purpose; use them for tests only.

## 8.7 Checklist for a LAN test

1. Make a cert: `python scripts/make_dev_cert.py <server-ip>`.
2. Start with `--host <ip> --tls-cert ... --tls-key ... --token ...` and, if you want admin, `--admin-listen <ip>:50052 --admin-token <different>`.
3. On the client: `qcss remote ping --target <ip>:50051 --ca server.pem --token ...`.
4. Run `python scripts/remote_smoke.py --target <ip>:50051 --ca server.pem --token "$QCSS_TOKEN"` (README: checks health, description, jobs, refusals, calibration compare-and-swap, streaming, cancellation and token rejection).
5. Only add `--insecure` for the QICK and Qibosoq faces on a network you trust.

Unverified in this session: two-machine TLS (not run), the remote smoke script, and the cert script.

---
Sources: `SECURITY.md`, `README.md` (Security note), `src/qcss/cli.py` (serve guards lines ~336-432, client guards), `src/qcss/core/net.py`, `src/qcss/boards/qick/serializer.py`, `src/qcss/boards/qick/pyro_host.py`, `integrations/qcss_dashboard/README.md`. Read: `qcss serve --help`, `qcss admin --help`.
