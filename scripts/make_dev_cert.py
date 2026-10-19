"""Make a self-signed TLS certificate for `qcss serve` on a lab or home network.

    python scripts/make_dev_cert.py 192.168.1.20            # the server laptop's LAN address(es)

Writes server.pem (give a copy to every client: it is what they trust) and server.key (keep it on
the server; on Linux/macOS it is created owner-only). The certificate also names localhost and
127.0.0.1, is valid for 365 days, and needs the `cryptography` package (python -m pip install cryptography).
"""
from __future__ import annotations

import argparse
import datetime
import ipaddress
import os
import pathlib
import sys


def main(argv: list[str] | None = None) -> int:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("names", nargs="+", help="IP addresses and/or host names clients will use to reach the server")
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("."), help="output directory")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--force", action="store_true", help="overwrite an existing server.key")
    args = ap.parse_args(argv)
    key_path = args.out / "server.key"
    if key_path.exists() and not args.force:
        print(f"error: {key_path} exists; pass --force to replace it (clients must then get the new server.pem)")
        return 1

    alt: list[x509.GeneralName] = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    for name in args.names:
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:
            alt.append(x509.DNSName(name))

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"qcss {args.names[0]}")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=args.days))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "server.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.unlink(missing_ok=True)
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)     # owner-only from creation (POSIX)
    with os.fdopen(fd, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    print(f"wrote {args.out / 'server.pem'} (copy to clients) and {args.out / 'server.key'} (keep private)")
    print("valid for: " + ", ".join(str(n.value) for n in alt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
