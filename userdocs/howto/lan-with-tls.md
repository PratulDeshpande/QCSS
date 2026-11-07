# How to: serve QCSS to another machine with TLS and a token

**Goal:** a server on one machine, clients on another, encrypted and authenticated. **Verified:** certificate creation, bind refusals, TLS + token on loopback (2026-11-05). *Unverified:* an actual second machine and firewall rules.

## The rule
A non-loopback bind of the lab link (and of the admin channel) is refused unless it has BOTH TLS and a token, or you pass `--insecure`. Loopback (`127.0.0.1`, `::1`, `localhost`) is exempt. The Qibosoq board and the QICK Pyro4 face have no TLS or token at all, so a network bind of those needs `--insecure`.

## 1. Make a certificate (server machine)
`scripts/make_dev_cert.py` needs the `cryptography` package (already present in this environment; otherwise `python -m pip install cryptography`).
```
uv run python scripts/make_dev_cert.py 192.168.1.20 --out certs
```
Give every IP address and host name clients will use. Output:
```
wrote ...\server.pem (copy to clients) and ...\server.key (keep private)
valid for: localhost, 127.0.0.1, 192.168.1.20
```
Options: `--out DIR` (the directory must exist), `--days N` (default 365), `--force` to overwrite an existing `server.key` (clients then need the new `server.pem`). It refuses to overwrite otherwise.

## 2. Start the server
```
export QCSS_TOKEN=pick-a-long-random-string
uv run qcss serve --host 192.168.1.20 --tls-cert certs/server.pem --tls-key certs/server.key --token "$QCSS_TOKEN"
```
`--token` can be omitted when `QCSS_TOKEN` is set. You should see `(TLS, token required)` in the first line. To keep an admin channel, add `--admin-listen <ip>:50052 --admin-token <different-token>` (the same TLS applies; the admin token must differ and is required whenever the lab link has one).

Refusals you may meet (all verified messages):
| You ran | Error |
|---|---|
| `--host 0.0.0.0` with TLS but no token | `refusing to bind 0.0.0.0:50993 without a token; pass --tls-cert/--tls-key and --token, or --insecure on a network you trust` |
| with a token but no TLS | `refusing to bind ... without TLS; ...` |
| only one of cert/key | `pass both --tls-cert and --tls-key, or neither` |
| `--token abc --admin-listen ...` without admin token | `the lab link requires a token, so the admin channel needs one too: pass --admin-token` |
| same value for both tokens | `--admin-token must differ from --token` |

## 3. Connect from the client
Copy `server.pem` (never `server.key`) to the client, then:
```
export QCSS_TOKEN=pick-a-long-random-string
uv run qcss remote ping -t 192.168.1.20:50051 --ca server.pem
uv run qcss remote run examples/jobs/pi_q0.json -t 192.168.1.20:50051 --ca server.pem
```
`--ca` enables TLS. The same `--ca`/`--token`/`--insecure` flags exist on every `qcss remote` and `qcss admin` command (admin reads `QCSS_ADMIN_TOKEN`).

What the client does when something is missing (verified on loopback with TLS):
- Wrong or missing token: `Error UNAUTHENTICATED: missing or invalid bearer token`. (`remote ping` still answers: health checks are exempt from the token.)
- TLS server but client without `--ca`: `Error UNAVAILABLE: failed to connect to all addresses; ... End of TCP stream`.
- Token without `--ca` to a non-local address: refused by the client, `refusing to send the token in cleartext to <addr>`; add `--ca` (or `--insecure` on a trusted network).
- The certificate must name the address the client types. Reach the server by an IP or name not in `valid for:` and the TLS handshake fails; regenerate the cert with that name.

## 4. Optional smoke test
`python scripts/remote_smoke.py --target <ip>:50051 --ca server.pem --token "$QCSS_TOKEN"` (from the README; not run here).

## Quibolab clients
The shipped `platforms/qcss_qblox_5q/platform.py` sets no `ca_file`; copy the platform folder and set it in your copy. See the Qibolab quick-start.

Sources: `scripts/make_dev_cert.py`, `src/qcss/adapters/grpc_server.py` (`check_bind_is_safe`), `src/qcss/cli.py` (`serve`, `_client`, `_admin_channel`).
