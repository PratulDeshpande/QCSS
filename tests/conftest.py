"""Pytest configuration and shared fixtures for QCSS."""
from __future__ import annotations

import os
import pathlib
import tempfile

import pytest

# Suppress matplotlib cache directory warning on Windows
os.environ.setdefault("MPLCONFIGDIR", tempfile.gettempdir())

# No event-loop patching: asyncio's self-pipe is how worker threads (asyncio.to_thread) and
# gRPC wake the loop. Sandboxes that forbid loopback sockets are handled by skipping the
# networked test (see _can_connect_loopback in test_grpc_end_to_end.py).

from qcss.config.loader import load_profile
from qcss.core.timebase import TimeBase

TESTS_DIR = pathlib.Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
PROFILES_DIR = REPO_ROOT / "src" / "qcss" / "config" / "profiles"


@pytest.fixture
def qblox_profile():
    return load_profile(PROFILES_DIR / "qblox_cluster_5q.yaml")


@pytest.fixture
def zi_profile():
    return load_profile(PROFILES_DIR / "zi_shfqc_5q.yaml")


@pytest.fixture
def test_ideal_profile():
    return load_profile(PROFILES_DIR / "test_ideal_1q.yaml")


@pytest.fixture
def timebase_1ghz():
    return TimeBase.from_clocks("1e9")
