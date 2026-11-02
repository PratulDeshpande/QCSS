"""Generate the *_pb2.py, *_pb2.pyi and service *_pb2_grpc.py modules under src/qcss from proto/qcss/**/*.proto.

Offline and Windows-friendly: runs grpc_tools.protoc (dev dependency), so the .proto files
are the single source of truth. Generated code is committed; CI regenerates and fails on a
diff. Never point an output at src/ with a "clean" step: it would delete the whole tree.

    python scripts/gen_proto.py
"""
from __future__ import annotations

import pathlib
import sys

from grpc_tools import protoc

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROTO = ROOT / "proto"
OUT = ROOT / "src"
SERVICES = {"control_service.proto", "admin.proto"}          # only files with a service get a *_pb2_grpc.py


def main() -> int:
    include = pathlib.Path(protoc.__file__).parent / "_proto"
    files = sorted(p.relative_to(PROTO).as_posix() for p in (PROTO / "qcss").rglob("*.proto"))
    rc = protoc.main(["grpc_tools.protoc", f"-I{PROTO}", f"-I{include}", f"--python_out={OUT}",
                      f"--pyi_out={OUT}", f"--grpc_python_out={OUT}", *files])
    if rc != 0:
        return rc
    for f in files:                           # protoc writes an empty *_grpc.py for message-only files
        name = pathlib.PurePosixPath(f).name
        if name not in SERVICES:
            (OUT / pathlib.PurePosixPath(f).with_name(name.replace(".proto", "_pb2_grpc.py"))).unlink(missing_ok=True)
    print(f"generated {len(files)} proto modules under {OUT / 'qcss'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
