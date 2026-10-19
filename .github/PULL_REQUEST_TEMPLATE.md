## What and why

<!-- What does this change, and what problem does it solve? Link the issue if there is one. -->

## How it was checked

<!-- Paste the relevant output, or describe the test you added. -->

- [ ] `python -m pytest` passes
- [ ] `ruff check src tests scripts` is clean
- [ ] New behaviour has a test (an analytic oracle where the change affects physics)
- [ ] If a `.proto` file changed: `python scripts/gen_proto.py` was run and the generated code is included
- [ ] If a hardware profile value changed: its `provenance` (source URL, `verified`) is updated
- [ ] User-visible changes are noted in `CHANGELOG.md`
