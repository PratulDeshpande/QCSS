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


def test_serve_refuses_a_network_qick_board_without_insecure():
    """Pyro4 has no TLS and no token, so a QICK board on the network needs the operator's explicit consent."""
    result = CliRunner().invoke(app, ["serve", "--qick-ns", "127.0.0.1:8888", "--qick-listen", "0.0.0.0",
                                      "--profile", "qick_zcu216_5q"])
    assert result.exit_code != 0
    assert "--qick-listen" in result.output and "--insecure" in result.output


def test_serve_refuses_to_start_a_network_nameserver_without_insecure():
    result = CliRunner().invoke(app, ["serve", "--qick-ns", "0.0.0.0:8888", "--qick-start-ns",
                                      "--profile", "qick_zcu216_5q"])
    assert result.exit_code != 0
    assert "--qick-ns" in result.output and "--insecure" in result.output


@pytest.mark.parametrize("address", ["8888", "127.0.0.1", "127.0.0.1:ns"])
def test_serve_refuses_a_qick_nameserver_that_is_not_host_port(address):
    result = CliRunner().invoke(app, ["serve", "--qick-ns", address, "--profile", "qick_zcu216_5q"])
    assert result.exit_code != 0
    assert "--qick-ns" in result.output and "host:port" in result.output


def test_serve_offers_only_the_qick_firmwares_it_has():
    result = CliRunner().invoke(app, ["serve", "--qick-ns", "127.0.0.1:8888", "--qick-firmware", "zcu111_v9",
                                      "--profile", "qick_zcu216_5q"])
    assert result.exit_code != 0
    assert "zcu216_v2_5q" in result.output


@pytest.mark.parametrize("address", ["unix:C:/tmp/board.sock", "127.0.0.1", "127.0.0.1:board"])
def test_serve_refuses_a_board_face_that_is_not_tcp_host_port(address):
    """The qibosoq client connects over TCP only: anything but host:port is refused before anything starts (M5)."""
    result = CliRunner().invoke(app, ["serve", "--board-listen", address, "--profile", "qick_zcu216_5q"])
    assert result.exit_code != 0
    assert "--board-listen" in result.output and "host:port" in result.output


@pytest.mark.parametrize("value", ["6-0", "6:", "a:0", "6:0:1"])
def test_serve_refuses_a_qick_loopback_that_is_not_gen_colon_readout(value):
    result = CliRunner().invoke(app, ["serve", "--qick-ns", "127.0.0.1:8888", "--qick-loopback", value,
                                      "--profile", "qick_zcu216_5q"])
    assert result.exit_code != 0
    assert "--qick-loopback" in result.output and "GEN:RO" in result.output


def test_serve_refuses_a_qick_loopback_without_the_qick_board():
    result = CliRunner().invoke(app, ["serve", "--qick-loopback", "6:0", "--profile", "qick_zcu216_5q"])
    assert result.exit_code != 0
    assert "--qick-loopback" in result.output and "--qick-ns" in result.output


def test_serve_hands_the_qick_test_cables_to_the_chassis(monkeypatch):
    seen = {}

    class Stop(Exception):
        pass

    def fake_chassis(config):
        seen["cables"] = config.qick_loopback
        raise Stop

    monkeypatch.setattr("qcss.chassis.Chassis", fake_chassis)
    result = CliRunner().invoke(app, ["serve", "--qick-ns", "127.0.0.1:8888", "--qick-loopback", "6:0",
                                      "--qick-loopback", "1:2", "--profile", "qick_zcu216_5q"])
    assert isinstance(result.exception, Stop)
    assert seen["cables"] == ((6, 0), (1, 2))
