from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ElementType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ELEMENT_TYPE_UNSPECIFIED: _ClassVar[ElementType]
    ELEMENT_TYPE_FLOAT32: _ClassVar[ElementType]
    ELEMENT_TYPE_FLOAT64: _ClassVar[ElementType]
    ELEMENT_TYPE_COMPLEX64: _ClassVar[ElementType]
    ELEMENT_TYPE_COMPLEX128: _ClassVar[ElementType]
    ELEMENT_TYPE_INT8: _ClassVar[ElementType]
    ELEMENT_TYPE_UINT8: _ClassVar[ElementType]
    ELEMENT_TYPE_INT32: _ClassVar[ElementType]
    ELEMENT_TYPE_UINT64: _ClassVar[ElementType]
ELEMENT_TYPE_UNSPECIFIED: ElementType
ELEMENT_TYPE_FLOAT32: ElementType
ELEMENT_TYPE_FLOAT64: ElementType
ELEMENT_TYPE_COMPLEX64: ElementType
ELEMENT_TYPE_COMPLEX128: ElementType
ELEMENT_TYPE_INT8: ElementType
ELEMENT_TYPE_UINT8: ElementType
ELEMENT_TYPE_INT32: ElementType
ELEMENT_TYPE_UINT64: ElementType

class NdArray(_message.Message):
    __slots__ = ("element_type", "shape", "data")
    ELEMENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    SHAPE_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    element_type: ElementType
    shape: _containers.RepeatedScalarFieldContainer[int]
    data: bytes
    def __init__(self, element_type: _Optional[_Union[ElementType, str]] = ..., shape: _Optional[_Iterable[int]] = ..., data: _Optional[bytes] = ...) -> None: ...
