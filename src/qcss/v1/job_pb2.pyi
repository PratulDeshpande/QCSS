from qcss.v1 import common_pb2 as _common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class FidelityTier(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FIDELITY_TIER_UNSPECIFIED: _ClassVar[FidelityTier]
    FIDELITY_TIER_AUTO: _ClassVar[FidelityTier]
    FIDELITY_TIER_T0_SURROGATE: _ClassVar[FidelityTier]
    FIDELITY_TIER_T1A_STABILIZER: _ClassVar[FidelityTier]
    FIDELITY_TIER_T1B_STATEVECTOR: _ClassVar[FidelityTier]
    FIDELITY_TIER_T2_LINDBLAD: _ClassVar[FidelityTier]
    FIDELITY_TIER_T3_TRAJECTORY: _ClassVar[FidelityTier]

class WaveformShape(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    WAVEFORM_SHAPE_UNSPECIFIED: _ClassVar[WaveformShape]
    WAVEFORM_SHAPE_ARBITRARY: _ClassVar[WaveformShape]
    WAVEFORM_SHAPE_GAUSSIAN: _ClassVar[WaveformShape]
    WAVEFORM_SHAPE_DRAG: _ClassVar[WaveformShape]
    WAVEFORM_SHAPE_SQUARE: _ClassVar[WaveformShape]
    WAVEFORM_SHAPE_COSINE_FLATTOP: _ClassVar[WaveformShape]

class AcquisitionMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ACQUISITION_MODE_UNSPECIFIED: _ClassVar[AcquisitionMode]
    ACQUISITION_MODE_RAW_TRACE: _ClassVar[AcquisitionMode]
    ACQUISITION_MODE_INTEGRATED: _ClassVar[AcquisitionMode]
    ACQUISITION_MODE_DISCRIMINATED: _ClassVar[AcquisitionMode]

class ConditionOp(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CONDITION_OP_UNSPECIFIED: _ClassVar[ConditionOp]
    CONDITION_OP_EQUAL: _ClassVar[ConditionOp]
    CONDITION_OP_NOT_EQUAL: _ClassVar[ConditionOp]
    CONDITION_OP_MASK_AND: _ClassVar[ConditionOp]
    CONDITION_OP_MASK_OR: _ClassVar[ConditionOp]
    CONDITION_OP_MASK_XOR: _ClassVar[ConditionOp]
FIDELITY_TIER_UNSPECIFIED: FidelityTier
FIDELITY_TIER_AUTO: FidelityTier
FIDELITY_TIER_T0_SURROGATE: FidelityTier
FIDELITY_TIER_T1A_STABILIZER: FidelityTier
FIDELITY_TIER_T1B_STATEVECTOR: FidelityTier
FIDELITY_TIER_T2_LINDBLAD: FidelityTier
FIDELITY_TIER_T3_TRAJECTORY: FidelityTier
WAVEFORM_SHAPE_UNSPECIFIED: WaveformShape
WAVEFORM_SHAPE_ARBITRARY: WaveformShape
WAVEFORM_SHAPE_GAUSSIAN: WaveformShape
WAVEFORM_SHAPE_DRAG: WaveformShape
WAVEFORM_SHAPE_SQUARE: WaveformShape
WAVEFORM_SHAPE_COSINE_FLATTOP: WaveformShape
ACQUISITION_MODE_UNSPECIFIED: AcquisitionMode
ACQUISITION_MODE_RAW_TRACE: AcquisitionMode
ACQUISITION_MODE_INTEGRATED: AcquisitionMode
ACQUISITION_MODE_DISCRIMINATED: AcquisitionMode
CONDITION_OP_UNSPECIFIED: ConditionOp
CONDITION_OP_EQUAL: ConditionOp
CONDITION_OP_NOT_EQUAL: ConditionOp
CONDITION_OP_MASK_AND: ConditionOp
CONDITION_OP_MASK_OR: ConditionOp
CONDITION_OP_MASK_XOR: ConditionOp

class Waveform(_message.Message):
    __slots__ = ("shape", "samples", "length_samples", "sigma_samples", "drag_beta_samples", "rise_fall_samples")
    SHAPE_FIELD_NUMBER: _ClassVar[int]
    SAMPLES_FIELD_NUMBER: _ClassVar[int]
    LENGTH_SAMPLES_FIELD_NUMBER: _ClassVar[int]
    SIGMA_SAMPLES_FIELD_NUMBER: _ClassVar[int]
    DRAG_BETA_SAMPLES_FIELD_NUMBER: _ClassVar[int]
    RISE_FALL_SAMPLES_FIELD_NUMBER: _ClassVar[int]
    shape: WaveformShape
    samples: _common_pb2.NdArray
    length_samples: int
    sigma_samples: float
    drag_beta_samples: float
    rise_fall_samples: int
    def __init__(self, shape: _Optional[_Union[WaveformShape, str]] = ..., samples: _Optional[_Union[_common_pb2.NdArray, _Mapping]] = ..., length_samples: _Optional[int] = ..., sigma_samples: _Optional[float] = ..., drag_beta_samples: _Optional[float] = ..., rise_fall_samples: _Optional[int] = ...) -> None: ...

class Play(_message.Message):
    __slots__ = ("channel_id", "waveform_id", "amplitude", "phase_offset_rad", "duration_ticks")
    CHANNEL_ID_FIELD_NUMBER: _ClassVar[int]
    WAVEFORM_ID_FIELD_NUMBER: _ClassVar[int]
    AMPLITUDE_FIELD_NUMBER: _ClassVar[int]
    PHASE_OFFSET_RAD_FIELD_NUMBER: _ClassVar[int]
    DURATION_TICKS_FIELD_NUMBER: _ClassVar[int]
    channel_id: str
    waveform_id: str
    amplitude: float
    phase_offset_rad: float
    duration_ticks: int
    def __init__(self, channel_id: _Optional[str] = ..., waveform_id: _Optional[str] = ..., amplitude: _Optional[float] = ..., phase_offset_rad: _Optional[float] = ..., duration_ticks: _Optional[int] = ...) -> None: ...

class Wait(_message.Message):
    __slots__ = ("duration_ticks",)
    DURATION_TICKS_FIELD_NUMBER: _ClassVar[int]
    duration_ticks: int
    def __init__(self, duration_ticks: _Optional[int] = ...) -> None: ...

class ShiftPhase(_message.Message):
    __slots__ = ("frame_id", "delta_rad")
    FRAME_ID_FIELD_NUMBER: _ClassVar[int]
    DELTA_RAD_FIELD_NUMBER: _ClassVar[int]
    frame_id: str
    delta_rad: float
    def __init__(self, frame_id: _Optional[str] = ..., delta_rad: _Optional[float] = ...) -> None: ...

class SetPhase(_message.Message):
    __slots__ = ("frame_id", "phase_rad")
    FRAME_ID_FIELD_NUMBER: _ClassVar[int]
    PHASE_RAD_FIELD_NUMBER: _ClassVar[int]
    frame_id: str
    phase_rad: float
    def __init__(self, frame_id: _Optional[str] = ..., phase_rad: _Optional[float] = ...) -> None: ...

class ResetPhase(_message.Message):
    __slots__ = ("frame_id",)
    FRAME_ID_FIELD_NUMBER: _ClassVar[int]
    frame_id: str
    def __init__(self, frame_id: _Optional[str] = ...) -> None: ...

class SetFrequency(_message.Message):
    __slots__ = ("frame_id", "frequency_hz")
    FRAME_ID_FIELD_NUMBER: _ClassVar[int]
    FREQUENCY_HZ_FIELD_NUMBER: _ClassVar[int]
    frame_id: str
    frequency_hz: float
    def __init__(self, frame_id: _Optional[str] = ..., frequency_hz: _Optional[float] = ...) -> None: ...

class Acquire(_message.Message):
    __slots__ = ("channel_id", "integration_ticks", "mode", "weights_id", "register_index", "result_key")
    CHANNEL_ID_FIELD_NUMBER: _ClassVar[int]
    INTEGRATION_TICKS_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    WEIGHTS_ID_FIELD_NUMBER: _ClassVar[int]
    REGISTER_INDEX_FIELD_NUMBER: _ClassVar[int]
    RESULT_KEY_FIELD_NUMBER: _ClassVar[int]
    channel_id: str
    integration_ticks: int
    mode: AcquisitionMode
    weights_id: str
    register_index: int
    result_key: str
    def __init__(self, channel_id: _Optional[str] = ..., integration_ticks: _Optional[int] = ..., mode: _Optional[_Union[AcquisitionMode, str]] = ..., weights_id: _Optional[str] = ..., register_index: _Optional[int] = ..., result_key: _Optional[str] = ...) -> None: ...

class Condition(_message.Message):
    __slots__ = ("op", "register_indices", "value", "mask")
    OP_FIELD_NUMBER: _ClassVar[int]
    REGISTER_INDICES_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    MASK_FIELD_NUMBER: _ClassVar[int]
    op: ConditionOp
    register_indices: _containers.RepeatedScalarFieldContainer[int]
    value: int
    mask: int
    def __init__(self, op: _Optional[_Union[ConditionOp, str]] = ..., register_indices: _Optional[_Iterable[int]] = ..., value: _Optional[int] = ..., mask: _Optional[int] = ...) -> None: ...

class Block(_message.Message):
    __slots__ = ("instructions",)
    INSTRUCTIONS_FIELD_NUMBER: _ClassVar[int]
    instructions: _containers.RepeatedCompositeFieldContainer[Instruction]
    def __init__(self, instructions: _Optional[_Iterable[_Union[Instruction, _Mapping]]] = ...) -> None: ...

class Branch(_message.Message):
    __slots__ = ("condition", "then_block", "else_block", "duration_ticks", "sequencer_id")
    CONDITION_FIELD_NUMBER: _ClassVar[int]
    THEN_BLOCK_FIELD_NUMBER: _ClassVar[int]
    ELSE_BLOCK_FIELD_NUMBER: _ClassVar[int]
    DURATION_TICKS_FIELD_NUMBER: _ClassVar[int]
    SEQUENCER_ID_FIELD_NUMBER: _ClassVar[int]
    condition: Condition
    then_block: Block
    else_block: Block
    duration_ticks: int
    sequencer_id: str
    def __init__(self, condition: _Optional[_Union[Condition, _Mapping]] = ..., then_block: _Optional[_Union[Block, _Mapping]] = ..., else_block: _Optional[_Union[Block, _Mapping]] = ..., duration_ticks: _Optional[int] = ..., sequencer_id: _Optional[str] = ...) -> None: ...

class Instruction(_message.Message):
    __slots__ = ("start_tick", "play", "wait", "shift_phase", "set_phase", "reset_phase", "set_frequency", "acquire", "branch")
    START_TICK_FIELD_NUMBER: _ClassVar[int]
    PLAY_FIELD_NUMBER: _ClassVar[int]
    WAIT_FIELD_NUMBER: _ClassVar[int]
    SHIFT_PHASE_FIELD_NUMBER: _ClassVar[int]
    SET_PHASE_FIELD_NUMBER: _ClassVar[int]
    RESET_PHASE_FIELD_NUMBER: _ClassVar[int]
    SET_FREQUENCY_FIELD_NUMBER: _ClassVar[int]
    ACQUIRE_FIELD_NUMBER: _ClassVar[int]
    BRANCH_FIELD_NUMBER: _ClassVar[int]
    start_tick: int
    play: Play
    wait: Wait
    shift_phase: ShiftPhase
    set_phase: SetPhase
    reset_phase: ResetPhase
    set_frequency: SetFrequency
    acquire: Acquire
    branch: Branch
    def __init__(self, start_tick: _Optional[int] = ..., play: _Optional[_Union[Play, _Mapping]] = ..., wait: _Optional[_Union[Wait, _Mapping]] = ..., shift_phase: _Optional[_Union[ShiftPhase, _Mapping]] = ..., set_phase: _Optional[_Union[SetPhase, _Mapping]] = ..., reset_phase: _Optional[_Union[ResetPhase, _Mapping]] = ..., set_frequency: _Optional[_Union[SetFrequency, _Mapping]] = ..., acquire: _Optional[_Union[Acquire, _Mapping]] = ..., branch: _Optional[_Union[Branch, _Mapping]] = ...) -> None: ...

class AmplitudeTarget(_message.Message):
    __slots__ = ("instruction_index",)
    INSTRUCTION_INDEX_FIELD_NUMBER: _ClassVar[int]
    instruction_index: int
    def __init__(self, instruction_index: _Optional[int] = ...) -> None: ...

class FrequencyTarget(_message.Message):
    __slots__ = ("frame_id",)
    FRAME_ID_FIELD_NUMBER: _ClassVar[int]
    frame_id: str
    def __init__(self, frame_id: _Optional[str] = ...) -> None: ...

class DurationTarget(_message.Message):
    __slots__ = ("waveform_id",)
    WAVEFORM_ID_FIELD_NUMBER: _ClassVar[int]
    waveform_id: str
    def __init__(self, waveform_id: _Optional[str] = ...) -> None: ...

class Sweep(_message.Message):
    __slots__ = ("axis", "amplitude", "frequency", "duration", "values")
    AXIS_FIELD_NUMBER: _ClassVar[int]
    AMPLITUDE_FIELD_NUMBER: _ClassVar[int]
    FREQUENCY_FIELD_NUMBER: _ClassVar[int]
    DURATION_FIELD_NUMBER: _ClassVar[int]
    VALUES_FIELD_NUMBER: _ClassVar[int]
    axis: int
    amplitude: AmplitudeTarget
    frequency: FrequencyTarget
    duration: DurationTarget
    values: _common_pb2.NdArray
    def __init__(self, axis: _Optional[int] = ..., amplitude: _Optional[_Union[AmplitudeTarget, _Mapping]] = ..., frequency: _Optional[_Union[FrequencyTarget, _Mapping]] = ..., duration: _Optional[_Union[DurationTarget, _Mapping]] = ..., values: _Optional[_Union[_common_pb2.NdArray, _Mapping]] = ...) -> None: ...

class IntegrationWeights(_message.Message):
    __slots__ = ("weights",)
    WEIGHTS_FIELD_NUMBER: _ClassVar[int]
    weights: _common_pb2.NdArray
    def __init__(self, weights: _Optional[_Union[_common_pb2.NdArray, _Mapping]] = ...) -> None: ...

class Job(_message.Message):
    __slots__ = ("job_key", "waveform_library", "weight_library", "main", "sweeps", "num_shots", "repetition_delay_ticks", "priority", "requested_tier", "random_seed", "expected_calibration_epoch")
    class WaveformLibraryEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: Waveform
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[Waveform, _Mapping]] = ...) -> None: ...
    class WeightLibraryEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: IntegrationWeights
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[IntegrationWeights, _Mapping]] = ...) -> None: ...
    JOB_KEY_FIELD_NUMBER: _ClassVar[int]
    WAVEFORM_LIBRARY_FIELD_NUMBER: _ClassVar[int]
    WEIGHT_LIBRARY_FIELD_NUMBER: _ClassVar[int]
    MAIN_FIELD_NUMBER: _ClassVar[int]
    SWEEPS_FIELD_NUMBER: _ClassVar[int]
    NUM_SHOTS_FIELD_NUMBER: _ClassVar[int]
    REPETITION_DELAY_TICKS_FIELD_NUMBER: _ClassVar[int]
    PRIORITY_FIELD_NUMBER: _ClassVar[int]
    REQUESTED_TIER_FIELD_NUMBER: _ClassVar[int]
    RANDOM_SEED_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_CALIBRATION_EPOCH_FIELD_NUMBER: _ClassVar[int]
    job_key: str
    waveform_library: _containers.MessageMap[str, Waveform]
    weight_library: _containers.MessageMap[str, IntegrationWeights]
    main: Block
    sweeps: _containers.RepeatedCompositeFieldContainer[Sweep]
    num_shots: int
    repetition_delay_ticks: int
    priority: int
    requested_tier: FidelityTier
    random_seed: int
    expected_calibration_epoch: int
    def __init__(self, job_key: _Optional[str] = ..., waveform_library: _Optional[_Mapping[str, Waveform]] = ..., weight_library: _Optional[_Mapping[str, IntegrationWeights]] = ..., main: _Optional[_Union[Block, _Mapping]] = ..., sweeps: _Optional[_Iterable[_Union[Sweep, _Mapping]]] = ..., num_shots: _Optional[int] = ..., repetition_delay_ticks: _Optional[int] = ..., priority: _Optional[int] = ..., requested_tier: _Optional[_Union[FidelityTier, str]] = ..., random_seed: _Optional[int] = ..., expected_calibration_epoch: _Optional[int] = ...) -> None: ...
