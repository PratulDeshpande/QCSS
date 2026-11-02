from qcss.v1 import device_pb2 as _device_pb2
from qcss.v1 import job_pb2 as _job_pb2
from qcss.v1 import result_pb2 as _result_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class InstrumentFault(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    INSTRUMENT_FAULT_UNSPECIFIED: _ClassVar[InstrumentFault]
    INSTRUMENT_FAULT_HANG: _ClassVar[InstrumentFault]
    INSTRUMENT_FAULT_DROP: _ClassVar[InstrumentFault]
    INSTRUMENT_FAULT_REBOOT: _ClassVar[InstrumentFault]
    INSTRUMENT_FAULT_SLOW_UPLOAD: _ClassVar[InstrumentFault]
INSTRUMENT_FAULT_UNSPECIFIED: InstrumentFault
INSTRUMENT_FAULT_HANG: InstrumentFault
INSTRUMENT_FAULT_DROP: InstrumentFault
INSTRUMENT_FAULT_REBOOT: InstrumentFault
INSTRUMENT_FAULT_SLOW_UPLOAD: InstrumentFault

class KillQubitRequest(_message.Message):
    __slots__ = ("qubit_index",)
    QUBIT_INDEX_FIELD_NUMBER: _ClassVar[int]
    qubit_index: int
    def __init__(self, qubit_index: _Optional[int] = ...) -> None: ...

class KillQubitResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ReviveQubitRequest(_message.Message):
    __slots__ = ("qubit_index",)
    QUBIT_INDEX_FIELD_NUMBER: _ClassVar[int]
    qubit_index: int
    def __init__(self, qubit_index: _Optional[int] = ...) -> None: ...

class ReviveQubitResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class DriftStepRequest(_message.Message):
    __slots__ = ("qubit_index", "delta_frequency_hz", "t1_factor")
    QUBIT_INDEX_FIELD_NUMBER: _ClassVar[int]
    DELTA_FREQUENCY_HZ_FIELD_NUMBER: _ClassVar[int]
    T1_FACTOR_FIELD_NUMBER: _ClassVar[int]
    qubit_index: int
    delta_frequency_hz: float
    t1_factor: float
    def __init__(self, qubit_index: _Optional[int] = ..., delta_frequency_hz: _Optional[float] = ..., t1_factor: _Optional[float] = ...) -> None: ...

class DriftStepResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class TlsCollisionRequest(_message.Message):
    __slots__ = ("qubit_index", "coupling_hz", "linewidth_hz", "detuning_hz")
    QUBIT_INDEX_FIELD_NUMBER: _ClassVar[int]
    COUPLING_HZ_FIELD_NUMBER: _ClassVar[int]
    LINEWIDTH_HZ_FIELD_NUMBER: _ClassVar[int]
    DETUNING_HZ_FIELD_NUMBER: _ClassVar[int]
    qubit_index: int
    coupling_hz: float
    linewidth_hz: float
    detuning_hz: float
    def __init__(self, qubit_index: _Optional[int] = ..., coupling_hz: _Optional[float] = ..., linewidth_hz: _Optional[float] = ..., detuning_hz: _Optional[float] = ...) -> None: ...

class TlsCollisionResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class BurstRequest(_message.Message):
    __slots__ = ("qubit_index", "peak_gamma_per_s")
    QUBIT_INDEX_FIELD_NUMBER: _ClassVar[int]
    PEAK_GAMMA_PER_S_FIELD_NUMBER: _ClassVar[int]
    qubit_index: int
    peak_gamma_per_s: float
    def __init__(self, qubit_index: _Optional[int] = ..., peak_gamma_per_s: _Optional[float] = ...) -> None: ...

class BurstResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class FreezeDriftRequest(_message.Message):
    __slots__ = ("frozen",)
    FROZEN_FIELD_NUMBER: _ClassVar[int]
    frozen: bool
    def __init__(self, frozen: bool = ...) -> None: ...

class FreezeDriftResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ClearScenariosRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ClearScenariosResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class Mode(_message.Message):
    __slots__ = ("time_scale", "deterministic", "tier_policy")
    TIME_SCALE_FIELD_NUMBER: _ClassVar[int]
    DETERMINISTIC_FIELD_NUMBER: _ClassVar[int]
    TIER_POLICY_FIELD_NUMBER: _ClassVar[int]
    time_scale: float
    deterministic: bool
    tier_policy: _job_pb2.FidelityTier
    def __init__(self, time_scale: _Optional[float] = ..., deterministic: bool = ..., tier_policy: _Optional[_Union[_job_pb2.FidelityTier, str]] = ...) -> None: ...

class GetModeRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class GetModeResponse(_message.Message):
    __slots__ = ("mode", "global_seed")
    MODE_FIELD_NUMBER: _ClassVar[int]
    GLOBAL_SEED_FIELD_NUMBER: _ClassVar[int]
    mode: Mode
    global_seed: int
    def __init__(self, mode: _Optional[_Union[Mode, _Mapping]] = ..., global_seed: _Optional[int] = ...) -> None: ...

class SetModeRequest(_message.Message):
    __slots__ = ("mode",)
    MODE_FIELD_NUMBER: _ClassVar[int]
    mode: Mode
    def __init__(self, mode: _Optional[_Union[Mode, _Mapping]] = ...) -> None: ...

class SetModeResponse(_message.Message):
    __slots__ = ("mode",)
    MODE_FIELD_NUMBER: _ClassVar[int]
    mode: Mode
    def __init__(self, mode: _Optional[_Union[Mode, _Mapping]] = ...) -> None: ...

class QubitTruth(_message.Message):
    __slots__ = ("qubit_index", "frequency_hz", "t1_s", "dead")
    QUBIT_INDEX_FIELD_NUMBER: _ClassVar[int]
    FREQUENCY_HZ_FIELD_NUMBER: _ClassVar[int]
    T1_S_FIELD_NUMBER: _ClassVar[int]
    DEAD_FIELD_NUMBER: _ClassVar[int]
    qubit_index: int
    frequency_hz: float
    t1_s: float
    dead: bool
    def __init__(self, qubit_index: _Optional[int] = ..., frequency_hz: _Optional[float] = ..., t1_s: _Optional[float] = ..., dead: bool = ...) -> None: ...

class ReadTruthRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ReadTruthResponse(_message.Message):
    __slots__ = ("lab_time_s", "qubits", "properties")
    LAB_TIME_S_FIELD_NUMBER: _ClassVar[int]
    QUBITS_FIELD_NUMBER: _ClassVar[int]
    PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    lab_time_s: float
    qubits: _containers.RepeatedCompositeFieldContainer[QubitTruth]
    properties: _device_pb2.DeviceProperties
    def __init__(self, lab_time_s: _Optional[float] = ..., qubits: _Optional[_Iterable[_Union[QubitTruth, _Mapping]]] = ..., properties: _Optional[_Union[_device_pb2.DeviceProperties, _Mapping]] = ...) -> None: ...

class InspectJobRequest(_message.Message):
    __slots__ = ("job_id",)
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    def __init__(self, job_id: _Optional[str] = ...) -> None: ...

class InspectJobResponse(_message.Message):
    __slots__ = ("tier_used", "noise_fidelity", "calibration_epoch", "warnings")
    TIER_USED_FIELD_NUMBER: _ClassVar[int]
    NOISE_FIDELITY_FIELD_NUMBER: _ClassVar[int]
    CALIBRATION_EPOCH_FIELD_NUMBER: _ClassVar[int]
    WARNINGS_FIELD_NUMBER: _ClassVar[int]
    tier_used: _job_pb2.FidelityTier
    noise_fidelity: _result_pb2.NoiseFidelity
    calibration_epoch: int
    warnings: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, tier_used: _Optional[_Union[_job_pb2.FidelityTier, str]] = ..., noise_fidelity: _Optional[_Union[_result_pb2.NoiseFidelity, str]] = ..., calibration_epoch: _Optional[int] = ..., warnings: _Optional[_Iterable[str]] = ...) -> None: ...

class InjectInstrumentFaultRequest(_message.Message):
    __slots__ = ("fault", "count", "duration_s")
    FAULT_FIELD_NUMBER: _ClassVar[int]
    COUNT_FIELD_NUMBER: _ClassVar[int]
    DURATION_S_FIELD_NUMBER: _ClassVar[int]
    fault: InstrumentFault
    count: int
    duration_s: float
    def __init__(self, fault: _Optional[_Union[InstrumentFault, str]] = ..., count: _Optional[int] = ..., duration_s: _Optional[float] = ...) -> None: ...

class InjectInstrumentFaultResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ClearInstrumentFaultsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ClearInstrumentFaultsResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...
