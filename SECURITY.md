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

* **Authentication and TLS are opt-in.** The gRPC server (`qcss serve`) binds to `127.0.0.1` by
  default, without TLS or a token. For LAN use pass `--tls-cert`/`--tls-key` and `--token` (or
  `QCSS_TOKEN`): every call except the gRPC health check then needs `authorization: Bearer <token>`.
  `qcss serve` refuses a non-loopback bind without TLS and a token unless `--insecure` is given. There is one
  shared token and no per-user access control: anyone holding it can submit jobs and overwrite the
  calibration.
* **Untrusted input is protobuf only.** The server never unpickles network data. `pickle` is used
  solely for parent-to-child process communication inside the server's own worker pool.
* **Resource limits are modest.** Messages are capped at 16 MiB and hardware-rule checks reject
  oversized programs, but a client can still submit many large jobs. The server keeps each job's
  results so clients can reconnect and resume: at most 256 MiB per job (older chunks every reader has
  passed are dropped, and resuming before them returns `OUT_OF_RANGE`) and the 256 most recent
  finished jobs (older ones return `NOT_FOUND`).
* **The client protects the token.** `QcssClient` and `qcss remote` refuse to send a token without
  TLS to a non-loopback address unless `insecure=True` / `--insecure` is given.

Reports that demonstrate a way around these protections, remote code execution, or memory-safety
problems in QCSS's own code are in scope.
