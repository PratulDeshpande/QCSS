"""Command-line interface (CLI) for the Quantum Control Stack Simulator (QCSS)."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import pathlib
import sys
import time
from typing import Any

import click
import numpy as np
import yaml
from google.protobuf import json_format

from qcss.adapters.grpc_server import UnsafeBindError, check_bind_is_safe
from qcss.config.loader import get_unverified_fields, load_device, load_profile
from qcss.core.errors import HardwareValidationError, TierRoutingError
from qcss.core.ndarray import from_proto
from qcss.core.net import is_local_address
from qcss.core.timebase import TimeBase
from qcss.runtime.runner import SimulationContext, create_simulation_runner
from qcss.v1 import job_pb2

PROFILES_DIR = pathlib.Path(__file__).parent / "config" / "profiles"
DEVICES_DIR = pathlib.Path(__file__).parent / "config" / "devices"


def _resolve_profile_path(name_or_path: str) -> pathlib.Path:
    p = pathlib.Path(name_or_path)
    if p.exists():
        return p
    # Check built-in profiles directory
    candidate = PROFILES_DIR / f"{name_or_path}.yaml"
    if candidate.exists():
        return candidate
    candidate_raw = PROFILES_DIR / name_or_path
    if candidate_raw.exists():
        return candidate_raw
    raise click.BadParameter(f"Hardware profile not found: '{name_or_path}'. Checked local path and {PROFILES_DIR}")


def _resolve_device_path(name_or_path: str | None) -> pathlib.Path | None:
    if not name_or_path:
        return None
    p = pathlib.Path(name_or_path)
    if p.exists():
        return p
    candidate = DEVICES_DIR / f"{name_or_path}.yaml"
    if candidate.exists():
        return candidate
    candidate_raw = DEVICES_DIR / name_or_path
    if candidate_raw.exists():
        return candidate_raw
    raise click.BadParameter(f"Device specification not found: '{name_or_path}'. Checked local path and {DEVICES_DIR}")


def _load_job_file(job_path: str) -> job_pb2.Job:
    path = pathlib.Path(job_path)
    if not path.exists():
        raise click.BadParameter(f"Job file not found: '{job_path}'")

    raw = path.read_bytes()
    job = job_pb2.Job()

    if path.suffix in (".bin", ".pb"):
        job.ParseFromString(raw)
        return job

    # Text format: JSON or YAML
    text = raw.decode("utf-8")
    try:
        data = yaml.safe_load(text)
        if isinstance(data, dict):
            return json_format.ParseDict(data, job_pb2.Job(), ignore_unknown_fields=False)
    except Exception:  # noqa: S110, BLE001
        pass

    try:
        return json_format.Parse(text, job_pb2.Job(), ignore_unknown_fields=False)
    except Exception as exc:
        raise click.ClickException(f"Failed to parse job file '{job_path}': {exc}") from exc


@click.group()
@click.version_option(version="0.1.0", prog_name="qcss")
def app():
    """QCSS: Hardware-in-the-loop Quantum Control Stack Simulator."""


@app.group()
def profile():
    """Inspect and manage hardware profiles."""


@profile.command("list")
def profile_list():
    """List available built-in hardware profiles."""
    click.echo("Available hardware profiles:")
    if PROFILES_DIR.exists():
        for f in sorted(PROFILES_DIR.glob("*.yaml")):
            try:
                prof = load_profile(f)
                click.echo(
                    f"  * {f.stem:<22} [vendor: {prof.vendor:<10} clock: {prof.clock.tick_hz} Hz, "
                    f"generators: {len(prof.generators)}, ports: {len(prof.ports)}]"
                )
            except Exception as e:  # noqa: BLE001
                click.echo(f"  * {f.stem:<22} [error loading: {e}]")


@profile.command("show")
@click.argument("name_or_path")
def profile_show(name_or_path: str):
    """Show details of a hardware profile."""
    path = _resolve_profile_path(name_or_path)
    prof = load_profile(path)

    click.echo(f"Profile: {prof.profile_name} (from {path.name})")
    click.echo(f"Vendor:  {prof.vendor}")
    source_str = prof.clock.provenance.source_url or "hardware spec"
    click.echo(f"Clock:   {prof.clock.tick_hz} Hz ({source_str})")
    click.echo(f"\nPorts ({len(prof.ports)}):")
    for p in prof.ports:
        click.echo(f"  - {p.port_id:<16} kind: {p.kind:<12} max_generators: {p.max_generators}")

    click.echo(f"\nGenerators ({len(prof.generators)}):")
    for g in prof.generators:
        click.echo(
            f"  - {g.generator_id:<16} port: {g.port_id:<16} sample_rate: {g.sample_rate_hz} Hz, "
            f"wave_mem: {g.wave_mem_samples} smp, instr_mem: {g.instr_mem}"
        )

    click.echo(f"\nFeedback Latencies ({len(prof.feedback.latencies)} entries):")
    for lat in prof.feedback.latencies:
        click.echo(f"  - {lat.src} -> {lat.dst} [{lat.routing}]: {lat.latency_ticks} ticks (+/-{lat.jitter_ticks})")

    unverified = get_unverified_fields(prof)
    if unverified:
        click.secho(f"\nUnverified Provenance Fields ({len(unverified)}):", fg="yellow")
        for u in unverified:
            click.echo(f"  ! {u}")
    else:
        click.secho("\nAll profile fields verified against hardware specs.", fg="green")


@app.group()
def device():
    """Inspect and manage device specifications."""


@device.command("show")
@click.argument("path_or_name")
def device_show(path_or_name: str):
    """Show details of a device physics specification."""
    path = _resolve_device_path(path_or_name)
    if path is None:
        raise click.BadParameter("Device path required")
    dev = load_device(path)

    click.echo(f"Device: {dev.device_name} (from {path.name})")
    click.echo(f"Chip Area: {dev.chip_area_cm2} cm^2")
    click.echo(f"\nQubits ({len(dev.qubits)}):")
    for q in dev.qubits:
        click.echo(
            f"  - Q{q.qubit_index}: f_max={q.f_max_ghz:.3f} GHz, Ec={q.ec_ghz:.3f} GHz, "
            f"T1={q.t1_us:.1f} us, T2*={q.t2_star_us:.1f} us, P_exc={q.p_excited}"
        )

    click.echo(f"\nCouplers ({len(dev.couplers)}):")
    for c in dev.couplers:
        click.echo(f"  - Q{c.qubit_pair[0]} <-> Q{c.qubit_pair[1]}: J = {c.j_mhz:.2f} MHz")

    click.echo(f"\nResonators ({len(dev.resonators)}):")
    for r in dev.resonators:
        click.echo(f"  - Q{r.qubit_index}: f_r={r.f_r_ghz:.3f} GHz, kappa={r.kappa_mhz:.2f} MHz, chi={(r.pulls_mhz[1]-r.pulls_mhz[0])/2:.2f} MHz")


@app.command("validate")
@click.argument("job_path")
@click.option("--profile", "-p", default="qblox_cluster_5q", help="Hardware profile name or path")
@click.option("--device", "-d", default=None, help="Device specification path or name")
def validate(job_path: str, profile: str, device: str | None):
    """Validate a job schedule against hardware constraints without simulating."""
    p_path = _resolve_profile_path(profile)
    prof = load_profile(p_path)
    d_path = _resolve_device_path(device)
    dev = load_device(d_path) if d_path else None

    tb = TimeBase.from_clocks(prof.clock.tick_hz)
    job = _load_job_file(job_path)

    try:
        plan = SimulationContext(prof, dev, tb).plan(job)
    except HardwareValidationError as err:
        click.secho(f"Job '{job.job_key or job_path}' has {len(err.violations)} hardware violations:", fg="red")
        for path, desc in err.violations:
            click.echo(f"  * {path}: {desc}")
        sys.exit(1)
    except TierRoutingError as err:
        click.secho(str(err), fg="red")
        sys.exit(1)
    click.secho(f"Job '{job.job_key or job_path}' is VALID against profile '{prof.profile_name}' "
                f"(tier {plan.tier}: {plan.reason}).", fg="green")
    for w in plan.warnings:
        click.secho(f"  warning: {w}", fg="yellow")


@app.command("run")
@click.argument("job_path")
@click.option("--profile", "-p", default="qblox_cluster_5q", help="Hardware profile name or path")
@click.option("--device", "-d", default=None, help="Device specification path or name")
@click.option("--shots", "-s", type=int, default=None, help="Override number of shots")
@click.option(
    "--tier",
    "-t",
    type=click.Choice(["T0", "T1A", "T1B", "T2", "T3", "AUTO"], case_sensitive=False),
    default=None,
    help="Override simulation fidelity tier",
)
@click.option("--chunk-size", "-c", type=int, default=1024, help="Chunk size in shots (part of the seed key)")
@click.option("--output", "-o", type=click.Path(), default=None, help="Output JSON results file")
def run(job_path: str, profile: str, device: str | None, shots: int | None, tier: str | None,
        chunk_size: int, output: str | None):
    """Run a quantum control job on the simulator."""
    p_path = _resolve_profile_path(profile)
    prof = load_profile(p_path)
    d_path = _resolve_device_path(device)
    dev = load_device(d_path) if d_path else None

    tb = TimeBase.from_clocks(prof.clock.tick_hz)
    job = _load_job_file(job_path)

    if shots is not None:
        job.num_shots = shots
    if job.num_shots == 0:
        job.num_shots = 100

    tier_enum_map = {
        "T0": job_pb2.FIDELITY_TIER_T0_SURROGATE,
        "T1A": job_pb2.FIDELITY_TIER_T1A_STABILIZER,
        "T1B": job_pb2.FIDELITY_TIER_T1B_STATEVECTOR,
        "T2": job_pb2.FIDELITY_TIER_T2_LINDBLAD,
        "T3": job_pb2.FIDELITY_TIER_T3_TRAJECTORY,
        "AUTO": job_pb2.FIDELITY_TIER_AUTO,
    }
    if tier is not None:
        job.requested_tier = tier_enum_map[tier.upper()]

    click.echo(
        f"Simulating '{job.job_key or job_path}' ({job.num_shots} shots) on "
        f"profile '{prof.profile_name}' [tier: {tier or 'AUTO'}]..."
    )

    ctx = SimulationContext(prof, dev, tb)
    try:
        plan = ctx.plan(job)
    except HardwareValidationError as err:
        click.secho(f"Simulation failed: {len(err.violations)} hardware violations", fg="red")
        for path, desc in err.violations:
            click.echo(f"  * {path}: {desc}")
        sys.exit(1)
    except TierRoutingError as err:
        click.secho(f"Simulation failed: {err}", fg="red")
        sys.exit(1)
    click.echo(f"Tier: {plan.tier} ({plan.reason})")
    runner = create_simulation_runner(prof, dev, tb, chunk_size=chunk_size, context=ctx)
    cancel = asyncio.Event()

    async def execute():
        t0 = time.perf_counter()
        chunks = []
        async for chunk in runner(job.job_key or "cli_run", job, cancel):
            chunks.append(chunk)
            click.echo(f"  Chunk {chunk.sequence_number}: {chunk.num_shots_in_chunk} shots processed "
                       f"(total: {chunk.shot_offset + chunk.num_shots_in_chunk}/{job.num_shots})")
        elapsed = time.perf_counter() - t0
        return chunks, elapsed

    try:
        chunks, elapsed = asyncio.run(execute())
    except Exception as exc:  # noqa: BLE001
        click.secho(f"Simulation failed: {exc}", fg="red")
        sys.exit(1)

    click.secho(
        f"\nSimulation completed in {elapsed:.3f} s ({job.num_shots / max(elapsed, 1e-6):.1f} shots/s).",
        fg="green",
    )

    # Collect result summary
    summary: dict[str, Any] = {
        "job_key": job.job_key or job_path,
        "num_shots": job.num_shots,
        "elapsed_seconds": elapsed,
        "chunks": len(chunks),
        "acquisitions": {},
    }

    for c in chunks:
        for acq in c.acquisitions:
            k = acq.result_key
            if k not in summary["acquisitions"]:
                summary["acquisitions"][k] = {"states": [], "iq_count": 0}
            st = from_proto(acq.states)
            summary["acquisitions"][k]["states"].extend(st.tolist())
            summary["acquisitions"][k]["iq_count"] += len(from_proto(acq.iq))

    # Print acquisition counts
    click.echo("Acquisition summary:")
    for k, v in summary["acquisitions"].items():
        st_arr = np.array(v["states"])
        counts = {int(val): int(np.sum(st_arr == val)) for val in np.unique(st_arr)} if len(st_arr) else {}
        click.echo(f"  - Key '{k}': {len(st_arr)} measurements, state counts: {counts}")

    if output:
        out_path = pathlib.Path(output)
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        click.echo(f"Saved results to: {out_path.resolve()}")


def _parse_qick_loopback(values: tuple[str, ...], qick_ns: str | None) -> tuple[tuple[int, int], ...]:
    """``--qick-loopback GEN:RO`` values as (generator, readout) pairs."""
    if values and qick_ns is None:
        raise click.UsageError("--qick-loopback cables the native QICK board: it needs --qick-ns host:port")
    cables = []
    for v in values:
        parts = v.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            raise click.UsageError(f"--qick-loopback {v}: give GEN:RO, a generator and a readout index, e.g. 6:0")
        cables.append((int(parts[0]), int(parts[1])))
    return tuple(cables)


def _check_qick_options(qick_ns: str | None, qick_listen: str, start_ns: bool, insecure: bool) -> None:
    """The native QICK board's addresses: TCP host:port, and on a network only with --insecure."""
    if qick_ns is None:
        if start_ns:
            raise click.UsageError("--qick-start-ns needs --qick-ns host:port (where to run the nameserver)")
        return
    ns_host, _, ns_port = qick_ns.rpartition(":")
    if not ns_host or not ns_port.isdigit():
        raise click.UsageError(f"--qick-ns {qick_ns}: the Pyro4 nameserver is TCP host:port, e.g. 127.0.0.1:8888")
    l_host, _, l_port = qick_listen.partition(":")
    if not l_host or (l_port and not l_port.isdigit()):
        raise click.UsageError(f"--qick-listen {qick_listen}: give host or host:port, e.g. 127.0.0.1")
    for flag, addr in (("--qick-listen", f"{l_host}:{l_port or 0}"), ("--qick-ns", qick_ns if start_ns else None)):
        if addr is not None and not insecure and not is_local_address(addr):
            raise click.UsageError(f"refusing to bind {flag} {addr} to the network: Pyro4 has no TLS and no token "
                                   "(QICK's own boards neither); pass --insecure on a network you trust")
    if importlib.util.find_spec("Pyro4") is None:      # last: the operator's own mistakes are reported first
        raise click.UsageError("the native QICK board needs Pyro4: pip install 'qcss[qick]'")


