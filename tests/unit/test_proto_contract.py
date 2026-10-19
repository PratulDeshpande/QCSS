"""Unit tests verifying protobuf contract rules and NdArray serialization."""
from __future__ import annotations

import numpy as np
import pytest

from qcss.core.ndarray import from_proto, to_proto
from qcss.v1 import common_pb2, device_pb2, job_pb2, result_pb2


def test_enum_zero_values_unspecified():
    """Verify that every enum has *_UNSPECIFIED = 0."""
    enums = [
        common_pb2.ElementType,
        device_pb2.ChannelKind,
        job_pb2.FidelityTier,
        job_pb2.WaveformShape,
        job_pb2.AcquisitionMode,
        job_pb2.ConditionOp,
        result_pb2.JobState,
        result_pb2.NoiseFidelity,
    ]
    for enum_desc in enums:
        values = enum_desc.DESCRIPTOR.values
        zero_val = [v for v in values if v.number == 0]
        assert len(zero_val) == 1, f"Enum {enum_desc.name} has no zero value"
        assert zero_val[0].name.endswith("_UNSPECIFIED"), (
            f"Enum {enum_desc.name} zero value {zero_val[0].name} does not end with _UNSPECIFIED"
        )


def test_ndarray_roundtrip_all_dtypes():
    dtypes = [
        np.float32, np.float64, np.complex64, np.complex128,
        np.int8, np.uint8, np.int32, np.uint64
    ]
    for dt in dtypes:
        original = (np.arange(12) + 1).astype(dt).reshape((3, 4))
        proto_msg = to_proto(original)
        restored = from_proto(proto_msg)
        assert restored.dtype == dt
        assert restored.shape == (3, 4)
        assert np.array_equal(original, restored)


def test_ndarray_unspecified_rejected():
    raw = common_pb2.NdArray(element_type=common_pb2.ELEMENT_TYPE_UNSPECIFIED, shape=[2], data=b"\x00\x00")
    with pytest.raises(ValueError, match="UNSPECIFIED"):
        from_proto(raw)


def test_job_structure():
    job = job_pb2.Job(
        num_shots=1000,
        job_key="job-test-123",
        requested_tier=job_pb2.FIDELITY_TIER_T2_LINDBLAD,
        random_seed=42,
    )
    job.waveform_library["x_pi"].CopyFrom(
        job_pb2.Waveform(
            shape=job_pb2.WAVEFORM_SHAPE_GAUSSIAN,
            length_samples=20,
            sigma_samples=5.0,
        )
    )
    assert job.num_shots == 1000
    assert job.job_key == "job-test-123"
    assert "x_pi" in job.waveform_library
    assert job.waveform_library["x_pi"].shape == job_pb2.WAVEFORM_SHAPE_GAUSSIAN
