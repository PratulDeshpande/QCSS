# CLI reference
Generated from `--help` output by a script (not part of the repo). Regenerate after CLI changes (script: scratchpad `gen_cli.py`, runs every `--help` recursively at COLUMNS=100).

Notes: `qcss` is the console script of the root package (`qcss.cli:app`). `qcss-dashboard` is the console script of `integrations/qcss_dashboard` (`qcss_dashboard.cli:main`); it was not installed on the generating machine, so its help was captured by importing that module from source. Tokens are never CLI flags for the dashboard: it reads `QCSS_TOKEN`, `QCSS_ADMIN_TOKEN` and `QCSS_DASHBOARD_TOKEN` from the environment (see environment-and-ports.md).

## `qcss`

```text
Usage: qcss [OPTIONS] COMMAND [ARGS]...

  QCSS: Hardware-in-the-loop Quantum Control Stack Simulator.

Options:
  --version  Show the version and exit.
  --help     Show this message and exit.

Commands:
  admin       Operate the simulated lab through its admin channel...
  device      Inspect and manage device specifications.
  profile     Inspect and manage hardware profiles.
  remote      Talk to a running QCSS server (this machine or another one...
  run         Run a quantum control job on the simulator.
  serve       Run the simulated instrument (the chassis): the instrument...
  technician  The lab's calibration staff: Qibocal runs on a schedule and...
  validate    Validate a job schedule against hardware constraints...
```

## `qcss admin`

```text
Usage: qcss admin [OPTIONS] COMMAND [ARGS]...

  Operate the simulated lab through its admin channel (scenarios, modes,
  truth, instrument faults).

Options:
  --help  Show this message and exit.

Commands:
  burst         A cosmic-ray hit centred on the qubit, now.
  clear         Remove every scenario (kills, drift steps, defects, bursts).
  clear-faults  Remove every pending instrument fault.
  drift         Step a qubit's frequency and/or T1 (accumulates).
  fault         Make the instrument misbehave: hang or drop calls,...
  freeze        Stop (or resume) drift of the whole chip.
  inspect       How the simulator ran a job (tier, noise fidelity,...
  kill          Lose a qubit: it decays within ~100 ns and moves 200 MHz...
  mode          Show how the chassis runs; with options, change it.
  revive        Undo `kill`.
  tls           A TLS defect drifts into resonance with the qubit.
  truth         The chip as it really is now (only the simulator knows...
```

## `qcss admin burst`

```text
Usage: qcss admin burst [OPTIONS] QUBIT

  A cosmic-ray hit centred on the qubit, now.

Options:
  --peak-gamma-per-s FLOAT  Peak extra decay rate (default 2 per us)
  --timeout FLOAT           Per-call timeout, s  [default: 30.0]
  --insecure                Allow sending the token without TLS to a non-
                            loopback address (trusted networks only)
  --token TEXT              Admin token (env QCSS_ADMIN_TOKEN)
  --ca FILE                 PEM certificate to trust; enables TLS
  -t, --target TEXT         host:port of the admin channel  [default:
                            127.0.0.1:50052]
  --help                    Show this message and exit.
```

## `qcss admin clear`

```text
Usage: qcss admin clear [OPTIONS]

  Remove every scenario (kills, drift steps, defects, bursts).

Options:
  --timeout FLOAT    Per-call timeout, s  [default: 30.0]
  --insecure         Allow sending the token without TLS to a non-loopback
                     address (trusted networks only)
  --token TEXT       Admin token (env QCSS_ADMIN_TOKEN)
  --ca FILE          PEM certificate to trust; enables TLS
  -t, --target TEXT  host:port of the admin channel  [default:
                     127.0.0.1:50052]
  --help             Show this message and exit.
```

## `qcss admin clear-faults`

