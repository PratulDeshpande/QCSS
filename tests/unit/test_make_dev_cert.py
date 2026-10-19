"""scripts/make_dev_cert.py writes a self-signed server certificate valid for the given LAN addresses."""
from __future__ import annotations

import importlib.util
import ipaddress
import os

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


def test_an_existing_key_is_not_overwritten_without_force(tmp_path):
    (tmp_path / "server.key").write_text("keep me")
    assert _script().main(["10.0.0.5", "--out", str(tmp_path)]) != 0
    assert (tmp_path / "server.key").read_text() == "keep me"
    assert _script().main(["10.0.0.5", "--out", str(tmp_path), "--force"]) == 0


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_the_private_key_is_readable_by_its_owner_only(tmp_path):
    _script().main(["10.0.0.5", "--out", str(tmp_path)])
    assert (tmp_path / "server.key").stat().st_mode & 0o077 == 0