@app.command("serve")
@click.option("--host", "-h", default="127.0.0.1", help="gRPC host bind address (a network bind needs TLS and --token)")
@click.option("--port", "-p", type=int, default=50051, help="gRPC port")
@click.option("--listen", default=None, help="Full address instead of host:port, e.g. unix:C:/Users/me/qcss.sock")
@click.option("--profile", default="qblox_cluster_5q", help="Hardware profile name or path")
@click.option("--device", default=None, help="Device specification path or name")
@click.option("--workers", type=int, default=0, help="Spawn worker processes for simulation (0 = one thread)")
@click.option("--seed", type=int, default=None,
              help="Global seed of the random-stream tree (default: fresh entropy, as a real lab never repeats)")
@click.option("--tls-cert", type=click.Path(dir_okay=False), default=None, help="PEM server certificate (chain)")
@click.option("--tls-key", type=click.Path(dir_okay=False), default=None, help="PEM private key of --tls-cert")
@click.option("--token", envvar="QCSS_TOKEN", default=None,
              help="Require 'authorization: Bearer <token>' on every call (env QCSS_TOKEN)")
@click.option("--insecure", is_flag=True, help="Allow a network bind without TLS or token (trusted networks only)")
@click.option("--time-scale", type=click.FloatRange(min=0), default=1.0, show_default=True,
              help="Lab seconds per wall second: the chip drifts while idle and jobs take instrument time "
                   "(0 freezes the chip and runs jobs unpaced)")
