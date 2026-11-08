# QCSS Documentation

**Created and maintained by [Pratul Deshpande](about.md)** ([@PratulDeshpande](https://github.com/PratulDeshpande))

Structure follows [Diátaxis](https://diataxis.fr/) (tutorials, how-to, reference, explanation).

| You are... | Start here |
|---|---|
| A host-laptop user, new to QICK | [QICK from a host](quickstart/qick-from-a-host.md) |
| A host-laptop user, new to Qibolab | [Qibolab from a host](quickstart/qibolab-from-a-host.md) |
| Learning by doing | [Tutorials](tutorials/01-first-job.md) |
| Looking for a recipe | [How-to guides](howto/pick-a-physics-tier.md) |
| Looking up a flag or field | [Reference](reference/cli.md) |
| Wanting the whole picture | [User manual](manual/00-overview-and-glossary.md) |
| Project background & author | [About the Author](about.md) |

## Status
| Item | State |
|---|---|
| QICK quick-start | written, verified on loopback |
| Qibolab quick-start | written, verified on loopback |
| Qibosoq quick-start | written, verified on loopback |
| Reference (CLI, env/ports, config fields, gRPC/admin, QICK surface) | written |
| Architecture, ops/security, developer guide, release notes | written (draft) |
| User manual (manual/00-09) | written, partly verified (see each chapter) |
| Tutorials (4), how-tos (6), troubleshooting | written, verified on loopback where marked |
| PDF of the manual | `build/QCSS-User-Manual.pdf`, rebuild with `bash build/build-manual.sh` (needs pandoc + xelatex) |

## Author & Citation

QCSS is authored and maintained by **Pratul Deshpande**. To learn more about the simulator's architecture and origin, see [About the Author](about.md).

If you use QCSS in research, education, or testing, please cite it:

```bibtex
@software{Deshpande_QCSS_2026,
  author  = {Deshpande, Pratul},
  title   = {QCSS: Quantum Control Stack Simulator},
  year    = {2026},
  url     = {https://github.com/PratulDeshpande/QCSS},
  license = {Apache-2.0}
}
```
