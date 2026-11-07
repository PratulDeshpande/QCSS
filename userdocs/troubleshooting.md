# Troubleshooting

Find your symptom, read the cause, apply the fix. "Verified" means the message was produced on loopback on 2026-11-05; "Read" means taken from the code or README but not triggered.

## Server will not start
| Symptom | Cause | Fix |
|---|---|---|
| `refusing to bind 0.0.0.0:PORT without TLS and a token; pass --tls-cert/--tls-key and --token, or --insecure ...` (verified; says "a token" or "TLS" alone if only one is missing) | non-loopback bind of the lab link needs both | add both (see `howto/lan-with-tls.md`), or `--insecure` on a trusted network |
| `pass both --tls-cert and --tls-key, or neither` (verified) | only one given | give both |
| `the lab link requires a token, so the admin channel needs one too: pass --admin-token` (verified) | `--token` set, admin channel has none | add `--admin-token` |
| `--admin-token must differ from --token` (verified) | same value | use two tokens |
| `--admin-listen must differ from the instrument address` (Read) | same address | use another port |
| `RuntimeError: Failed to bind to address 127.0.0.1:50981` with `WSA Error ... 10048` just above (verified) | the port is taken, often by an earlier server you forgot | choose another `--port`, or find and stop the old one (below) |
| `refusing to bind the board face to ...: the qibosoq protocol has no TLS and no token` (verified) | `--board-listen` on a network address | `--insecure` (trusted network) or loopback |
| `--board-listen 6011: the board face is TCP host:port` (verified) | bare port | write `127.0.0.1:6011` |
| `refusing to bind --qick-ns/--qick-listen ... to the network: Pyro4 has no TLS and no token` (Read) | QICK face on a network address | `--insecure`, trusted network only |
| `--qick-start-ns needs --qick-ns host:port` / `--qick-loopback needs --qick-ns` / `give GEN:RO` (Read) | QICK options incomplete | give the missing option |
| `the native QICK board needs Pyro4: pip install 'qcss[qick]'` (Read) | missing extra | `uv sync --extra qick` |

## Client cannot connect or is refused
| Symptom | Cause | Fix |
|---|---|---|
| `Error UNAUTHENTICATED: missing or invalid bearer token` (verified, lab and admin) | wrong or missing token | set `QCSS_TOKEN` (lab) or `QCSS_ADMIN_TOKEN` (admin) or pass `--token`. `remote ping` still succeeds with a bad token on purpose |
| `Error UNAVAILABLE: failed to connect to all addresses; ... End of TCP stream` (verified against a TLS server) | client used plaintext, server speaks TLS | add `--ca server.pem` |
| connection refused / `WSA 10061` (verified for a dead port) | server not running, wrong host or port | check the server terminal and `-t` |
| `refusing to send the token in cleartext to <addr>` (verified); admin: `refusing to send the admin token in cleartext to <addr>` (Read) | token + non-local address + no TLS | `--ca server.pem`, or `--insecure` on a trusted network |
| TLS handshake fails for a LAN IP | certificate does not name that address | `scripts/make_dev_cert.py <that-ip>` and re-copy `server.pem` |
| `Error FAILED_PRECONDITION: the chassis runs without a device file` (verified, admin) | server started without `--device` | restart with `--device transmon_5q` |
| `Error UNIMPLEMENTED: Method not implemented!` for `remote properties` (verified) | by design: a lab cannot read the true T1/f01 | use `qcss remote calibration` or the admin channel's `truth` |
| `Error UNAVAILABLE: Connection reset by peer` right after `admin fault drop` (verified) | an injected fault | `qcss admin clear-faults` |

## Jobs fail or look wrong
| Symptom | Cause | Fix |
|---|---|---|
| `Error INVALID_ARGUMENT: ... duration 100 not a multiple of 80 ticks ... integration 1000 not a multiple of 112` (verified) | job written for another profile's timing grid (here `pi_q0.json` on `qick_zcu216_5q`) | use the matching profile, or edit the job; check first with `qcss validate JOB --profile NAME` |
| job state `REJECTED` with `CALIBRATION_EPOCH` (Read, README) | a recalibration landed while the job was pinned to the old epoch | resubmit; read the new epoch with `qcss remote calibration` |
| Every shot reads 0 after an admin action | a killed qubit | `qcss admin truth` (state `DEAD`), `qcss admin revive Q` |
| Counts differ on each run | by design (fresh entropy, job seed ignored) | `qcss serve --seed N --deterministic` (see `howto/seeded-and-deterministic-runs.md`) |
| Chip back to defaults after restart | no `--state-dir`, or process was force-killed before the 60 s autosave | use `--state-dir` and stop with Ctrl+C (`howto/persist-chip-state.md`) |
| Jobs take seconds each | `--time-scale` 1 paces jobs in real time, or the machine is busy | `--time-scale 0` for unpaced test runs |

