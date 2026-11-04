"""Freeze the remote surface of a QICK board, as the installed qick client sees it.

Reads the qick sources with ``ast`` (``qick.qick`` imports pynq, which only exists on a board) and writes
``src/qcss/boards/qick/surface.json``:

- every public method of ``QickSoc`` (and its ``QickConfig`` base), of both tProc drivers and of the
  ``DataStreamer``, with its parameter names and defaults, since over Pyro4 a client may call any of them;
- every ``soc.<method>(`` call the client-side program code makes (``acquire``, ``run_rounds``, ...),
  the calls an unmodified QICK program actually sends to the board.

The native QICK face is checked against this file, so a qick upgrade that adds or changes a remote call
fails a test instead of failing in front of a user.

    python scripts/qick_surface.py            # write the file for the installed qick
    python scripts/qick_surface.py --check    # exit 1 if the file is out of date
"""
from __future__ import annotations

import argparse
import ast
import importlib.metadata
import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "qcss" / "boards" / "qick" / "surface.json"
# (module file, class name) for each remote object a client reaches through the soc proxy
CLASSES = {
    "soc": [("qick.py", "QickSoc"), ("qick_asm.py", "QickConfig")],
    "tproc_v1": [("drivers/tproc.py", "AxisTProc64x32_x8")],
    "tproc_v2": [("drivers/tproc.py", "Axis_QICK_Proc")],
    "streamer": [("streamer.py", "DataStreamer")],
}
# client-side modules whose methods call the board: QickProgram, AveragerProgramV2, the v1 averagers
CLIENT_MODULES = ["qick_asm.py", "asm_v1.py", "asm_v2.py", "averager_program.py"]


def _qick_dir() -> Path:
    spec = importlib.util.find_spec("qick")
    if spec is None or spec.origin is None:
        sys.exit("qick is not installed: pip install qick==0.2.370 (see CONTRIBUTING.md)")
    return Path(spec.origin).parent


def _default(node: ast.expr | None) -> object:
    if node is None:
        return "<required>"
    try:
        return ast.literal_eval(node)
    except ValueError:
        return ast.unparse(node)


def _params(fn: ast.FunctionDef) -> list[dict[str, object]]:
    a = fn.args
    pos = a.posonlyargs + a.args
    defaults = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    out = [{"name": p.arg, "default": _default(d)} for p, d in zip(pos, defaults, strict=True)][1:]  # drop self
    if a.vararg:
        out.append({"name": "*" + a.vararg.arg, "default": "<varargs>"})
    out += [{"name": p.arg, "default": _default(d)} for p, d in zip(a.kwonlyargs, a.kw_defaults, strict=True)]
    if a.kwarg:
        out.append({"name": "**" + a.kwarg.arg, "default": "<kwargs>"})
    return out


def _methods(tree: ast.Module, cls: str) -> dict[str, list[dict[str, object]]]:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            return {f.name: _params(f) for f in node.body
                    if isinstance(f, ast.FunctionDef) and not f.name.startswith("_")}
    raise SystemExit(f"class {cls} not found: the qick layout changed, update CLASSES in {__file__}")


def _client_calls(tree: ast.Module) -> set[str]:
    calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            chain, v = [node.func.attr], node.func.value
            while isinstance(v, ast.Attribute):
                chain.append(v.attr)
                v = v.value
            if isinstance(v, ast.Name) and v.id == "soc":
                calls.add(".".join(reversed(chain)))
    return calls


def build() -> dict[str, object]:
    root = _qick_dir()
    parsed: dict[str, ast.Module] = {}

    def tree(rel: str) -> ast.Module:
        if rel not in parsed:
            parsed[rel] = ast.parse((root / rel).read_text(encoding="utf-8"), filename=rel)
        return parsed[rel]

    objects: dict[str, dict[str, list[dict[str, object]]]] = {}
    for obj, classes in CLASSES.items():
        merged: dict[str, list[dict[str, object]]] = {}
        for rel, cls in reversed(classes):            # the first class listed wins, as in its MRO
            merged.update(_methods(tree(rel), cls))
        objects[obj] = dict(sorted(merged.items()))
    calls = sorted(set().union(*(_client_calls(tree(m)) for m in CLIENT_MODULES)))
    return {"qick_version": importlib.metadata.version("qick"), "objects": objects, "client_calls": calls,
            "source_lines": _source_lines(tree, CLASSES["soc"])}


def _source_lines(tree: Callable[[str], ast.Module], classes: list[tuple[str, str]]) -> dict[str, list[object]]:
    """Where each QickSoc method is defined ([qick-relative file, line]): the frame a board's traceback shows."""
    lines: dict[str, list[object]] = {}
    for rel, cls in reversed(classes):
        for node in tree(rel).body:
            if isinstance(node, ast.ClassDef) and node.name == cls:
                for f in node.body:
                    if isinstance(f, ast.FunctionDef) and not f.name.startswith("_"):
                        lines[f.name] = [rel, f.lineno]
    return dict(sorted(lines.items()))


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if surface.json differs from the installed qick")
    args = ap.parse_args()
    text = json.dumps(build(), indent=1) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            sys.exit(f"{OUT} is out of date: run python scripts/qick_surface.py")
        print("surface.json is current")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