@click.option("--admin-listen", default=None,
              help="Address of the admin channel (scenarios, modes, truth, faults), e.g. 127.0.0.1:50052")
@click.option("--admin-token", envvar="QCSS_ADMIN_TOKEN", default=None,
              help="Token of the admin channel, separate from --token (env QCSS_ADMIN_TOKEN)")
@click.option("--state-dir", type=click.Path(file_okay=False), default=None,
              help="Keep the chip's state here, so it survives restarts (drift, defects, scenarios, lab time)")
@click.option("--deterministic", is_flag=True,
              help="Honour each job's random_seed so CI can replay shots (a real instrument never does)")
@click.option("--tier", type=click.Choice(["auto", "t0", "t1a", "t1b", "t2"], case_sensitive=False), default="auto",
              show_default=True, help="Physics tier for every job (the operator's choice, not the client's)")
@click.option("--debug-reflection", is_flag=True, help="Advertise the services through gRPC reflection (debugging)")
@click.option("--board-listen", default=None,
              help="Also serve a Qibosoq-compatible board face (TCP/JSON) here, e.g. 127.0.0.1:6000")
@click.option("--qick-ns", default=None,
              help="Also serve a native QICK board (Pyro4, as qick.pyro.start_server does), registered with the "
                   "Pyro4 nameserver at this host:port, e.g. 127.0.0.1:8888")