```text
Usage: qcss admin clear-faults [OPTIONS]

  Remove every pending instrument fault.

Options:
  --timeout FLOAT    Per-call timeout, s  [default: 30.0]
  --insecure         Allow sending the token without TLS to a non-loopback
                     address (trusted networks only)
  --token TEXT       Admin token (env QCSS_ADMIN_TOKEN)
  --ca FILE          PEM certificate to trust; enables TLS
  -t, --target TEXT  host:port of the admin channel  [default:
                     127.0.0.1:50052]
  --help             Show this message and exit.
```

## `qcss admin drift`

```text
Usage: qcss admin drift [OPTIONS] QUBIT

  Step a qubit's frequency and/or T1 (accumulates).

Options:
  --df-hz FLOAT            Frequency jump, Hz
  --t1-factor FLOAT RANGE  Multiply T1 by this  [x>0]
  --timeout FLOAT          Per-call timeout, s  [default: 30.0]
  --insecure               Allow sending the token without TLS to a non-
                           loopback address (trusted networks only)
  --token TEXT             Admin token (env QCSS_ADMIN_TOKEN)
  --ca FILE                PEM certificate to trust; enables TLS
  -t, --target TEXT        host:port of the admin channel  [default:
                           127.0.0.1:50052]
  --help                   Show this message and exit.
```

## `qcss admin fault`

```text
Usage: qcss admin fault [OPTIONS] {hang|drop|reboot|slow-upload}

  Make the instrument misbehave: hang or drop calls, reboot, or upload slowly.

Options:
  --count INTEGER RANGE   Calls affected  [default: 1; x>=1]
  --duration FLOAT RANGE  Seconds (required for hang, reboot and slow-upload)
                          [x>=0]
  --timeout FLOAT         Per-call timeout, s  [default: 30.0]
  --insecure              Allow sending the token without TLS to a non-
                          loopback address (trusted networks only)
  --token TEXT            Admin token (env QCSS_ADMIN_TOKEN)
  --ca FILE               PEM certificate to trust; enables TLS
  -t, --target TEXT       host:port of the admin channel  [default:
                          127.0.0.1:50052]
  --help                  Show this message and exit.
```

## `qcss admin freeze`

```text
Usage: qcss admin freeze [OPTIONS]

  Stop (or resume) drift of the whole chip.

Options:
  --off              Let the chip drift again
  --timeout FLOAT    Per-call timeout, s  [default: 30.0]
  --insecure         Allow sending the token without TLS to a non-loopback
                     address (trusted networks only)
  --token TEXT       Admin token (env QCSS_ADMIN_TOKEN)
  --ca FILE          PEM certificate to trust; enables TLS
  -t, --target TEXT  host:port of the admin channel  [default:
                     127.0.0.1:50052]
  --help             Show this message and exit.
```

## `qcss admin inspect`

```text
Usage: qcss admin inspect [OPTIONS] JOB_ID

  How the simulator ran a job (tier, noise fidelity, calibration epoch).

Options:
  --timeout FLOAT    Per-call timeout, s  [default: 30.0]
  --insecure         Allow sending the token without TLS to a non-loopback
                     address (trusted networks only)
  --token TEXT       Admin token (env QCSS_ADMIN_TOKEN)
  --ca FILE          PEM certificate to trust; enables TLS
  -t, --target TEXT  host:port of the admin channel  [default:
                     127.0.0.1:50052]
  --help             Show this message and exit.
```

## `qcss admin kill`

```text
Usage: qcss admin kill [OPTIONS] QUBIT

  Lose a qubit: it decays within ~100 ns and moves 200 MHz off where it was
  calibrated.

Options:
  --timeout FLOAT    Per-call timeout, s  [default: 30.0]
  --insecure         Allow sending the token without TLS to a non-loopback
                     address (trusted networks only)
  --token TEXT       Admin token (env QCSS_ADMIN_TOKEN)
  --ca FILE          PEM certificate to trust; enables TLS
  -t, --target TEXT  host:port of the admin channel  [default:
                     127.0.0.1:50052]
  --help             Show this message and exit.
```

