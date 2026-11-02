"""Nothing a lab client can see says 'simulator': platform files, instrument messages, board replies."""
from __future__ import annotations

import asyncio
import pathlib
import re

import pytest

from qcss.runtime.jobs import JobManager
from qcss.v1 import job_pb2, result_pb2

# Words that would give the simulator away (the instrument's maker name, QCSS, is not one of them).
TELLS = re.compile(r"simulat|emulat|\bfake|\bmock|\bstim\b|stimt1a|lindblad|statevector|surrogate|twirl|"
                   r"\btier\b|\bt1a\b|\bt1b\b|device[- ]model|\btruth|qutip|noise fidelity|qcss[\\/]",
                   re.IGNORECASE)
PLATFORMS = pathlib.Path("platforms")


@pytest.mark.parametrize("platform", ["qcss_qblox_5q", "qcss_rfsoc_5q"])
def test_platform_files_read_like_a_labs(platform):
    for f in (PLATFORMS / platform).glob("*"):
        if f.is_file() and f.suffix in (".py", ".json"):
            hits = TELLS.findall(f.read_text(encoding="utf-8"))
            assert not hits, f"{f}: {hits}"


async def _validator(job):
    return None


async def _engine_failure(job_id, job, cancel):
    raise ValueError("StimT1a needs a Clifford gate; pulse 'w0' is not one")
    yield  # pragma: no cover


@pytest.mark.anyio
async def test_a_failed_job_says_nothing_about_the_simulation_on_the_lab_link():
    jobs = JobManager(_engine_failure, _validator, expose_diagnostics=False)
    try:
        job_id = await jobs.submit(job_pb2.Job(num_shots=1))
        _ = [c async for c in jobs.results(job_id)]
        st = jobs.status(job_id)
        assert st.state == result_pb2.JOB_STATE_FAILED
        assert st.message and not TELLS.search(st.message), st.message
        assert "StimT1a" in jobs.failure_detail(job_id)            # kept for the admin channel
    finally:
        await jobs.close()


def test_a_board_error_reply_carries_no_simulator_paths():
    from tests.integration.test_grpc_end_to_end import _can_connect_loopback
    from tests.integration.test_qibosoq_board_server import _Board
    from tests.unit.test_qibosoq_board import drive, readout, request
    client = pytest.importorskip("qibosoq.client")
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    with _Board() as board, pytest.raises(client.QibosoqError) as err:
        client.connect(request([drive(dac=13), readout()]), "127.0.0.1", board.port)
    text = str(err.value)
    assert "dac 13 is not connected" in text and not TELLS.search(text), text


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_tells_pattern_catches_what_it_should():
    assert TELLS.search("Tier routing failed") and TELLS.search(r'File "E:\x\src\qcss\boards\q.py"')
    assert not TELLS.search("qcss_qblox_5q") and not TELLS.search("QcssController@127.0.0.1")
    _ = asyncio  # the async test above runs on anyio's asyncio backend