@click.option("--qick-name", default="myqick", show_default=True,
              help="The QICK board's proxy name in the nameserver (make_proxy's proxy_name)")
@click.option("--qick-listen", default="127.0.0.1", show_default=True,
              help="host[:port] the QICK board's Pyro4 daemon binds; clients connect here after the lookup")
@click.option("--qick-firmware", type=click.Choice(["zcu216_v2_5q", "zcu216_v1_5q"]), default="zcu216_v2_5q",
              show_default=True, help="The firmware the QICK board runs: tProc v2 or v1")
@click.option("--qick-start-ns", is_flag=True, help="Also run the Pyro4 nameserver at --qick-ns in this process")
@click.option("--qick-loopback", "qick_loopback", multiple=True, metavar="GEN:RO",
              help="Wire a bench test cable from generator GEN to readout RO's ADC (repeatable), as QICK's first "
                   "tutorials assume: that generator leaves the chip and the readout hears only the cable")
def serve_cmd(host: str, port: int, listen: str | None, profile: str, device: str | None, workers: int,
              seed: int | None, tls_cert: str | None, tls_key: str | None, token: str | None, insecure: bool,
              time_scale: float, admin_listen: str | None, admin_token: str | None, state_dir: str | None,
              deterministic: bool, tier: str, debug_reflection: bool, board_listen: str | None,
              qick_ns: str | None, qick_name: str, qick_listen: str, qick_firmware: str, qick_start_ns: bool,
              qick_loopback: tuple[str, ...]):
    """Run the simulated instrument (the chassis): the instrument link, and optionally the admin link."""
    from qcss.chassis import Chassis, ChassisConfig

    addr = listen or f"{host}:{port}"
    if (tls_cert is None) != (tls_key is None):
        raise click.UsageError("pass both --tls-cert and --tls-key, or neither")
    if admin_listen is not None and token and not admin_token:
        raise click.UsageError("the lab link requires a token, so the admin channel needs one too: pass --admin-token")
    if admin_token and admin_token == token:
        raise click.UsageError("--admin-token must differ from --token")
    if admin_listen is not None and admin_listen == addr:
        raise click.UsageError("--admin-listen must differ from the instrument address")
    try:
        check_bind_is_safe(addr, tls=tls_cert is not None, token=bool(token), insecure=insecure)
        if admin_listen is not None:
            check_bind_is_safe(admin_listen, tls=tls_cert is not None, token=bool(admin_token), insecure=insecure)
    except UnsafeBindError as err:
        raise click.UsageError(str(err)) from err
    if board_listen is not None:
        b_host, _, b_port = board_listen.rpartition(":")
        if board_listen.startswith(("unix:", "unix-abstract:")) or not b_host or not b_port.isdigit():
            raise click.UsageError(f"--board-listen {board_listen}: the board face is TCP host:port (the qibosoq "
                                   "client connects over TCP only), e.g. 127.0.0.1:6000")
    if board_listen is not None and not insecure and not is_local_address(board_listen):
        raise click.UsageError(f"refusing to bind the board face to {board_listen}: the qibosoq protocol has no TLS "
                               "and no token; pass --insecure on a network you trust")
    cables = _parse_qick_loopback(qick_loopback, qick_ns)
    _check_qick_options(qick_ns, qick_listen, qick_start_ns, insecure)
    tls =(pathlib.Path(tls_cert).read_bytes(), pathlib.Path(tls_key).read_bytes()) if tls_cert and tls_key else None

    prof = load_profile(_resolve_profile_path(profile))
    if board_listen is not None and not any(p.port_id.startswith("dac") for p in prof.ports):
        # BoardWiring (boards/qibosoq.py) maps the client's dac N onto ports named dacN; any other profile fails late
        raise click.UsageError(f"--board-listen needs an RFSoC profile whose ports are dacN, such as qick_zcu216_5q "
                               f"(profile '{profile}' has none)")
    d_path = _resolve_device_path(device)
    dev = load_device(d_path) if d_path else None
    chassis = Chassis(ChassisConfig(
        profile=prof, device=dev, lab_address=addr, admin_address=admin_listen, tls=tls, token=token,
        admin_token=admin_token, state_dir=pathlib.Path(state_dir) if state_dir else None, seed=seed,
        time_scale=time_scale, deterministic=deterministic, tier=tier.upper(), workers=workers,
        reflection=debug_reflection, board_address=board_listen, qick_ns=qick_ns, qick_name=qick_name,
        qick_listen=qick_listen, qick_firmware=qick_firmware, qick_start_ns=qick_start_ns, qick_loopback=cables))

    security = ("TLS" if tls else "plaintext") + (", token required" if token else ", no token")
    click.echo(f"Starting QCSS ControlService on {addr} ({security}) with profile '{prof.profile_name}'...")
    if chassis.restored:
        click.echo(f"Restored the chip from {chassis.state_path}.")

    async def run_server():
        await chassis.start()
        click.secho(f"QCSS ControlService listening on {addr}. Press Ctrl+C to terminate.", fg="green")
        if admin_listen is not None:
            click.echo(f"Admin channel on {admin_listen}" + (" (token required)." if admin_token else "."))
        if board_listen is not None:
            click.echo(f"Qibosoq board face on {board_listen}.")
        try:
            await chassis.wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await chassis.stop()

    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        click.echo("\nServer terminated by user.")