## `qcss admin mode`

```text
Usage: qcss admin mode [OPTIONS]

  Show how the chassis runs; with options, change it.

Options:
  --time-scale FLOAT RANGE        Lab seconds per wall second  [x>=0]
  --deterministic / --realistic   Replay job seeds (CI) or not (lab)
  --tier [requested|auto|t0|t1a|t1b|t2]
                                  Physics tier for every job ('requested'
                                  honours each job's own)
  --timeout FLOAT                 Per-call timeout, s  [default: 30.0]
  --insecure                      Allow sending the token without TLS to a
                                  non-loopback address (trusted networks only)
  --token TEXT                    Admin token (env QCSS_ADMIN_TOKEN)
  --ca FILE                       PEM certificate to trust; enables TLS
  -t, --target TEXT               host:port of the admin channel  [default:
                                  127.0.0.1:50052]
  --help                          Show this message and exit.
```

## `qcss admin revive`

```text
Usage: qcss admin revive [OPTIONS] QUBIT

  Undo `kill`.

Options:
  --timeout FLOAT    Per-call timeout, s  [default: 30.0]
  --insecure         Allow sending the token without TLS to a non-loopback
                     address (trusted networks only)
  --token TEXT       Admin token (env QCSS_ADMIN_TOKEN)
  --ca FILE          PEM certificate to trust; enables TLS
  -t, --target TEXT  host:port of the admin channel  [default:
                     127.0.0.1:50052]
  --help             Show this message and exit.
```

## `qcss admin tls`

```text
Usage: qcss admin tls [OPTIONS] QUBIT

  A TLS defect drifts into resonance with the qubit.

Options:
  --coupling-hz FLOAT   Defect coupling (default 0.5 MHz)
  --linewidth-hz FLOAT  Defect linewidth (default 1 MHz)
  --detuning-hz FLOAT   Defect detuning from the qubit
  --timeout FLOAT       Per-call timeout, s  [default: 30.0]
  --insecure            Allow sending the token without TLS to a non-loopback
                        address (trusted networks only)
  --token TEXT          Admin token (env QCSS_ADMIN_TOKEN)
  --ca FILE             PEM certificate to trust; enables TLS
  -t, --target TEXT     host:port of the admin channel  [default:
                        127.0.0.1:50052]
  --help                Show this message and exit.
```

## `qcss admin truth`

```text
Usage: qcss admin truth [OPTIONS]

  The chip as it really is now (only the simulator knows this).

Options:
  --timeout FLOAT    Per-call timeout, s  [default: 30.0]
  --insecure         Allow sending the token without TLS to a non-loopback
                     address (trusted networks only)
  --token TEXT       Admin token (env QCSS_ADMIN_TOKEN)
  --ca FILE          PEM certificate to trust; enables TLS
  -t, --target TEXT  host:port of the admin channel  [default:
                     127.0.0.1:50052]
  --help             Show this message and exit.
```

## `qcss device`

```text
Usage: qcss device [OPTIONS] COMMAND [ARGS]...

  Inspect and manage device specifications.

Options:
  --help  Show this message and exit.

Commands:
  show  Show details of a device physics specification.
```

## `qcss device show`

```text
Usage: qcss device show [OPTIONS] PATH_OR_NAME

  Show details of a device physics specification.

Options:
  --help  Show this message and exit.
```

## `qcss profile`

```text
Usage: qcss profile [OPTIONS] COMMAND [ARGS]...

  Inspect and manage hardware profiles.

Options:
  --help  Show this message and exit.

Commands:
  list  List available built-in hardware profiles.
  show  Show details of a hardware profile.
```

## `qcss profile list`

```text
Usage: qcss profile list [OPTIONS]

  List available built-in hardware profiles.

Options:
  --help  Show this message and exit.
```

## `qcss profile show`

