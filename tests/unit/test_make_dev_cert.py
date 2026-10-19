"""scripts/make_dev_cert.py writes a self-signed server certificate valid for the given LAN addresses."""
from __future__ import annotations

import importlib.util
import ipaddress

import pytest

from tests.conftest import REPO_ROOT

x509 = pytest.importorskip("cryptography.x509")


def _script():
    spec = importlib.util.spec_from_file_location("make_dev_cert", REPO_ROOT / "scripts" / "make_dev_cert.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_certificate_names_every_address_and_the_key_is_private(tmp_path):
    assert _script().main(["192.168.1.20", "qcss-lab.local", "--out", str(tmp_path)]) == 0
    cert = x509.load_pem_x509_certificate((tmp_path / "server.pem").read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert ipaddress.ip_address("192.168.1.20") in san.get_values_for_type(x509.IPAddress)
    assert ipaddress.ip_address("127.0.0.1") in san.get_values_for_type(x509.IPAddress)
    assert {"qcss-lab.local", "localhost"} <= set(san.get_values_for_type(x509.DNSName))
    assert b"PRIVATE KEY" in (tmp_path / "server.key").read_bytes()
    assert b"PRIVATE KEY" not in (tmp_path / "server.pem").read_bytes()