## Qibolab and Qibosoq faces
| Symptom | Cause | Fix |
|---|---|---|
| `--board-listen needs an RFSoC profile whose ports are dacN ...` at server start (verified; older builds failed late with `dac 0 is not connected`) | Qibosoq board face with the `qblox_cluster_5q` profile | `--profile qick_zcu216_5q` |
| `decimated (raw) acquisition is not supported by this board` (verified) | Qibosoq refuses RAW acquisition | use INTEGRATION or DISCRIMINATION |
| `DC bias ... flux bias is not supported by this board`, `sweeping the DC bias is not supported` (Read) | Qibosoq face refuses DC bias | drop the bias or flux sweep from the sequence |
| `pulse shape '...' is not supported by this board` (Read) | Qibosoq face supports a limited shape set | use a supported shape |
| `ModuleNotFoundError: qibosoq` or numpy conflicts | PyPI qibosoq has no numpy-2 release | `uv pip install "qibosoq @ git+https://github.com/qiboteam/qibosoq@2c376278785e6ae8aae1f13d1b0b467e067aaf7d"` |
| `create_platform` cannot find `qcss_qblox_5q` / `qcss_rfsoc_5q` | `QIBOLAB_PLATFORMS` unset | point it at the repo's `platforms/` |
| platform connects to `192.168.0.81:6000` | `QCSS_RFSOC_5Q_ADDRESS` unset (that is the default) | set it to `127.0.0.1:6010` or your server |
| Qibolab client "token refused to send" | no CA for a non-local address | set `ca_file` in your copy of the platform |

## QICK face (Pyro4)
| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: Pyro4` | missing extra | `uv sync --extra qick` |
| `ModuleNotFoundError: qick` or version error | `qick==0.2.370` not installed | `uv pip install qick==0.2.370` |
| client cannot find `myqick` | nameserver not running, wrong `ns_port`, or `--qick-name` differs from `proxy_name` | use `--qick-start-ns` (or run your own nameserver) and match name and port |
| Nameserver port already in use (Read) | an older nameserver on 8888 | pick another `--qick-ns host:port` and use the same in `make_proxy` |
| remote client finds the name but cannot call it | the daughter Pyro4 port is firewalled, or `--qick-listen` is loopback | bind `--qick-listen <ip> --insecure`, open the firewall (*unverified between machines*) |

## uv and installs
| Symptom | Cause | Fix |
|---|---|---|
| Manual `qick` or `qibosoq` disappears | `uv sync` removes packages it was not told about | run `uv sync --extra ... --group ...` with every extra you need, then `uv pip install` the manual ones again |
| `uv run` re-syncs and removes extras | same | `uv run --no-sync ...` after a custom install (flag of `uv`; not run here) |
| `qcss-dashboard` command not found | the dashboard package is separate | `PYTHONPATH=integrations/qcss_dashboard/src uv run python -m qcss_dashboard.cli` |
| Explorer shows a blank or missing UI | frontend not built | `cd integrations/qcss_dashboard/web && npm ci && npm run build` (Node 20.19+ or 22) |

## Windows specifics
- PowerShell sets variables as `$env:NAME = "value"`; bash as `export NAME=value`. A variable set in one terminal does not exist in another.
- Paths: `--listen unix:C:/Users/me/qcss.sock` form for sockets; otherwise use forward or double backslashes in `--env`/paths.
- Stop a server with Ctrl+C in its own terminal (that also saves `--state-dir`). `uv run` starts a launcher plus a child python, so Task Manager shows two processes per server; stop both of the one you started, nobody else's.
- To see what uses a port: `netstat -ano | findstr :50981`, then the PID in Task Manager. (`Get-NetTCPConnection` may print nothing for a process in some shells; I saw that.)
- Python 3.12 or 3.13 only.

Sources: `src/qcss/cli.py`, `src/qcss/adapters/grpc_server.py`, `src/qcss/boards/qibosoq.py`, README.