```text
Usage: qcss profile show [OPTIONS] NAME_OR_PATH

  Show details of a hardware profile.

Options:
  --help  Show this message and exit.
```

## `qcss remote`

```text
Usage: qcss remote [OPTIONS] COMMAND [ARGS]...

  Talk to a running QCSS server (this machine or another one on the network).

Options:
  --help  Show this message and exit.

Commands:
  calibration  Print the current calibration snapshot and its epoch as JSON.
  describe     Show the instrument profile and the channels the server...
  ping         Check that the server is reachable and healthy (gRPC...
  properties   Show T1, T2*, readout and gate errors per qubit and pair.
  run          Submit a job, wait for it, stream the results and print...
```

## `qcss remote calibration`

```text
Usage: qcss remote calibration [OPTIONS]

  Print the current calibration snapshot and its epoch as JSON.

Options:
  --timeout FLOAT      Per-call timeout, s  [default: 30.0]
  --insecure           Allow sending the token without TLS to a non-loopback
                       address (trusted networks only)
  --token TEXT         Bearer token (env QCSS_TOKEN)
  --ca FILE            PEM certificate to trust (the server's self-signed cert
                       or its CA); enables TLS
  -t, --target TEXT    host:port of the server  [default: 127.0.0.1:50051]
  -q, --qubit INTEGER  Only these qubits (repeatable)
  --help               Show this message and exit.
```

## `qcss remote describe`

```text
Usage: qcss remote describe [OPTIONS]

  Show the instrument profile and the channels the server offers.

Options:
  --timeout FLOAT    Per-call timeout, s  [default: 30.0]
  --insecure         Allow sending the token without TLS to a non-loopback
                     address (trusted networks only)
  --token TEXT       Bearer token (env QCSS_TOKEN)
  --ca FILE          PEM certificate to trust (the server's self-signed cert
                     or its CA); enables TLS
  -t, --target TEXT  host:port of the server  [default: 127.0.0.1:50051]
  --help             Show this message and exit.
```

## `qcss remote ping`

```text
Usage: qcss remote ping [OPTIONS]

  Check that the server is reachable and healthy (gRPC health check).

Options:
  --timeout FLOAT    Per-call timeout, s  [default: 30.0]
  --insecure         Allow sending the token without TLS to a non-loopback
                     address (trusted networks only)
  --token TEXT       Bearer token (env QCSS_TOKEN)
  --ca FILE          PEM certificate to trust (the server's self-signed cert
                     or its CA); enables TLS
  -t, --target TEXT  host:port of the server  [default: 127.0.0.1:50051]
  --help             Show this message and exit.
```

## `qcss remote properties`

```text
Usage: qcss remote properties [OPTIONS]

  Show T1, T2*, readout and gate errors per qubit and pair.

Options:
  --timeout FLOAT    Per-call timeout, s  [default: 30.0]
  --insecure         Allow sending the token without TLS to a non-loopback
                     address (trusted networks only)
  --token TEXT       Bearer token (env QCSS_TOKEN)
  --ca FILE          PEM certificate to trust (the server's self-signed cert
                     or its CA); enables TLS
  -t, --target TEXT  host:port of the server  [default: 127.0.0.1:50051]
  --help             Show this message and exit.
```

## `qcss remote run`

```text
Usage: qcss remote run [OPTIONS] JOB_PATH

  Submit a job, wait for it, stream the results and print the readout counts.

Options:
  --timeout FLOAT      Per-call timeout, s  [default: 30.0]
  --insecure           Allow sending the token without TLS to a non-loopback
                       address (trusted networks only)
  --token TEXT         Bearer token (env QCSS_TOKEN)
  --ca FILE            PEM certificate to trust (the server's self-signed cert
                       or its CA); enables TLS
  -t, --target TEXT    host:port of the server  [default: 127.0.0.1:50051]
  -s, --shots INTEGER  Override num_shots
  -o, --output FILE    Save results as JSON
  --help               Show this message and exit.
```

