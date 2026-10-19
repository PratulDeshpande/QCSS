from qcss.v1 import calibration_pb2 as _calibration_pb2
from qcss.v1 import device_pb2 as _device_pb2
from qcss.v1 import job_pb2 as _job_pb2
from qcss.v1 import result_pb2 as _result_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SubmitJobRequest(_message.Message):
    __slots__ = ("job",)
    JOB_FIELD_NUMBER: _ClassVar[int]
    job: _job_pb2.Job
    def __init__(self, job: _Optional[_Union[_job_pb2.Job, _Mapping]] = ...) -> None: ...

class SubmitJobResponse(_message.Message):
    __slots__ = ("job_id", "calibration_epoch")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    CALIBRATION_EPOCH_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    calibration_epoch: int
    def __init__(self, job_id: _Optional[str] = ..., calibration_epoch: _Optional[int] = ...) -> None: ...

class GetJobStatusRequest(_message.Message):
    __slots__ = ("job_id",)
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    def __init__(self, job_id: _Optional[str] = ...) -> None: ...

class GetJobStatusResponse(_message.Message):
    __slots__ = ("status",)
    STATUS_FIELD_NUMBER: _ClassVar[int]
    status: _result_pb2.JobStatus
    def __init__(self, status: _Optional[_Union[_result_pb2.JobStatus, _Mapping]] = ...) -> None: ...

class CancelJobRequest(_message.Message):
    __slots__ = ("job_id",)
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    def __init__(self, job_id: _Optional[str] = ...) -> None: ...

class CancelJobResponse(_message.Message):
    __slots__ = ("status",)
    STATUS_FIELD_NUMBER: _ClassVar[int]
    status: _result_pb2.JobStatus
    def __init__(self, status: _Optional[_Union[_result_pb2.JobStatus, _Mapping]] = ...) -> None: ...

class StreamResultsRequest(_message.Message):
    __slots__ = ("job_id", "resume_after_sequence")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    RESUME_AFTER_SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    resume_after_sequence: int
    def __init__(self, job_id: _Optional[str] = ..., resume_after_sequence: _Optional[int] = ...) -> None: ...

class StreamResultsResponse(_message.Message):
    __slots__ = ("chunk",)
    CHUNK_FIELD_NUMBER: _ClassVar[int]
    chunk: _result_pb2.ResultChunk
    def __init__(self, chunk: _Optional[_Union[_result_pb2.ResultChunk, _Mapping]] = ...) -> None: ...

class GetCalibrationRequest(_message.Message):
    __slots__ = ("qubit_indices",)
    QUBIT_INDICES_FIELD_NUMBER: _ClassVar[int]
    qubit_indices: _containers.RepeatedScalarFieldContainer[int]
    def __init__(self, qubit_indices: _Optional[_Iterable[int]] = ...) -> None: ...

class GetCalibrationResponse(_message.Message):
    __slots__ = ("snapshot",)
    SNAPSHOT_FIELD_NUMBER: _ClassVar[int]
    snapshot: _calibration_pb2.CalibrationSnapshot
    def __init__(self, snapshot: _Optional[_Union[_calibration_pb2.CalibrationSnapshot, _Mapping]] = ...) -> None: ...

class UpdateCalibrationRequest(_message.Message):
    __slots__ = ("snapshot", "expected_epoch")
    SNAPSHOT_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_EPOCH_FIELD_NUMBER: _ClassVar[int]
    snapshot: _calibration_pb2.CalibrationSnapshot
    expected_epoch: int
    def __init__(self, snapshot: _Optional[_Union[_calibration_pb2.CalibrationSnapshot, _Mapping]] = ..., expected_epoch: _Optional[int] = ...) -> None: ...

class UpdateCalibrationResponse(_message.Message):
    __slots__ = ("new_epoch",)
    NEW_EPOCH_FIELD_NUMBER: _ClassVar[int]
    new_epoch: int
    def __init__(self, new_epoch: _Optional[int] = ...) -> None: ...

class DescribeDeviceRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class DescribeDeviceResponse(_message.Message):
    __slots__ = ("device",)
    DEVICE_FIELD_NUMBER: _ClassVar[int]
    device: _device_pb2.DeviceDescription
    def __init__(self, device: _Optional[_Union[_device_pb2.DeviceDescription, _Mapping]] = ...) -> None: ...
