from google.protobuf import timestamp_pb2 as _timestamp_pb2
from qcss.v1 import common_pb2 as _common_pb2
from qcss.v1 import job_pb2 as _job_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class JobState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    JOB_STATE_UNSPECIFIED: _ClassVar[JobState]
    JOB_STATE_QUEUED: _ClassVar[JobState]
    JOB_STATE_VALIDATING: _ClassVar[JobState]
    JOB_STATE_RUNNING: _ClassVar[JobState]
    JOB_STATE_COMPLETED: _ClassVar[JobState]
    JOB_STATE_FAILED: _ClassVar[JobState]
    JOB_STATE_CANCELLED: _ClassVar[JobState]
    JOB_STATE_REJECTED: _ClassVar[JobState]

class NoiseFidelity(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    NOISE_FIDELITY_UNSPECIFIED: _ClassVar[NoiseFidelity]
    NOISE_FIDELITY_PHYSICAL: _ClassVar[NoiseFidelity]
    NOISE_FIDELITY_TWIRLED: _ClassVar[NoiseFidelity]
    NOISE_FIDELITY_SURROGATE: _ClassVar[NoiseFidelity]
JOB_STATE_UNSPECIFIED: JobState
JOB_STATE_QUEUED: JobState
JOB_STATE_VALIDATING: JobState
JOB_STATE_RUNNING: JobState
JOB_STATE_COMPLETED: JobState
JOB_STATE_FAILED: JobState
JOB_STATE_CANCELLED: JobState
JOB_STATE_REJECTED: JobState
NOISE_FIDELITY_UNSPECIFIED: NoiseFidelity
NOISE_FIDELITY_PHYSICAL: NoiseFidelity
NOISE_FIDELITY_TWIRLED: NoiseFidelity
NOISE_FIDELITY_SURROGATE: NoiseFidelity

class JobStatus(_message.Message):
    __slots__ = ("job_id", "state", "progress", "message", "submitted_at", "started_at", "finished_at", "tier_used", "noise_fidelity")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    SUBMITTED_AT_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    FINISHED_AT_FIELD_NUMBER: _ClassVar[int]
    TIER_USED_FIELD_NUMBER: _ClassVar[int]
    NOISE_FIDELITY_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    state: JobState
    progress: float
    message: str
    submitted_at: _timestamp_pb2.Timestamp
    started_at: _timestamp_pb2.Timestamp
    finished_at: _timestamp_pb2.Timestamp
    tier_used: _job_pb2.FidelityTier
    noise_fidelity: NoiseFidelity
    def __init__(self, job_id: _Optional[str] = ..., state: _Optional[_Union[JobState, str]] = ..., progress: _Optional[float] = ..., message: _Optional[str] = ..., submitted_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., started_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., finished_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., tier_used: _Optional[_Union[_job_pb2.FidelityTier, str]] = ..., noise_fidelity: _Optional[_Union[NoiseFidelity, str]] = ...) -> None: ...

class AcquisitionResult(_message.Message):
    __slots__ = ("result_key", "iq", "states", "shot_end_ticks")
    RESULT_KEY_FIELD_NUMBER: _ClassVar[int]
    IQ_FIELD_NUMBER: _ClassVar[int]
    STATES_FIELD_NUMBER: _ClassVar[int]
    SHOT_END_TICKS_FIELD_NUMBER: _ClassVar[int]
    result_key: str
    iq: _common_pb2.NdArray
    states: _common_pb2.NdArray
    shot_end_ticks: _common_pb2.NdArray
    def __init__(self, result_key: _Optional[str] = ..., iq: _Optional[_Union[_common_pb2.NdArray, _Mapping]] = ..., states: _Optional[_Union[_common_pb2.NdArray, _Mapping]] = ..., shot_end_ticks: _Optional[_Union[_common_pb2.NdArray, _Mapping]] = ...) -> None: ...

class ResultChunk(_message.Message):
    __slots__ = ("job_id", "sequence_number", "sweep_point", "shot_offset", "num_shots_in_chunk", "acquisitions", "calibration_epoch", "is_last", "warnings")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_NUMBER_FIELD_NUMBER: _ClassVar[int]
    SWEEP_POINT_FIELD_NUMBER: _ClassVar[int]
    SHOT_OFFSET_FIELD_NUMBER: _ClassVar[int]
    NUM_SHOTS_IN_CHUNK_FIELD_NUMBER: _ClassVar[int]
    ACQUISITIONS_FIELD_NUMBER: _ClassVar[int]
    CALIBRATION_EPOCH_FIELD_NUMBER: _ClassVar[int]
    IS_LAST_FIELD_NUMBER: _ClassVar[int]
    WARNINGS_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    sequence_number: int
    sweep_point: _containers.RepeatedScalarFieldContainer[int]
    shot_offset: int
    num_shots_in_chunk: int
    acquisitions: _containers.RepeatedCompositeFieldContainer[AcquisitionResult]
    calibration_epoch: int
    is_last: bool
    warnings: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, job_id: _Optional[str] = ..., sequence_number: _Optional[int] = ..., sweep_point: _Optional[_Iterable[int]] = ..., shot_offset: _Optional[int] = ..., num_shots_in_chunk: _Optional[int] = ..., acquisitions: _Optional[_Iterable[_Union[AcquisitionResult, _Mapping]]] = ..., calibration_epoch: _Optional[int] = ..., is_last: bool = ..., warnings: _Optional[_Iterable[str]] = ...) -> None: ...
