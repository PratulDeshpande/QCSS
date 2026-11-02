"""DescribeDevice tells a driver what an instrument driver knows: channels, sample rates and LOs."""
from __future__ import annotations

from qcss.adapters.grpc_server import describe_device
from qcss.config.loader import load_device
from qcss.ir.compiler import build_bindings


def test_each_channel_reports_the_lo_of_its_port(qblox_profile):
    dev = load_device("src/qcss/config/devices/transmon_5q.yaml")
    desc = describe_device(qblox_profile, build_bindings(qblox_profile, dev)).device
    lo = {c.channel_id: c.lo_frequency_hz for c in desc.channels}
    assert lo["xy_q0"] == 4.9e9 and lo["ro_q3"] == 7.0e9
    assert lo["flux_q2"] == 0.0                       # baseband: no LO
