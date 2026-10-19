# Contributing to QCSS

Thanks for helping. QCSS is judged by one question: *can a quantum OS talk to it exactly as it talks
to hardware, and trust the answers?* Contributions are welcome when they move that forward and stay
honest about what is verified and what is not.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). Contributions are licensed
under the project's [Apache-2.0 license](LICENSE).

## Set up

```bash
git clone https://github.com/PratulDeshpande/qcss.git
cd qcss
python -m pip install -e . --group dev      # needs pip 25.1+; Python 3.12 or 3.13
python -m pytest                            # about a minute
```

## Checks to run before opening a pull request

```bash
python -m pytest                       # must pass
ruff check src tests scripts integrations   # must be clean
pyright                                # must report 0 errors
python scripts/gen_proto.py            # only if you edited a .proto file
```

CI runs the same checks on Linux and Windows (Python 3.12 and 3.13). It also regenerates the protobuf
code and fails if the committed files in `src/qcss/v1/` differ, so commit regenerated code together
with the `.proto` change.

> **Typing tips.** Some third-party stubs are stricter than the libraries. Prefer `np.real(x)` /
> `np.imag(x)` over `x.real` / `x.imag` on loosely typed arrays, and `@` (not `*`) for qutip operator
> products. Keep `# pyright: ignore[rule]` for genuine upstream stub bugs, with a comment saying why.

## Ground rules

* **The `.proto` files are the product.** Changes must keep `buf lint` (STANDARD) clean and must not
  break the wire format (`buf breaking`, WIRE_JSON). Every enum keeps `*_UNSPECIFIED = 0`.
* **Hardware numbers are data with a source.** A new or changed profile value needs a `provenance`
  block (`source_url`, `firmware_version` where known, `verified`). If you cannot source it, mark it
  `verified: false`. Never hard-code a vendor constant in Python.
* **Each error enters exactly once.** Decoherence enters through the physics engine, readout error
  through the readout model, drift through the device state. Double counting produces results that
  look plausible and are wrong.
* **Refuse, don't approximate.** If a tier cannot honour a job, the router refuses with a reason; it
  never silently runs a cheaper model.
* **Time is an integer number of ticks.** Convert to nanoseconds only at API edges.
* **Randomness is keyed, not global.** Draw from `qcss.core.seeding.stream(...)`; never use Python's
  `hash()` or an unseeded generator, or seeded jobs stop reproducing.

## Tests

Tests are the specification. New physics comes with an analytic oracle (a closed-form result compared
within a stated statistical tolerance, such as 5σ binomial), not a number copied from a run.

| Directory | What it holds |
|---|---|
| `tests/unit/` | One file per module, plus Hypothesis property tests |
| `tests/oracles/` | Physics compared with analytic formulas through the real runtime |
| `tests/cross_tier/` | Tiers agree where their domains overlap |
| `tests/integration/` | gRPC end to end, calibration epochs, feedback timing |

Use the `stochastic` and `slow` markers for statistical and long-running tests. Do not hard-code
network ports: bind to port 0 or use the `_free_port()` helper in the gRPC tests.

## Style

* `ruff` with the settings in `pyproject.toml` (line length 120). Generated `*_pb2*` files are excluded.
* Match the surrounding code's naming and comment density. Comments explain *why*, not what.
* Keep pull requests focused: one concern per PR, with a description of what changed and how you
  checked it.

## Reporting bugs and requesting features

Use the issue templates. For a bug, a minimal job file and the exact command are the most useful
things you can include. For security problems, see [SECURITY.md](SECURITY.md) and do not open a public
issue.
