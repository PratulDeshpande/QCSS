"""NdArray decoding of what a client sends: bad input is a ValueError the server can report."""
from __future__ import annotations

import pytest

from qcss.core.ndarray import from_proto
from qcss.v1 import common_pb2 as cpb


@pytest.mark.parametrize("message", [
    cpb.NdArray(element_type=cpb.ELEMENT_TYPE_UNSPECIFIED),
    cpb.NdArray(element_type=99, data=b"1234"),  # type: ignore[arg-type]  # proto3 enums are open
    cpb.NdArray(element_type=cpb.ELEMENT_TYPE_FLOAT32, data=b"123"),           # not a whole number of elements
    cpb.NdArray(element_type=cpb.ELEMENT_TYPE_FLOAT32, data=b"1234", shape=[2]),
])
def test_malformed_arrays_raise_value_error(message):
    with pytest.raises(ValueError):
        from_proto(message)