# ---------------------------------------------------------------------- admin channel
@app.group("admin")
def admin():
    """Operate the simulated lab through its admin channel (scenarios, modes, truth, instrument faults)."""


def _admin_options(f):
    f = click.option("--target", "-t", default="127.0.0.1:50052", show_default=True,
                     help="host:port of the admin channel")(f)
    f = click.option("--ca", type=click.Path(exists=True, dir_okay=False), default=None,
                     help="PEM certificate to trust; enables TLS")(f)
    f = click.option("--token", envvar="QCSS_ADMIN_TOKEN", default=None, help="Admin token (env QCSS_ADMIN_TOKEN)")(f)
    f = click.option("--insecure", is_flag=True,
                     help="Allow sending the token without TLS to a non-loopback address (trusted networks only)")(f)
    return click.option("--timeout", type=float, default=30.0, show_default=True, help="Per-call timeout, s")(f)


def _admin_call(opts: dict[str, Any], method: str, request: Any) -> Any:
    """One AdminService call; prints the gRPC error and exits 1 on failure."""
    import grpc

    from qcss.admin.v1 import admin_pb2_grpc as apbg
    from qcss.core.net import is_local_address

    target, ca, token = opts["target"], opts["ca"], opts["token"]
    if token and ca is None and not opts["insecure"] and not is_local_address(target):
        raise click.UsageError(f"refusing to send the admin token in cleartext to {target}; pass --ca or --insecure")
    channel = (grpc.secure_channel(target, grpc.ssl_channel_credentials(pathlib.Path(ca).read_bytes())) if ca
               else grpc.insecure_channel(target))
    md = (("authorization", f"Bearer {token}"),) if token else ()
    try:
        with channel:
            return getattr(apbg.AdminServiceStub(channel), method)(request, metadata=md, timeout=opts["timeout"])
    except grpc.RpcError as err:
        click.secho(f"Error {err.code().name}: {err.details()}", fg="red")      # type: ignore[attr-defined]
        sys.exit(1)


@admin.command("kill")
@click.argument("qubit", type=int)
@_admin_options
def admin_kill(qubit: int, **opts: Any):
    """Lose a qubit: it decays within ~100 ns and moves 200 MHz off where it was calibrated."""
    from qcss.admin.v1 import admin_pb2 as apb
    _admin_call(opts, "KillQubit", apb.KillQubitRequest(qubit_index=qubit))
    click.echo(f"qubit {qubit} killed")


@admin.command("revive")
@click.argument("qubit", type=int)
@_admin_options
def admin_revive(qubit: int, **opts: Any):
    """Undo `kill`."""
    from qcss.admin.v1 import admin_pb2 as apb
    _admin_call(opts, "ReviveQubit", apb.ReviveQubitRequest(qubit_index=qubit))
    click.echo(f"qubit {qubit} revived")


@admin.command("drift")
@click.argument("qubit", type=int)
@click.option("--df-hz", type=float, default=0.0, help="Frequency jump, Hz")
@click.option("--t1-factor", type=click.FloatRange(min=0, min_open=True), default=1.0, help="Multiply T1 by this")
@_admin_options
def admin_drift(qubit: int, df_hz: float, t1_factor: float, **opts: Any):
    """Step a qubit's frequency and/or T1 (accumulates)."""
    from qcss.admin.v1 import admin_pb2 as apb
    _admin_call(opts, "DriftStep", apb.DriftStepRequest(qubit_index=qubit, delta_frequency_hz=df_hz,
                                                        t1_factor=t1_factor))
    click.echo(f"qubit {qubit}: df {df_hz:g} Hz, T1 x{t1_factor:g}")


@admin.command("tls")
@click.argument("qubit", type=int)
@click.option("--coupling-hz", type=float, default=0.0, help="Defect coupling (default 0.5 MHz)")
@click.option("--linewidth-hz", type=float, default=0.0, help="Defect linewidth (default 1 MHz)")
@click.option("--detuning-hz", type=float, default=0.0, help="Defect detuning from the qubit")
@_admin_options
def admin_tls(qubit: int, coupling_hz: float, linewidth_hz: float, detuning_hz: float, **opts: Any):
    """A TLS defect drifts into resonance with the qubit."""
    from qcss.admin.v1 import admin_pb2 as apb
    _admin_call(opts, "TlsCollision", apb.TlsCollisionRequest(qubit_index=qubit, coupling_hz=coupling_hz,
                                                              linewidth_hz=linewidth_hz, detuning_hz=detuning_hz))
    click.echo(f"qubit {qubit}: TLS collision")


@admin.command("burst")
@click.argument("qubit", type=int)
@click.option("--peak-gamma-per-s", type=float, default=0.0, help="Peak extra decay rate (default 2 per us)")
@_admin_options
def admin_burst(qubit: int, peak_gamma_per_s: float, **opts: Any):
    """A cosmic-ray hit centred on the qubit, now."""
    from qcss.admin.v1 import admin_pb2 as apb
    _admin_call(opts, "Burst", apb.BurstRequest(qubit_index=qubit, peak_gamma_per_s=peak_gamma_per_s))
    click.echo(f"qubit {qubit}: burst")


@admin.command("freeze")
@click.option("--off", is_flag=True, help="Let the chip drift again")
@_admin_options
def admin_freeze(off: bool, **opts: Any):
    """Stop (or resume) drift of the whole chip."""
    from qcss.admin.v1 import admin_pb2 as apb
    _admin_call(opts, "FreezeDrift", apb.FreezeDriftRequest(frozen=not off))
    click.echo("drift resumed" if off else "drift frozen")


@admin.command("clear")
@_admin_options
def admin_clear(**opts: Any):
    """Remove every scenario (kills, drift steps, defects, bursts)."""
    from qcss.admin.v1 import admin_pb2 as apb
    _admin_call(opts, "ClearScenarios", apb.ClearScenariosRequest())
    click.echo("scenarios cleared")


