"""Insert TikZ figures into a manual chapter at the end of a named section (build copy only; the chapters stay clean).

usage: inject_figs.py CHAPTER.md DIAGRAM_DIR [ORIGINAL_NAME]   (prints the new markdown on stdout)
"""
import re
import sys
from pathlib import Path

# chapter file -> [(heading prefix, diagram name, caption)]
FIGS = {
    "00-overview-and-glossary.md": [
        ("## 0.2 The pieces", "system-overview", "QCSS at a glance: client software, the three faces, the chassis, and the operator side."),
        ("## 0.3 How a job flows", "job-flow", "The five stages a job passes through inside the chassis, and where it can be refused."),
    ],
    "02-faces.md": [
        ("# Chapter 2", "faces", "The three faces: each reaches the same job manager and the same simulated chip."),
    ],
    "04-qpu-physics.md": [
        ("### AUTO routing", "tier-routing", "How the router picks a physics tier. It refuses rather than downgrading silently."),
        ("## 4.5 Signal chain", "signal-chain", "From programmed samples to what the qubit feels, and back to a measurement result."),
    ],
    "05-runtime-jobs-and-calibration.md": [
        ("### Plan, refusal and states", "job-states", "Job states. The protocol also defines VALIDATING."),
        ("## 5.2 Calibration", "calibration-epoch", "Calibration updates are compare-and-swap on the epoch."),
    ],
    "06-admin-channel-and-faults.md": [
        ("# Chapter 6", "admin-planes", "The lab plane and the admin plane are separate services with separate tokens."),
    ],
    "07-explorer-dashboard.md": [
        ("## 7.1 Running it", "explorer-architecture", "Explorer architecture: browser, bridge, and an embedded or an existing chassis."),
    ],
    "08-security.md": [
        ("## 8.1 Four listeners", "listeners", "The listeners a chassis can open and what protects each."),
    ],
}


def figure(diagrams: Path, name: str, caption: str) -> str:
    path = (diagrams / f"{name}.tex").as_posix()
    return f"```{{=latex}}\n\\begin{{figure}}[H]\n\\centering\n{{\\hyphenpenalty=10000 \\exhyphenpenalty=10000 \\input{{{path}}}}}\n\\caption{{{caption}}}\n\\end{{figure}}\n```\n"


def main(chapter: Path, diagrams: Path, name: str) -> str:
    lines = chapter.read_text(encoding="utf-8").splitlines()
    pending = list(FIGS.get(name, []))
    out, in_fence, waiting = [], False, None  # waiting: the figure for the section we are inside
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and re.match(r"#{1,6} ", line) and waiting is not None:
            out += ["", figure(diagrams, *waiting), ""]
            waiting = None
        out.append(line)
        if not in_fence and waiting is None:
            for p in pending:
                if line.startswith(p[0]):
                    waiting = (p[1], p[2])
                    pending.remove(p)
                    break
    if waiting is not None:
        out += ["", figure(diagrams, *waiting)]
    if pending:
        sys.exit(f"{name}: heading not found: {[p[0] for p in pending]}")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    src = Path(sys.argv[1])
    sys.stdout.write(main(src, Path(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else src.name))
