"""The "does it look like real hardware?" checks the notebooks run. Each is an assert, so nbmake fails a
notebook whose client stops seeing a real-looking instrument, rather than printing something different."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

_SURFACE = Path(__file__).resolve().parents[1] / "src/qcss/boards/qick/surface.json"


def qick_surface(soc, soccfg) -> None:
    """What the QICK client sees through Pyro4 matches the real QickSoc recorded in surface.json."""
    surface = json.loads(_SURFACE.read_text())
    real = set(surface["objects"]["soc"])
    soc._pyroBind()                                    # fetch the remote metadata, as any first call does
    served = set(soc._pyroMethods)
    extra = served - real
    assert not extra, f"the board serves methods a real QickSoc lacks: {sorted(extra)}"
    assert type(soc).__module__.startswith("Pyro4"), "soc should be a Pyro4 proxy, as with a real board"
    assert type(soccfg).__name__ == "QickConfig", "soccfg should be qick's own QickConfig"
    print(f"client: Pyro4 proxy to '{soc._pyroUri.object}' at {soc._pyroUri.host}")
    print("board, as qick describes it:", *str(soccfg).splitlines()[:3], sep="\n  ")
    print(f"remote surface: {len(served)} of the real board's {len(real)} methods served, none extra  ✓")


def result_shape(name: str, value, shape: tuple | None = None, dtype=None) -> None:
    """A returned array has the type, shape and dtype the real instrument returns."""
    arr = np.asarray(value)
    if shape is not None:
        assert arr.shape == tuple(shape), f"{name}: shape {arr.shape}, expected {tuple(shape)}"
    if dtype is not None:
        assert np.issubdtype(arr.dtype, dtype), f"{name}: dtype {arr.dtype}, expected {np.dtype(dtype)}"
    print(f"{name:<24} {type(value).__name__:<10} shape {str(arr.shape):<14} dtype {arr.dtype}  ✓")


def truth_table(rows: list[tuple[str, float, float, float]]) -> None:
    """rows: (quantity, measured, true, relative tolerance). Prints the comparison and asserts each row."""
    print(f"{'quantity':<26}{'measured':>16}{'true (admin)':>16}{'error':>10}{'tol':>8}")
    bad = []
    for name, measured, true, tol in rows:
        err = abs(measured - true) / abs(true)
        ok = err <= tol
        bad += [] if ok else [name]
        print(f"{name:<26}{measured:>16.6g}{true:>16.6g}{err:>9.2%}{tol:>8.0%}  {'✓' if ok else '✗'}")
    assert not bad, f"outside tolerance: {bad}"


def gap(reason: str, ref: str) -> None:
    """Show a known QCSS gap plainly instead of hiding a skipped cell."""
    text = f"**QCSS gap — skipped.** {reason} (see `{ref}`)"
    try:
        from IPython.display import Markdown, display
        display(Markdown(f"> ⚠️ {text}"))
    except ImportError:
        print("WARNING:", text)
