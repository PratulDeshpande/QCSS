"""`qcss serve` refuses a network bind without TLS before it starts anything."""
from __future__ import annotations

import pytest
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


def test_serve_refuses_a_negative_time_scale():
    result = CliRunner().invoke(app, ["serve", "--time-scale", "-1", "--profile", "test_ideal_1q"])
    assert result.exit_code != 0
    assert "Invalid value for '--time-scale'" in result.output


def test_serve_refuses_a_network_board_bind_without_insecure():
    """The qibosoq protocol has no TLS and no token: on a network it needs the operator's explicit consent."""
    result = CliRunner().invoke(app, ["serve", "--board-listen", "0.0.0.0:6000", "--profile", "qick_zcu216_5q"])
    assert result.exit_code != 0
    assert "board" in result.output and "--insecure" in result.output


@pytest.mark.parametrize("address", ["unix:C:/tmp/board.sock", "127.0.0.1", "127.0.0.1:board"])
def test_serve_refuses_a_board_face_that_is_not_tcp_host_port(address):
    """The qibosoq client connects over TCP only: anything but host:port is refused before anything starts (M5)."""
    result = CliRunner().invoke(app, ["serve", "--board-listen", address, "--profile", "qick_zcu216_5q"])
    assert result.exit_code != 0
    assert "--board-listen" in result.output and "host:port" in result.output