_TIERS = {"requested": job_pb2.FIDELITY_TIER_UNSPECIFIED, "auto": job_pb2.FIDELITY_TIER_AUTO, "t0": job_pb2.FIDELITY_TIER_T0_SURROGATE,
          "t1a": job_pb2.FIDELITY_TIER_T1A_STABILIZER, "t1b": job_pb2.FIDELITY_TIER_T1B_STATEVECTOR,
          "t2": job_pb2.FIDELITY_TIER_T2_LINDBLAD}


@admin.command("mode")
@click.option("--time-scale", type=click.FloatRange(min=0), default=None, help="Lab seconds per wall second")
@click.option("--deterministic/--realistic", default=None, help="Replay job seeds (CI) or not (lab)")
@click.option("--tier", type=click.Choice(list(_TIERS), case_sensitive=False), default=None,
              help="Physics tier for every job ('requested' honours each job's own)")
@_admin_options
def admin_mode(time_scale: float | None, deterministic: bool | None, tier: str | None, **opts: Any):
    """Show how the chassis runs; with options, change it."""
    from qcss.admin.v1 import admin_pb2 as apb
    cur = _admin_call(opts, "GetMode", apb.GetModeRequest())
    mode = cur.mode
    if time_scale is not None or deterministic is not None or tier is not None:
        if time_scale is not None:
            mode.time_scale = time_scale
        if deterministic is not None:
            mode.deterministic = deterministic
        if tier is not None:
            mode.tier_policy = _TIERS[tier.lower()]
        mode = _admin_call(opts, "SetMode", apb.SetModeRequest(mode=mode)).mode
    tier_name = ("REQUESTED" if mode.tier_policy == job_pb2.FIDELITY_TIER_UNSPECIFIED
                 else job_pb2.FidelityTier.Name(mode.tier_policy).removeprefix("FIDELITY_TIER_").split("_")[0])
    click.echo(f"time_scale {mode.time_scale:g}  deterministic {'yes' if mode.deterministic else 'no'}  "
               f"tier {tier_name}  seed {cur.global_seed}")


@admin.command("truth")
@_admin_options
def admin_truth(**opts: Any):
    """The chip as it really is now (only the simulator knows this)."""
    from qcss.admin.v1 import admin_pb2 as apb
    t = _admin_call(opts, "ReadTruth", apb.ReadTruthRequest())
    click.echo(f"lab time {t.lab_time_s:.3f} s")
    click.echo("  qubit   f01 (GHz)   T1 (us)   state")
    for q in t.qubits:
        click.echo(f"  {q.qubit_index:>3}   {q.frequency_hz / 1e9:9.6f}  {q.t1_s * 1e6:8.2f}   "
                   f"{'DEAD' if q.dead else 'ok'}")


@admin.command("inspect")
@click.argument("job_id")
@_admin_options
def admin_inspect(job_id: str, **opts: Any):
    """How the simulator ran a job (tier, noise fidelity, calibration epoch)."""
    from qcss.admin.v1 import admin_pb2 as apb
    from qcss.v1 import result_pb2
    r = _admin_call(opts, "InspectJob", apb.InspectJobRequest(job_id=job_id))
    click.echo(f"tier {job_pb2.FidelityTier.Name(r.tier_used)}  "
               f"noise {result_pb2.NoiseFidelity.Name(r.noise_fidelity)}  epoch {r.calibration_epoch}")
    for w in r.warnings:
        click.echo(f"  warning: {w}")


@admin.command("fault")
@click.argument("kind", type=click.Choice(["hang", "drop", "reboot", "slow-upload"], case_sensitive=False))
@click.option("--count", type=click.IntRange(min=1), default=1, show_default=True, help="Calls affected")
@click.option("--duration", type=click.FloatRange(min=0), default=None,
              help="Seconds (required for hang, reboot and slow-upload)")
@_admin_options
def admin_fault(kind: str, count: int, duration: float | None, **opts: Any):
    """Make the instrument misbehave: hang or drop calls, reboot, or upload slowly."""
    from qcss.admin.v1 import admin_pb2 as apb
    if kind.lower() != "drop" and not duration:
        raise click.UsageError(f"--duration (seconds, > 0) is required for a {kind} fault")
    duration = duration or 0.0
    fault = {"hang": apb.INSTRUMENT_FAULT_HANG, "drop": apb.INSTRUMENT_FAULT_DROP,
             "reboot": apb.INSTRUMENT_FAULT_REBOOT, "slow-upload": apb.INSTRUMENT_FAULT_SLOW_UPLOAD}[kind.lower()]
    _admin_call(opts, "InjectInstrumentFault",
                apb.InjectInstrumentFaultRequest(fault=fault, count=count, duration_s=duration))
    click.echo(f"instrument fault: {kind} x{count}" + (f" for {duration:g} s" if duration else ""))


@admin.command("clear-faults")
@_admin_options
def admin_clear_faults(**opts: Any):
    """Remove every pending instrument fault."""
    from qcss.admin.v1 import admin_pb2 as apb
    _admin_call(opts, "ClearInstrumentFaults", apb.ClearInstrumentFaultsRequest())
    click.echo("instrument faults cleared")


# ---------------------------------------------------------------------- remote client
@app.group("remote")
def remote():
    """Talk to a running QCSS server (this machine or another one on the network)."""


def _remote_options(f):
    f = click.option("--target", "-t", default="127.0.0.1:50051", show_default=True,
                     help="host:port of the server")(f)
    f = click.option("--ca", type=click.Path(exists=True, dir_okay=False), default=None,
                     help="PEM certificate to trust (the server's self-signed cert or its CA); enables TLS")(f)
    f = click.option("--token", envvar="QCSS_TOKEN", default=None, help="Bearer token (env QCSS_TOKEN)")(f)
    f = click.option("--insecure", is_flag=True,
                     help="Allow sending the token without TLS to a non-loopback address (trusted networks only)")(f)
    return click.option("--timeout", type=float, default=30.0, show_default=True, help="Per-call timeout, s")(f)


