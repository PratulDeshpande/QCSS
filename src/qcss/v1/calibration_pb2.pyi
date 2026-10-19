from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class MixerCorrection(_message.Message):
    __slots__ = ("dc_offset_i", "dc_offset_q", "gain_ratio", "phase_skew_rad")
    DC_OFFSET_I_FIELD_NUMBER: _ClassVar[int]
    DC_OFFSET_Q_FIELD_NUMBER: _ClassVar[int]
    GAIN_RATIO_FIELD_NUMBER: _ClassVar[int]
    PHASE_SKEW_RAD_FIELD_NUMBER: _ClassVar[int]
    dc_offset_i: float
    dc_offset_q: float
    gain_ratio: float
    phase_skew_rad: float
    def __init__(self, dc_offset_i: _Optional[float] = ..., dc_offset_q: _Optional[float] = ..., gain_ratio: _Optional[float] = ..., phase_skew_rad: _Optional[float] = ...) -> None: ...

class ExponentialStage(_message.Message):
    __slots__ = ("tau_s", "amplitude", "enabled")
    TAU_S_FIELD_NUMBER: _ClassVar[int]
    AMPLITUDE_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    tau_s: float
    amplitude: float
    enabled: bool
    def __init__(self, tau_s: _Optional[float] = ..., amplitude: _Optional[float] = ..., enabled: bool = ...) -> None: ...

class FluxPredistortion(_message.Message):
    __slots__ = ("inverse_highpass_tau_s", "exponential", "fir_coefficients")
    INVERSE_HIGHPASS_TAU_S_FIELD_NUMBER: _ClassVar[int]
    EXPONENTIAL_FIELD_NUMBER: _ClassVar[int]
    FIR_COEFFICIENTS_FIELD_NUMBER: _ClassVar[int]
    inverse_highpass_tau_s: float
    exponential: _containers.RepeatedCompositeFieldContainer[ExponentialStage]
    fir_coefficients: _containers.RepeatedScalarFieldContainer[float]
    def __init__(self, inverse_highpass_tau_s: _Optional[float] = ..., exponential: _Optional[_Iterable[_Union[ExponentialStage, _Mapping]]] = ..., fir_coefficients: _Optional[_Iterable[float]] = ...) -> None: ...

class QubitCalibration(_message.Message):
    __slots__ = ("qubit_index", "drive_frequency_hz", "readout_frequency_hz", "pi_amplitude", "pi_length_samples", "drag_beta_samples", "readout_delay_ticks", "readout_rotation_rad", "readout_threshold", "drive_mixer", "readout_mixer", "flux_predistortion")
    QUBIT_INDEX_FIELD_NUMBER: _ClassVar[int]
    DRIVE_FREQUENCY_HZ_FIELD_NUMBER: _ClassVar[int]
    READOUT_FREQUENCY_HZ_FIELD_NUMBER: _ClassVar[int]
    PI_AMPLITUDE_FIELD_NUMBER: _ClassVar[int]
    PI_LENGTH_SAMPLES_FIELD_NUMBER: _ClassVar[int]
    DRAG_BETA_SAMPLES_FIELD_NUMBER: _ClassVar[int]
    READOUT_DELAY_TICKS_FIELD_NUMBER: _ClassVar[int]
    READOUT_ROTATION_RAD_FIELD_NUMBER: _ClassVar[int]
    READOUT_THRESHOLD_FIELD_NUMBER: _ClassVar[int]
    DRIVE_MIXER_FIELD_NUMBER: _ClassVar[int]
    READOUT_MIXER_FIELD_NUMBER: _ClassVar[int]
    FLUX_PREDISTORTION_FIELD_NUMBER: _ClassVar[int]
    qubit_index: int
    drive_frequency_hz: float
    readout_frequency_hz: float
    pi_amplitude: float
    pi_length_samples: int
    drag_beta_samples: float
    readout_delay_ticks: int
    readout_rotation_rad: float
    readout_threshold: float
    drive_mixer: MixerCorrection
    readout_mixer: MixerCorrection
    flux_predistortion: FluxPredistortion
    def __init__(self, qubit_index: _Optional[int] = ..., drive_frequency_hz: _Optional[float] = ..., readout_frequency_hz: _Optional[float] = ..., pi_amplitude: _Optional[float] = ..., pi_length_samples: _Optional[int] = ..., drag_beta_samples: _Optional[float] = ..., readout_delay_ticks: _Optional[int] = ..., readout_rotation_rad: _Optional[float] = ..., readout_threshold: _Optional[float] = ..., drive_mixer: _Optional[_Union[MixerCorrection, _Mapping]] = ..., readout_mixer: _Optional[_Union[MixerCorrection, _Mapping]] = ..., flux_predistortion: _Optional[_Union[FluxPredistortion, _Mapping]] = ...) -> None: ...

class CalibrationSnapshot(_message.Message):
    __slots__ = ("calibration_epoch", "qubits")
    CALIBRATION_EPOCH_FIELD_NUMBER: _ClassVar[int]
    QUBITS_FIELD_NUMBER: _ClassVar[int]
    calibration_epoch: int
    qubits: _containers.RepeatedCompositeFieldContainer[QubitCalibration]
    def __init__(self, calibration_epoch: _Optional[int] = ..., qubits: _Optional[_Iterable[_Union[QubitCalibration, _Mapping]]] = ...) -> None: ...
