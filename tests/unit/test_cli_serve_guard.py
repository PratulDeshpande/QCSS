"""`qcss serve` refuses a network bind without TLS before it starts anything."""
from __future__ import annotations

from click.testing import CliRunner

from qcss.cli import app


def test_serve_on_all_interfaces_without_tls_is_refused():
    result = CliRunner().invoke(app, ["serve", "--host", "0.0.0.0", "--profile", "test_ideal_1q"])
    assert result.exit_code != 0
    assert "without TLS" in result.output


def test_serve_needs_both_certificate_and_key():
    result = CliRunner().invoke(app, ["serve", "--tls-cert", "cert.pem", "--profile", "test_ideal_1q"])
    assert result.exit_code != 0
    assert "--tls-cert and --tls-key" in result.output
