"""NdArray <-> numpy conversion (bytes payload; no element-wise copies on receive)."""
from __future__ import annotations

import numpy as np

from qcss.v1 import common_pb2 as cpb

_TO_NP = {
    cpb.ELEMENT_TYPE_FLOAT32: np.dtype("<f4"),
    cpb.ELEMENT_TYPE_FLOAT64: np.dtype("<f8"),
    cpb.ELEMENT_TYPE_COMPLEX64: np.dtype("<c8"),
    cpb.ELEMENT_TYPE_COMPLEX128: np.dtype("<c16"),
    cpb.ELEMENT_TYPE_INT8: np.dtype("i1"),
    cpb.ELEMENT_TYPE_UINT8: np.dtype("u1"),
    cpb.ELEMENT_TYPE_INT32: np.dtype("<i4"),
    cpb.ELEMENT_TYPE_UINT64: np.dtype("<u8"),
}
_FROM_NP = {v: k for k, v in _TO_NP.items()}


def to_proto(a: np.ndarray) -> cpb.NdArray:
    a = np.ascontiguousarray(a)
    dt = a.dtype.newbyteorder("<") if a.dtype.byteorder == ">" else a.dtype
    try:
        et = _FROM_NP[np.dtype(dt)]
    except KeyError as exc:
        raise TypeError(f"unsupported dtype {a.dtype}") from exc
    return cpb.NdArray(element_type=et, shape=list(a.shape), data=a.astype(dt, copy=False).tobytes())


def from_proto(m: cpb.NdArray) -> np.ndarray:
    if m.element_type == cpb.ELEMENT_TYPE_UNSPECIFIED:
        raise ValueError("NdArray.element_type is UNSPECIFIED")
    dt = _TO_NP[m.element_type]
    arr = np.frombuffer(m.data, dtype=dt)
    return arr.reshape(tuple(m.shape)) if len(m.shape) else arr
