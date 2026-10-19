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

* **No authentication or TLS.** The gRPC server (`qcss serve`) binds to `127.0.0.1` by default. Anyone
  who can reach the port can submit jobs and overwrite the calibration. Do not expose it on an
  untrusted network; do not bind `0.0.0.0` without a TLS-terminating proxy you control.
* **Untrusted input is protobuf only.** The server never unpickles network data. `pickle` is used
  solely for parent-to-child process communication inside the server's own worker pool.
* **Resource limits are modest.** Messages are capped at 16 MiB, result queues are bounded, and
  hardware-rule checks reject oversized programs, but a client can still submit many large jobs. The
  server keeps finished jobs in memory until it restarts.

Reports that demonstrate a way around these protections, remote code execution, or memory-safety
problems in QCSS's own code are in scope.
