from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ChannelKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CHANNEL_KIND_UNSPECIFIED: _ClassVar[ChannelKind]
    CHANNEL_KIND_DRIVE: _ClassVar[ChannelKind]
    CHANNEL_KIND_FLUX: _ClassVar[ChannelKind]
    CHANNEL_KIND_READOUT: _ClassVar[ChannelKind]
    CHANNEL_KIND_CROSS_RESONANCE: _ClassVar[ChannelKind]
CHANNEL_KIND_UNSPECIFIED: ChannelKind
CHANNEL_KIND_DRIVE: ChannelKind
CHANNEL_KIND_FLUX: ChannelKind
CHANNEL_KIND_READOUT: ChannelKind
CHANNEL_KIND_CROSS_RESONANCE: ChannelKind

class ChannelInfo(_message.Message):
    __slots__ = ("channel_id", "kind", "generator_id", "port_id", "frame_id", "qubits", "sample_rate_hz")
    CHANNEL_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    GENERATOR_ID_FIELD_NUMBER: _ClassVar[int]
    PORT_ID_FIELD_NUMBER: _ClassVar[int]
    FRAME_ID_FIELD_NUMBER: _ClassVar[int]
    QUBITS_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_RATE_HZ_FIELD_NUMBER: _ClassVar[int]
    channel_id: str
    kind: ChannelKind
    generator_id: str
    port_id: str
    frame_id: str
    qubits: _containers.RepeatedScalarFieldContainer[int]
    sample_rate_hz: float
    def __init__(self, channel_id: _Optional[str] = ..., kind: _Optional[_Union[ChannelKind, str]] = ..., generator_id: _Optional[str] = ..., port_id: _Optional[str] = ..., frame_id: _Optional[str] = ..., qubits: _Optional[_Iterable[int]] = ..., sample_rate_hz: _Optional[float] = ...) -> None: ...

class DeviceDescription(_message.Message):
    __slots__ = ("profile_name", "vendor", "tick_hz", "channels", "max_discriminated_states", "default_repetition_delay_ticks")
    PROFILE_NAME_FIELD_NUMBER: _ClassVar[int]
    VENDOR_FIELD_NUMBER: _ClassVar[int]
    TICK_HZ_FIELD_NUMBER: _ClassVar[int]
    CHANNELS_FIELD_NUMBER: _ClassVar[int]
    MAX_DISCRIMINATED_STATES_FIELD_NUMBER: _ClassVar[int]
    DEFAULT_REPETITION_DELAY_TICKS_FIELD_NUMBER: _ClassVar[int]
    profile_name: str
    vendor: str
    tick_hz: str
    channels: _containers.RepeatedCompositeFieldContainer[ChannelInfo]
    max_discriminated_states: int
    default_repetition_delay_ticks: int
    def __init__(self, profile_name: _Optional[str] = ..., vendor: _Optional[str] = ..., tick_hz: _Optional[str] = ..., channels: _Optional[_Iterable[_Union[ChannelInfo, _Mapping]]] = ..., max_discriminated_states: _Optional[int] = ..., default_repetition_delay_ticks: _Optional[int] = ...) -> None: ...