## `qcss run`

```text
Usage: qcss run [OPTIONS] JOB_PATH

  Run a quantum control job on the simulator.

Options:
  -p, --profile TEXT              Hardware profile name or path
  -d, --device TEXT               Device specification path or name
  -s, --shots INTEGER             Override number of shots
  -t, --tier [T0|T1A|T1B|T2|T3|AUTO]
                                  Override simulation fidelity tier
  -c, --chunk-size INTEGER        Chunk size in shots (part of the seed key)
  -o, --output PATH               Output JSON results file
  --help                          Show this message and exit.
```

## `qcss serve`

```text
Usage: qcss serve [OPTIONS]

  Run the simulated instrument (the chassis): the instrument link, and
  optionally the admin link.

Options:
  -h, --host TEXT                 gRPC host bind address (a network bind needs
                                  TLS and --token)
  -p, --port INTEGER              gRPC port
  --listen TEXT                   Full address instead of host:port, e.g.
                                  unix:C:/Users/me/qcss.sock
  --profile TEXT                  Hardware profile name or path
  --device TEXT                   Device specification path or name
  --workers INTEGER               Spawn worker processes for simulation (0 =
                                  one thread)
  --seed INTEGER                  Global seed of the random-stream tree
                                  (default: fresh entropy, as a real lab never
                                  repeats)
  --tls-cert FILE                 PEM server certificate (chain)
  --tls-key FILE                  PEM private key of --tls-cert
  --token TEXT                    Require 'authorization: Bearer <token>' on
                                  every call (env QCSS_TOKEN)
  --insecure                      Allow a network bind without TLS or token
                                  (trusted networks only)
  --time-scale FLOAT RANGE        Lab seconds per wall second: the chip drifts
                                  while idle and jobs take instrument time (0
                                  freezes the chip and runs jobs unpaced)
                                  [default: 1.0; x>=0]
  --admin-listen TEXT             Address of the admin channel (scenarios,
                                  modes, truth, faults), e.g. 127.0.0.1:50052
  --admin-token TEXT              Token of the admin channel, separate from
                                  --token (env QCSS_ADMIN_TOKEN)
  --state-dir DIRECTORY           Keep the chip's state here, so it survives
                                  restarts (drift, defects, scenarios, lab
                                  time)
  --deterministic                 Honour each job's random_seed so CI can
                                  replay shots (a real instrument never does)
  --tier [auto|t0|t1a|t1b|t2]     Physics tier for every job (the operator's
                                  choice, not the client's)  [default: auto]
  --debug-reflection              Advertise the services through gRPC
                                  reflection (debugging)
  --board-listen TEXT             Also serve a Qibosoq-compatible board face
                                  (TCP/JSON) here, e.g. 127.0.0.1:6000
  --qick-ns TEXT                  Also serve a native QICK board (Pyro4, as
                                  qick.pyro.start_server does), registered
                                  with the Pyro4 nameserver at this host:port,
                                  e.g. 127.0.0.1:8888
  --qick-name TEXT                The QICK board's proxy name in the
                                  nameserver (make_proxy's proxy_name)
                                  [default: myqick]
  --qick-listen TEXT              host[:port] the QICK board's Pyro4 daemon
                                  binds; clients connect here after the lookup
                                  [default: 127.0.0.1]
  --qick-firmware [zcu216_v2_5q|zcu216_v1_5q]
                                  The firmware the QICK board runs: tProc v2
                                  or v1  [default: zcu216_v2_5q]
  --qick-start-ns                 Also run the Pyro4 nameserver at --qick-ns
                                  in this process
  --qick-loopback GEN:RO          Wire a bench test cable from generator GEN
                                  to readout RO's ADC (repeatable), as QICK's
                                  first tutorials assume: that generator
                                  leaves the chip and the readout hears only
                                  the cable
  --help                          Show this message and exit.
```