def _client(target: str, ca: str | None, token: str | None, timeout: float, insecure: bool = False):
    from qcss.client import QcssClient
    return QcssClient(target, tls_ca=pathlib.Path(ca).read_bytes() if ca else None, token=token, timeout_s=timeout,
                      insecure=insecure)


def _fail(err: Exception) -> None:
    from qcss.client import QcssRpcError
    if isinstance(err, QcssRpcError):
        click.secho(f"Error {err.code.name}: {err.message}", fg="red")
        for path, desc in err.field_violations:
            click.echo(f"  * {path}: {desc}")
        for kind, subject, desc in err.precondition_failures:
            click.echo(f"  * {kind} ({subject}): {desc}")
    else:
        click.secho(f"Error: {err}", fg="red")
    sys.exit(1)


@remote.command("ping")
@_remote_options
def remote_ping(target: str, ca: str | None, token: str | None, timeout: float, insecure: bool):
    """Check that the server is reachable and healthy (gRPC health check)."""
    t0 = time.perf_counter()
    try:
        with _client(target, ca, token, timeout, insecure) as c:
            ok = c.health()
    except Exception as err:  # noqa: BLE001
        _fail(err)
        return
    click.echo(f"{target}: {'SERVING' if ok else 'NOT SERVING'} ({(time.perf_counter() - t0) * 1e3:.1f} ms)")
    sys.exit(0 if ok else 1)


@remote.command("describe")
@_remote_options
def remote_describe(target: str, ca: str | None, token: str | None, timeout: float, insecure: bool):
    """Show the instrument profile and the channels the server offers."""
    from qcss.v1 import device_pb2
    try:
        with _client(target, ca, token, timeout, insecure) as c:
            d = c.describe()
    except Exception as err:  # noqa: BLE001
        _fail(err)
        return
    click.echo(f"Profile: {d.profile_name}  vendor: {d.vendor}  tick: {d.tick_hz} Hz  "
               f"max states: {d.max_discriminated_states}")
    for ch in d.channels:
        kind = device_pb2.ChannelKind.Name(ch.kind).removeprefix("CHANNEL_KIND_").lower()
        click.echo(f"  - {ch.channel_id:<12} {kind:<16} qubits {list(ch.qubits)}  frame {ch.frame_id:<6} "
                   f"port {ch.port_id}  {ch.sample_rate_hz / 1e9:g} GS/s")


@remote.command("properties")
@_remote_options
def remote_properties(target: str, ca: str | None, token: str | None, timeout: float, insecure: bool):
    """Show T1, T2*, readout and gate errors per qubit and pair."""
    try:
        with _client(target, ca, token, timeout, insecure) as c:
            p = c.properties()
    except Exception as err:  # noqa: BLE001
        _fail(err)
        return
    click.echo(f"Source: {p.source}  measured at: {p.measured_at.ToJsonString()}  epoch: {p.calibration_epoch}")
    click.echo("  qubit   f (GHz)   T1 (us)  T2* (us)  P(1|0)   P(0|1)   1q error")
    for q in p.qubits:
        click.echo(f"  {q.qubit_index:>5}  {q.frequency_hz / 1e9:8.4f}  {q.t1_s * 1e6:8.1f}  {q.t2_star_s * 1e6:8.1f}  "
                   f"{q.prob_meas1_prep0:7.4f}  {q.prob_meas0_prep1:7.4f}  {q.single_qubit_gate_error:.2e}")
    for pr in p.pairs:
        click.echo(f"  pair {list(pr.qubits)}: J = {pr.coupling_hz / 1e6:.2f} MHz, 2q gate "
                   f"{pr.two_qubit_gate_duration_s * 1e9:.0f} ns, error {pr.two_qubit_gate_error:.2e}")


@remote.command("calibration")
@_remote_options
@click.option("--qubit", "-q", "qubits", type=int, multiple=True, help="Only these qubits (repeatable)")
def remote_calibration(target: str, ca: str | None, token: str | None, timeout: float, insecure: bool,
                       qubits: tuple[int, ...]):
    """Print the current calibration snapshot and its epoch as JSON."""
    try:
        with _client(target, ca, token, timeout, insecure) as c:
            snap = c.get_calibration(qubits)
    except Exception as err:  # noqa: BLE001
        _fail(err)
        return
    click.echo(json_format.MessageToJson(snap))


