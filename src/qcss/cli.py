"""Command-line interface (CLI) for the Quantum Control Stack Simulator (QCSS)."""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import time
from typing import Any

import click
import numpy as np
import yaml
from google.protobuf import json_format

from qcss.adapters.grpc_server import UnsafeBindError, check_bind_is_safe, describe_device, serve
from qcss.config.loader import get_unverified_fields, load_device, load_profile
from qcss.core.errors import HardwareValidationError, TierRoutingError
from qcss.core.ndarray import from_proto
from qcss.core.timebase import TimeBase
from qcss.runtime.jobs import JobManager
from qcss.runtime.runner import SimulationContext, create_simulation_runner, create_simulation_validator
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


@app.command("serve")
@click.option("--host", "-h", default="127.0.0.1", help="gRPC host bind address (never 0.0.0.0 without TLS)")
@click.option("--port", "-p", type=int, default=50051, help="gRPC port")
@click.option("--listen", default=None, help="Full address instead of host:port, e.g. unix:C:/Users/me/qcss.sock")
@click.option("--profile", default="qblox_cluster_5q", help="Hardware profile name or path")
@click.option("--device", default=None, help="Device specification path or name")
@click.option("--workers", type=int, default=0, help="Spawn worker processes for simulation (0 = one thread)")
@click.option("--seed", type=int, default=0, help="Global seed of the server's random-stream tree")
@click.option("--tls-cert", type=click.Path(dir_okay=False), default=None, help="PEM server certificate (chain)")
@click.option("--tls-key", type=click.Path(dir_okay=False), default=None, help="PEM private key of --tls-cert")
@click.option("--token", envvar="QCSS_TOKEN", default=None,
              help="Require 'authorization: Bearer <token>' on every call (env QCSS_TOKEN)")
@click.option("--insecure", is_flag=True, help="Allow a network bind without TLS (trusted networks only)")
def serve_cmd(host: str, port: int, listen: str | None, profile: str, device: str | None, workers: int, seed: int,
              tls_cert: str | None, tls_key: str | None, token: str | None, insecure: bool):
    """Launch the QCSS gRPC ControlService server."""
    addr = listen or f"{host}:{port}"
    if (tls_cert is None) != (tls_key is None):
        raise click.UsageError("pass both --tls-cert and --tls-key, or neither")
    try:
        check_bind_is_safe(addr, tls=tls_cert is not None, insecure=insecure)
    except UnsafeBindError as err:
        raise click.UsageError(str(err)) from err
    tls = (pathlib.Path(tls_cert).read_bytes(), pathlib.Path(tls_key).read_bytes()) if tls_cert and tls_key else None

    p_path = _resolve_profile_path(profile)
    prof = load_profile(p_path)
    d_path = _resolve_device_path(device)
    dev = load_device(d_path) if d_path else None
    tb = TimeBase.from_clocks(prof.clock.tick_hz)

    security = ("TLS" if tls else "plaintext") + (", token required" if token else ", no token")
    click.echo(f"Starting QCSS ControlService on {addr} ({security}) with profile '{prof.profile_name}'...")

    async def run_server():
        ctx = SimulationContext(prof, dev, tb, global_seed=seed)
        runner = create_simulation_runner(prof, dev, tb, context=ctx, workers=workers)
        jobs = JobManager(runner, create_simulation_validator(prof, tb, dev, context=ctx))
        server = await serve(addr, jobs, describe_device(prof, ctx.bindings), ctx.calibration, tls=tls, token=token)
        click.secho(f"QCSS ControlService listening on {addr}. Press Ctrl+C to terminate.", fg="green")
        try:
            await server.wait_for_termination()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await server.stop(grace=1.0)
            await jobs.close()

    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        click.echo("\nServer terminated by user.")


if __name__ == "__main__":
    app()
