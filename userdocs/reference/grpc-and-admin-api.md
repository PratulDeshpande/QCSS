# gRPC and admin API reference

Wire contract, read from `proto/qcss/v1/*.proto` and `proto/qcss/admin/v1/admin.proto`. Server behaviour (status codes, limits) from `src/qcss/adapters/` and `src/qcss/runtime/`. Generated code lives in `src/qcss/v1` and `src/qcss/admin/v1` (committed). The proto files are the source of truth; this page is a summary.

## Conventions
- Packages `qcss.v1` (instrument link) and `qcss.admin.v1` (admin channel). Every enum has `*_UNSPECIFIED = 0`.
- Time is an integer count of ticks of the instrument clock (`DeviceDescription.tick_hz`, a decimal string).
- Arrays: `NdArray{element_type, shape, data}`: little-endian, C-order raw bytes. Element types: FLOAT32, FLOAT64, COMPLEX64, COMPLEX128, INT8, UINT8, INT32, UINT64.
- Message size cap 16 MiB each way. Results are streamed in chunks of at most 1024 shots (`CHUNK_SHOTS`, `qcss.core.seeding`).
- Auth: `authorization: Bearer <token>` metadata when the server has a token; the `grpc.health.v1.Health` service is exempt. Wrong or missing token gives `UNAUTHENTICATED` ("missing or invalid bearer token").
- Reflection is off unless `qcss serve --debug-reflection`.
- Metadata `x-quark-job-id` and `traceparent` are logged by the server when present.

## `qcss.v1.ControlService` (instrument link)

| RPC | Request -> response | Status codes raised by the server |
|---|---|---|
| `SubmitJob` | `SubmitJobRequest{job}` -> `SubmitJobResponse{job_id, calibration_epoch}` | `INVALID_ARGUMENT` (hardware-rule violations, with `BadRequest.FieldViolation` per field path); `FAILED_PRECONDITION` with `PreconditionFailure` type `CALIBRATION_EPOCH` (subject `job.expected_calibration_epoch`), `FIDELITY_TIER` (subject `job.requested_tier`, only when diagnostics are exposed) or `INSTRUMENT_RESOURCES` (what a lab chassis says instead: "the sequence exceeds the instrument's resources") |
| `GetJobStatus` | `{job_id}` -> `{status: JobStatus}` | `NOT_FOUND` (unknown or evicted job) |
| `CancelJob` | `{job_id}` -> `{status}` | `NOT_FOUND` |
| `StreamResults` (server-streaming) | `{job_id, resume_after_sequence}` -> stream of `{chunk: ResultChunk}` | `NOT_FOUND`; `OUT_OF_RANGE` when the requested chunks were already evicted |
| `GetCalibration` | `{qubit_indices[]}` -> `{snapshot}` | none |
| `UpdateCalibration` | `{snapshot, expected_epoch}` -> `{new_epoch}` (compare-and-swap) | `FAILED_PRECONDITION`, type `CALIBRATION_EPOCH`, subject `expected_epoch` |
| `DescribeDevice` | `{}` -> `{device: DeviceDescription}` | none |
| `GetDeviceProperties` | `{}` -> `{properties: DeviceProperties}` | `UNIMPLEMENTED` when the server has no properties provider (the README says a lab chassis does not serve it) |

Other codes: `UNAVAILABLE` from an injected instrument fault (`InstrumentFaultInterceptor`); `QcssClient` retries `UNAVAILABLE` a bounded number of reconnects.

Retention (`JobManager` defaults): 256 finished jobs, 256 MiB of results per job.

### Job (`job.proto`)

| Field | Type | Notes |
|---|---|---|
| `job_key` | string | client label |
| `waveform_library` | map<string, Waveform> | |
| `weight_library` | map<string, IntegrationWeights> | |
| `main` | Block | instructions |
| `sweeps` | repeated Sweep | exclusive with `program_points` |
| `num_shots` | uint32 | |
| `repetition_delay_ticks` | optional uint64 | unset: wait 10 x T1 (README) |
| `priority` | optional int32 | |
| `requested_tier` | FidelityTier | ignored by a lab chassis (the operator picks, `--tier`) |
| `random_seed` | optional uint64 | honoured only with `--deterministic` (or `qcss run`) |
| `expected_calibration_epoch` | optional uint64 | pins the job to a calibration; stale at start gives job `REJECTED` |
| `program_points` | repeated ProgramPoint{indices, main} | client-resolved sweep; `main` is then ignored |

Instruction ops (`Instruction{start_tick, oneof op}`): `Play{channel_id, waveform_id, amplitude, phase_offset_rad, duration_ticks?}`, `Wait`, `ShiftPhase`, `SetPhase`, `ResetPhase`, `SetFrequency{frame_id, frequency_hz}`, `Acquire{channel_id, integration_ticks, mode, weights_id, register_index, result_key}`, `Branch{condition, then_block, else_block, duration_ticks, sequencer_id}`. `Condition{op, register_indices, value, mask}`. Sweeps: `Sweep{axis, target: AmplitudeTarget|FrequencyTarget|DurationTarget, values}`.

Enums:
- `FidelityTier`: UNSPECIFIED (treated as AUTO), AUTO, T0_SURROGATE, T1A_STABILIZER, T1B_STATEVECTOR, T2_LINDBLAD, T3_TRAJECTORY (not built; refused).
- `WaveformShape`: UNSPECIFIED (rejected `INVALID_ARGUMENT`), ARBITRARY, GAUSSIAN, DRAG, SQUARE, COSINE_FLATTOP.
- `AcquisitionMode`: RAW_TRACE, INTEGRATED, DISCRIMINATED.
- `ConditionOp`: EQUAL, NOT_EQUAL, MASK_AND, MASK_OR, MASK_XOR.

