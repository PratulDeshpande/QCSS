"""`qcss serve` refuses a network bind without TLS before it starts anything."""
from __future__ import annotations

from click.testing import CliRunner

from qcss.cli import app


def test_serve_on_all_interfaces_without_tls_is_refused():
    result = CliRunner().invoke(app, ["serve", "--host", "0.0.0.0", "--profile", "test_ideal_1q"])
    assert result.exit_code != 0
    assert "without TLS" in result.output


def test_serve_on_a_lan_address_with_tls_but_no_token_is_refused(tmp_path):
    (tmp_path / "c.pem").write_text("x")
    (tmp_path / "k.pem").write_text("x")
    result = CliRunner().invoke(app, ["serve", "--host", "192.168.1.20", "--tls-cert", str(tmp_path / "c.pem"),
                                      "--tls-key", str(tmp_path / "k.pem"), "--profile", "test_ideal_1q"],
                                env={"QCSS_TOKEN": ""})
    assert result.exit_code != 0
    assert "token" in result.output


def test_serve_needs_both_certificate_and_key():
    result = CliRunner().invoke(app, ["serve", "--tls-cert", "cert.pem", "--profile", "test_ideal_1q"])
    assert result.exit_code != 0
    assert "--tls-cert and --tls-key" in result.output
