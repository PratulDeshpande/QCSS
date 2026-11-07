#!/usr/bin/env bash
# Builds QCSS-User-Manual.pdf from ../manual/0*.md plus the TikZ diagrams in diagrams/.
# Needs pandoc, xelatex (MiKTeX) and python. Chapters stay plain Markdown; figures are inserted into a temp copy.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
if command -v cygpath >/dev/null; then DIAG="$(cygpath -m "$HERE/diagrams")"; else DIAG="$HERE/diagrams"; fi
T=$(mktemp -d)
mkdir "$T/ch"
for f in "$HERE"/../manual/0*.md; do
  n="$(basename "$f")"
  # drop the repeated book title, promote "Chapter N" to H1, blank line after rules (else pandoc eats the next chapter)
  # also drop the backticks on "Sources:" lines so those long path lists can wrap instead of running off the page
  sed -e '1{/^# QCSS User Manual/d}' -e 's/^## Chapter /# Chapter /' -e 's/^---$/\n---\n/' -e '/^Sources:/s/`//g' "$f" > "$T/ch/$n"
  python "$HERE/inject_figs.py" "$T/ch/$n" "$DIAG" "$n" > "$T/$n"
  printf '\n\\newpage\n\n' >> "$T/$n"
done
cd "$T"
pandoc -f markdown-yaml_metadata_block 0*.md -H "$HERE/diagrams/header.tex" -o "$HERE/QCSS-User-Manual.pdf" --pdf-engine=xelatex \
  --toc --toc-depth=2 -V geometry:margin=2.2cm -V fontsize=10pt -V colorlinks=true \
  -M author="Pratul Deshpande" -M title="QCSS User Manual" -M subtitle="Quantum Control Stack Simulator, version 0.1.0" \
  -M date="$(date +%F)" -V monofont="Consolas" -V mainfont="Calibri"
