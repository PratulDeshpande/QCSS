"""The qcss-dashboard command: same bind rule as the chassis (off loopback needs TLS and a login token)."""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from qcss_dashboard.cli import UnsafeBind, check_bind, main, settings_from


def test_loopback_binds_need_nothing():
    check_bind("127.0.0.1", tls=False, token=False, insecure=False)
    check_bind("localhost", tls=False, token=False, insecure=False)


@pytest.mark.parametrize(("tls", "token"), [(False, False), (True, False), (False, True)])
def test_network_binds_need_tls_and_a_token(tls, token):
    with pytest.raises(UnsafeBind):
        check_bind("0.0.0.0", tls=tls, token=token, insecure=False)


def test_network_bind_with_tls_and_token_or_insecure_is_allowed():
    check_bind("0.0.0.0", tls=True, token=True, insecure=False)
    check_bind("0.0.0.0", tls=False, token=False, insecure=True)


def test_settings_take_tokens_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("QCSS_TOKEN", "lab-t")
    monkeypatch.setenv("QCSS_ADMIN_TOKEN", "adm-t")
    s = settings_from(workspace=str(tmp_path), lab="10.0.0.2:50051", admin="10.0.0.2:50052", ca=None,
                      access_token=None, read_only=True, embedded=False, profile="qblox_cluster_5q",
                      device="transmon_5q", time_scale=1.0, static=None)
    assert (s.lab_token, s.admin_token, s.read_only, s.embedded_chassis) == ("lab-t", "adm-t", True, False)


def test_refuses_an_unsafe_bind_before_starting(tmp_path):
    r = CliRunner().invoke(main, ["--host", "0.0.0.0", "--workspace", str(tmp_path), "--no-embedded"])
    assert r.exit_code != 0 and "TLS" in r.output