## `qcss technician`

```text
Usage: qcss technician [OPTIONS] COMMAND [ARGS]...

  The lab's calibration staff: Qibocal runs on a schedule and on request,
  writing the platform.

Options:
  --help  Show this message and exit.

Commands:
  request  Ask for a calibration (the hook a Quark adapter's...
  run      Keep a platform calibrated: requests first, then quick checks,...
```

## `qcss technician request`

```text
Usage: qcss technician request [OPTIONS]

  Ask for a calibration (the hook a Quark adapter's request_calibration
  calls); prints the acknowledgement.

Options:
  --requests-dir DIRECTORY  The technician's request spool  [required]
  --scope TEXT              What to calibrate: quick, device, cz  [default:
                            device]
  --help                    Show this message and exit.
```

## `qcss technician run`

```text
Usage: qcss technician run [OPTIONS]

  Keep a platform calibrated: requests first, then quick checks, full bring-
  ups and CZ as they come due.

Options:
  --platforms-dir DIRECTORY  Folder of Qibolab platforms (QIBOLAB_PLATFORMS)
                             [required]
  --platform TEXT            Platform to keep calibrated, e.g. qcss_qblox_5q
                             [required]
  --reports DIRECTORY        Where Qibocal's reports go  [required]
  --requests-dir DIRECTORY   The request spool  [required]
  --env TEXT                 NAME=VALUE for Qibocal's environment (instrument
                             address)
  --quick-every FLOAT RANGE  Seconds  [default: 14400.0; x>=1]
  --full-every FLOAT RANGE   Seconds  [default: 86400.0; x>=1]
  --cz-every FLOAT RANGE     Seconds  [default: 604800.0; x>=1]
  --poll FLOAT RANGE         Idle poll period, s  [default: 30.0; x>=0.1]
  --help                     Show this message and exit.
```

## `qcss validate`

```text
Usage: qcss validate [OPTIONS] JOB_PATH

  Validate a job schedule against hardware constraints without simulating.

Options:
  -p, --profile TEXT  Hardware profile name or path
  -d, --device TEXT   Device specification path or name
  --help              Show this message and exit.
```

## `qcss-dashboard`

```text
Usage: qcss-dashboard [OPTIONS]

  Start the QCSS Explorer dashboard.

Options:
  --host TEXT                 Address the dashboard listens on  [default:
                              127.0.0.1]
  --port INTEGER              [default: 8765]
  --workspace TEXT            Dashboard home (user configs, audit log, chip
                              state)
  --embedded / --no-embedded  Run a QCSS chassis inside the bridge, or connect
                              to an existing one  [default: embedded]
  --profile TEXT              Embedded chassis hardware profile  [default:
                              qblox_cluster_5q]
  --device TEXT               Embedded chassis device  [default: transmon_5q]
  --time-scale FLOAT          Embedded lab seconds per wall second  [default:
                              1.0]
  --lab TEXT                  Lab link of an external chassis  [default:
                              127.0.0.1:50051]
  --admin TEXT                Admin channel of an external chassis  [default:
                              127.0.0.1:50052]
  --ca TEXT                   CA/server certificate (PEM) for TLS to an
                              external chassis
  --read-only                 Refuse every change (configs, admin actions,
                              calibration, jobs)
  --static TEXT               Built frontend directory (default:
                              integrations/qcss_dashboard/web/dist)
  --tls-cert TEXT             TLS certificate for the dashboard itself
  --tls-key TEXT              TLS key for the dashboard itself
  --insecure                  Allow a non-loopback bind without TLS and a
                              login token
  --allowed-host TEXT         Host name browsers use to reach a network-bound
                              dashboard (repeatable)
  --help                      Show this message and exit.
```

Sources: `qcss --help` and nested `--help` (src/qcss/cli.py), `qcss-dashboard --help` (integrations/qcss_dashboard/src/qcss_dashboard/cli.py).