@remote.command("run")
@_remote_options
@click.argument("job_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--shots", "-s", type=int, default=None, help="Override num_shots")
@click.option("--output", "-o", type=click.Path(dir_okay=False), default=None, help="Save results as JSON")
def remote_run(target: str, ca: str | None, token: str | None, timeout: float, insecure: bool,
               job_path: str, shots: int | None,
               output: str | None):
    """Submit a job, wait for it, stream the results and print the readout counts."""
    from qcss.client import counts
    from qcss.v1 import job_pb2 as jpb
    from qcss.v1 import result_pb2

    job = _load_job_file(job_path)
    if shots is not None:
        job.num_shots = shots
    t0 = time.perf_counter()
    try:
        with _client(target, ca, token, timeout, insecure) as c:
            job_id, epoch = c.submit(job)
            click.echo(f"Submitted {job_id} (calibration epoch {epoch})")
            st = c.wait(job_id)
            chunks = list(c.results(job_id))
    except Exception as err:  # noqa: BLE001
        _fail(err)
        return
    elapsed = time.perf_counter() - t0
    state = result_pb2.JobState.Name(st.state)
    click.echo(f"{state} in {elapsed:.2f} s on tier {jpb.FidelityTier.Name(st.tier_used)}; {len(chunks)} chunk(s)")
    if st.message:
        click.echo(f"  message: {st.message}")
    keys = sorted({a.result_key for ch in chunks for a in ch.acquisitions})
    per_key = {k: counts(chunks, [k]) for k in keys}
    for k, cnt in per_key.items():
        click.echo(f"  {k}: {dict(sorted(cnt.items()))}")
    joint = counts(chunks, keys) if keys else {}
    if len(keys) > 1:
        click.echo(f"  joint ({', '.join(reversed(keys))}): {dict(sorted(joint.items()))}")
    points: dict[tuple[int, ...], list] = {}
    for ch in chunks:
        points.setdefault(tuple(ch.sweep_point), []).append(ch)
    per_point = [{"sweep_point": list(p), "counts": counts(cs, keys)} for p, cs in sorted(points.items())]
    if any(p for p in points):
        click.echo(f"  per sweep point ({', '.join(reversed(keys))}):")
        for p in per_point:
            click.echo(f"    point {p['sweep_point']}: {dict(sorted(p['counts'].items()))}")
    if output:
        pathlib.Path(output).write_text(json.dumps({
            "job_id": job_id, "state": state, "calibration_epoch": epoch, "elapsed_seconds": elapsed,
            "tier": jpb.FidelityTier.Name(st.tier_used), "chunks": len(chunks), "keys": keys,
            "counts": joint, "counts_per_key": per_key, "counts_per_point": per_point,
            "warnings": sorted({w for ch in chunks for w in ch.warnings})}, indent=2), encoding="utf-8")
        click.echo(f"Saved results to: {pathlib.Path(output).resolve()}")
    sys.exit(0 if st.state == result_pb2.JOB_STATE_COMPLETED else 1)



# ---------------------------------------------------------------------- virtual technician
RUNCARDS_DIR = pathlib.Path(__file__).parent / "technician" / "runcards"
# What each request scope runs, and how long it takes on a 5-qubit chip (the ETA in the acknowledgement).
CALIBRATION_SCOPES = {"quick": ("quick.yml", 900.0), "device": ("full.yml", 3600.0), "cz": ("cz.yml", 7200.0)}


@app.group("technician")
def technician():
    """The lab's calibration staff: Qibocal runs on a schedule and on request, writing the platform."""


@technician.command("request")
@click.option("--requests-dir", type=click.Path(file_okay=False), required=True, help="The technician's request spool")
@click.option("--scope", type=str, default="device", show_default=True,
              help=f"What to calibrate: {', '.join(CALIBRATION_SCOPES)}")
def technician_request(requests_dir: str, scope: str):
    """Ask for a calibration (the hook a Quark adapter's request_calibration calls); prints the acknowledgement."""
    from qcss.technician.schedule import request_calibration
    eta = CALIBRATION_SCOPES.get(scope, ("", 0.0))[1]
    ack = request_calibration(pathlib.Path(requests_dir), [scope], expected_duration_s=eta,
                              known_scopes=CALIBRATION_SCOPES)
    click.echo(json.dumps(ack))
    if not ack["accepted"]:
        sys.exit(1)


@technician.command("run")
@click.option("--platforms-dir", type=click.Path(exists=True, file_okay=False), required=True,
              help="Folder of Qibolab platforms (QIBOLAB_PLATFORMS)")
@click.option("--platform", required=True, help="Platform to keep calibrated, e.g. qcss_qblox_5q")
@click.option("--reports", type=click.Path(file_okay=False), required=True, help="Where Qibocal's reports go")
@click.option("--requests-dir", type=click.Path(file_okay=False), required=True, help="The request spool")
@click.option("--env", "env_pairs", multiple=True, help="NAME=VALUE for Qibocal's environment (instrument address)")
@click.option("--quick-every", type=click.FloatRange(min=1), default=4 * 3600.0, show_default=True, help="Seconds")
@click.option("--full-every", type=click.FloatRange(min=1), default=86400.0, show_default=True, help="Seconds")
@click.option("--cz-every", type=click.FloatRange(min=1), default=7 * 86400.0, show_default=True, help="Seconds")
@click.option("--poll", type=click.FloatRange(min=0.1), default=30.0, show_default=True, help="Idle poll period, s")
def technician_run(platforms_dir: str, platform: str, reports: str, requests_dir: str, env_pairs: tuple[str, ...],
                   quick_every: float, full_every: float, cz_every: float, poll: float):
    """Keep a platform calibrated: requests first, then quick checks, full bring-ups and CZ as they come due."""
    from qcss.technician import Technician
    from qcss.technician.schedule import Shift
    bad = [p for p in env_pairs if "=" not in p or not p.split("=", 1)[0]]
    if bad:
        raise click.BadParameter(f"expected NAME=VALUE, got {bad[0]!r}", param_hint="--env")
    env = dict(p.split("=", 1) for p in env_pairs)
    tech = Technician(pathlib.Path(platforms_dir), platform, reports=pathlib.Path(reports), env=env)
    cards = {k: RUNCARDS_DIR / f for k, (f, _) in CALIBRATION_SCOPES.items()}

    def calibrate(runcard: pathlib.Path):
        outcome = tech.calibrate(runcard)
        click.echo(f"{runcard.stem}: {'ok' if outcome.ok else 'FAILED'} ({outcome.report_dir})")
        return outcome
    shift = Shift(calibrate, {cards["quick"]: quick_every, cards["device"]: full_every, cards["cz"]: cz_every},
                  pathlib.Path(requests_dir), cards,
                  state_file=pathlib.Path(reports) / "technician-state.json")
    try:
        while True:
            if not shift.step():
                time.sleep(poll)
    except KeyboardInterrupt:
        click.echo("\nTechnician off shift.")


if __name__ == "__main__":
    app()
