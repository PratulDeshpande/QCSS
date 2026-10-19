"""The client never sends a bearer token in cleartext to a network address unless told to."""
from __future__ import annotations

import pytest

from qcss.client import QcssClient


def test_token_over_plaintext_to_a_network_address_is_refused():
    with pytest.raises(ValueError, match="cleartext"):
        QcssClient("192.168.1.20:50051", token="t")


@pytest.mark.parametrize("kwargs", [{"tls_ca": b"-----BEGIN CERTIFICATE-----"}, {"insecure": True}])
def test_token_to_a_network_address_is_allowed_with_tls_or_insecure(kwargs):
    QcssClient("192.168.1.20:50051", token="t", **kwargs).close()


@pytest.mark.parametrize("target", ["127.0.0.1:50051", "localhost:50051", "[::1]:50051"])
def test_token_over_plaintext_to_loopback_is_allowed(target):
    QcssClient(target, token="t").close()


def test_no_token_needs_no_tls():
    QcssClient("192.168.1.20:50051").close()


def test_remote_cli_refuses_a_cleartext_token_without_insecure():
    from click.testing import CliRunner

    from qcss.cli import app
    r = CliRunner().invoke(app, ["remote", "describe", "--target", "192.168.1.20:50051", "--token", "t"])
    assert r.exit_code != 0
    assert "cleartext" in r.output
    assert "--insecure" in CliRunner().invoke(app, ["remote", "describe", "--help"]).output
