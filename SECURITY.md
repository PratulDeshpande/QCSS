# Security Policy

## Supported versions

QCSS is alpha software. Only the latest release (and the `main` branch) receives security fixes.

| Version | Supported |
| --- | --- |
| latest `0.x` release, `main` | yes |
| older releases | no |

## Reporting a vulnerability

Please report vulnerabilities **privately**, not as a public issue or pull request.

Use GitHub's private reporting: open the repository's **Security** tab and choose
**Report a vulnerability** (<https://github.com/PratulDeshpande/qcss/security/advisories/new>).

Include what you found, how to reproduce it, and the version or commit. You can expect an
acknowledgement within a week. Fixes are released as soon as practical, and reporters are credited
in the advisory unless they prefer otherwise.

## Security model and known limits

QCSS is a **local development and test tool**, not a hardened network service. Please keep these in
mind before reporting them as vulnerabilities:

* **Three listeners, each loopback by default.** `qcss serve` can open:
  * the **instrument link** (gRPC, `--listen`/`--host`): for LAN use pass `--tls-cert`/`--tls-key` and
    `--token` (or `QCSS_TOKEN`); every call except the gRPC health check then needs
    `authorization: Bearer <token>`;
  * the **admin channel** (gRPC, `--admin-listen`): its own token (`--admin-token` or
    `QCSS_ADMIN_TOKEN`), which must differ from the lab token and is required whenever the lab link has
    a token. It can read the chip's true state and inject faults, so treat its token as the more
    sensitive one. The lab listener never serves admin RPCs;
  * the **Qibosoq board face** (TCP/JSON, `--board-listen`): no TLS and no token, because the Qibosoq
    protocol has neither.

  Any non-loopback bind is refused without TLS and a token (for the board face: always) unless
  `--insecure` is given. There is one token per channel and no per-user access control: anyone holding
  the lab token can submit jobs and overwrite the calibration.
* **Untrusted input is protobuf or JSON only.** The server never unpickles network data. The board
  face parses JSON; the chip state file (`--state-dir`) and the technician's request spool are plain
  JSON, and a pickle in place of the state file is refused, not executed. `pickle` is used solely for
  parent-to-child communication inside the server's own worker pool.
* **Resource limits are modest.** gRPC messages are capped at 16 MiB and hardware-rule checks reject
  oversized programs, but a client can still submit many large jobs (the chassis runs one at a time and
  queues the rest). The server keeps each job's results so clients can reconnect and resume: at most
  256 MiB per job (older chunks every reader has passed are dropped, and resuming before them returns
  `OUT_OF_RANGE`) and the 256 most recent finished jobs (older ones return `NOT_FOUND`). The board face
  refuses requests over 16 MiB without reading them, drops a client that takes more than 30 s to send
  its request, and refuses sweeps beyond 2^18 points x sequence elements, each with the board's own
  resource error. It does not cap `reps`: the reply to a long unaveraged run is held in memory.
* **The clients protect the tokens.** `QcssClient`, `qcss remote` and `qcss admin` refuse to send a
  token without TLS to a non-loopback address unless `insecure=True` / `--insecure` is given.
* **The technician runs Qibocal as a subprocess** with the platform folder and the environment you
  give it (`--env`). The request spool is a local folder; protect it like any lab-side config.

Reports that demonstrate a way around these protections, remote code execution, or memory-safety
problems in QCSS's own code are in scope.
