"""The technician's runcards load into Qibocal and give every routine what it requires."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import yaml

P = pytest.importorskip("qibocal.protocols", reason="the qibocal extra is not installed")
RUNCARDS = Path("src/qcss/technician/runcards")


@pytest.mark.parametrize("name", ["quick", "full", "cz"])
def test_a_runcard_names_real_routines_with_their_required_parameters(name):
    from qibocal.auto.runcard import Runcard
    raw = yaml.safe_load((RUNCARDS / f"{name}.yml").read_text(encoding="utf-8"))
    card = Runcard.load(raw)
    assert card.actions
    for action in card.actions:
        op = getattr(P, action.operation)
        required = {f.name for f in dataclasses.fields(op.parameters_type)
                    if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING}
        assert required <= set(action.parameters or {}), (action.id, required - set(action.parameters or {}))