### Job status and results (`result.proto`)

`JobStatus{job_id, state, progress, message, submitted_at, started_at, finished_at, tier_used, noise_fidelity}`. A lab chassis does not fill `tier_used` / `noise_fidelity`.

| `JobState` | Set by `runtime/jobs.py` | Meaning |
|---|---|---|
| `QUEUED` | at submit | waiting; the chassis runs one job at a time |
| `VALIDATING` | not set anywhere in `src/` (grep) | defined in the proto only |
| `RUNNING` | at execution start | |
| `COMPLETED` | normal end | |
| `FAILED` | execution error, or `abort_all` after a reboot fault | message is the reason; a lab chassis says "execution failed: instrument fault" |
| `CANCELLED` | `CancelJob` | "cancelled before start" if still queued |
| `REJECTED` | stale calibration epoch at execution start | message `CALIBRATION_EPOCH: ...` |

`NoiseFidelity`: PHYSICAL (T1b exact, T2, T3), TWIRLED (T1a), SURROGATE (T0).

`ResultChunk{job_id, sequence_number (from 1), sweep_point[], shot_offset, num_shots_in_chunk, acquisitions[], calibration_epoch, is_last, warnings[]}`; `AcquisitionResult{result_key, iq, states, shot_end_ticks}`.

### Calibration (`calibration.proto`)

`CalibrationSnapshot{calibration_epoch, qubits[]}`; `QubitCalibration{qubit_index, drive_frequency_hz, readout_frequency_hz, pi_amplitude, pi_length_samples, drag_beta_samples, readout_delay_ticks, readout_rotation_rad, readout_threshold, drive_mixer, readout_mixer, flux_predistortion}`; `MixerCorrection{dc_offset_i, dc_offset_q, gain_ratio, phase_skew_rad}`; `FluxPredistortion{inverse_highpass_tau_s?, exponential[ExponentialStage{tau_s, amplitude, enabled}], fir_coefficients[]}`. A written qubit replaces the stored one wholesale (CHANGELOG).

### Device (`device.proto`)

`DeviceDescription{profile_name, vendor, tick_hz, channels[], max_discriminated_states, default_repetition_delay_ticks}`; `ChannelInfo{channel_id, kind, generator_id, port_id, frame_id, qubits[], sample_rate_hz, lo_frequency_hz}`; `ChannelKind`: DRIVE, FLUX, READOUT, CROSS_RESONANCE. `DeviceProperties{measured_at, source, calibration_epoch, qubits[QubitProperties], pairs[PairProperties]}` (source is `"device-model"` for QCSS).

## `qcss.admin.v1.AdminService` (admin channel)

Own address (`qcss serve --admin-listen`) and own token. Never served on the lab link.

| RPC | Request fields | Effect |
|---|---|---|
| `KillQubit` / `ReviveQubit` | `qubit_index` | lose / restore a qubit |
| `DriftStep` | `qubit_index, delta_frequency_hz, t1_factor` (0 = unchanged) | step frequency and/or T1 (accumulates) |
| `TlsCollision` | `qubit_index, coupling_hz, linewidth_hz, detuning_hz` (0 = defaults 0.5 MHz, 1 MHz) | a TLS defect drifts into resonance |
| `Burst` | `qubit_index, peak_gamma_per_s` (0 = default 2 per microsecond) | cosmic-ray burst now |
| `FreezeDrift` | `frozen` | stop/resume drift of the whole chip |
| `ClearScenarios` | | remove every scenario |
| `GetMode` / `SetMode` | `Mode{time_scale, deterministic, tier_policy}`; `GetModeResponse` adds `global_seed` | `time_scale` lab s per wall s (0 = frozen chip, unpaced); `deterministic` honours `Job.random_seed`; `tier_policy` UNSPECIFIED honours each job |
| `ReadTruth` | | `lab_time_s`, `QubitTruth{qubit_index, frequency_hz, t1_s, dead}[]`, full `DeviceProperties` |
| `InspectJob` | `job_id` | `tier_used, noise_fidelity, calibration_epoch, warnings[]` |
| `InjectInstrumentFault` | `fault, count, duration_s` | `HANG` (next `count` calls stall `duration_s`), `DROP` (next `count` fail as a dropped connection), `REBOOT` (running jobs fail; every call fails for `duration_s`), `SLOW_UPLOAD` (next `count` submissions take `duration_s` longer) |
| `ClearInstrumentFaults` | | clear pending faults |

Admin status codes (`admin_server.py`): `FAILED_PRECONDITION` (chassis runs without a device file), `NOT_FOUND` (unknown qubit or job), `INVALID_ARGUMENT` (for example `time_scale must be >= 0`, unknown tier, bad scenario arguments).

## Protobuf rules (CONTRIBUTING.md)
`buf lint` (STANDARD) clean; no wire-breaking change (`buf breaking`, WIRE_JSON). Config: `buf.yaml`.

Sources: proto/qcss/v1/{control_service,job,result,calibration,device,common}.proto, proto/qcss/admin/v1/admin.proto, src/qcss/adapters/{grpc_server,admin_server,errors,instrument_faults}.py, src/qcss/runtime/jobs.py, src/qcss/core/errors.py, README.md, docs/control-stack-protocol.md, CONTRIBUTING.md.
