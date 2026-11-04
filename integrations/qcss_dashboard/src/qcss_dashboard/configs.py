"""Config store: shipped profiles and devices, user copies in the workspace, validation and diffs.

Shipped files (src/qcss/config/{profiles,devices}) are read-only: a draft is always saved under a new name in the user
workspace, so the dashboard can never corrupt the repository's reference hardware or chip.
"""
from __future__ import annotations

import difflib
import pathlib
import re
import typing
import warnings
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

import qcss.config as _cfg_pkg
from qcss.config.device import DeviceSpec
from qcss.config.loader import get_unverified_fields
from qcss.config.profile import HardwareProfile

BUILTIN = pathlib.Path(_cfg_pkg.__file__).parent
KINDS: dict[str, tuple[str, type[BaseModel]]] = {"profile": ("profiles", HardwareProfile),
                                                 "device": ("devices", DeviceSpec)}
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class ConfigError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _kind(kind: str) -> tuple[str, type[BaseModel]]:
    if kind not in KINDS:
        raise ConfigError(f"unknown config kind '{kind}' (expected profile or device)", 404)
    return KINDS[kind]


def _flatten(data: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(data, list) and data and all(isinstance(x, dict) for x in data):
        for i, v in enumerate(data):
            out.update(_flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = data
    return out


def registry_key(model: type[BaseModel], path: str) -> str | None:
    """'qubits[1].t1_us' under DeviceSpec -> 'QubitSpec.t1_us' (the registry entry describing it)."""
    cur: Any = model
    parts = re.sub(r"\[\d+\]", "", path).split(".")
    for i, name in enumerate(parts):
        if not (isinstance(cur, type) and issubclass(cur, BaseModel)) or name not in cur.model_fields:
            return None
        if i == len(parts) - 1:
            return f"{cur.__name__}.{name}"
        stack: list[Any] = [cur.model_fields[name].annotation]
        nxt = None
        while stack:
            t = stack.pop()
            if isinstance(t, type) and issubclass(t, BaseModel):
                nxt = t
                break
            stack.extend(typing.get_args(t))
        cur = nxt
    return None


class ConfigStore:
    def __init__(self, workspace: pathlib.Path) -> None:
        self.user_root = pathlib.Path(workspace) / "configs"

    def _dirs(self, kind: str) -> tuple[pathlib.Path, pathlib.Path]:
        sub, _ = _kind(kind)
        return BUILTIN / sub, self.user_root / sub

    def list(self, kind: str) -> list[dict[str, str]]:
        builtin, user = self._dirs(kind)
        out = [{"name": p.stem, "source": "builtin"} for p in sorted(builtin.glob("*.yaml"))]
        if user.exists():
            out += [{"name": p.stem, "source": "user"} for p in sorted(user.glob("*.yaml"))]
        return out

    def path(self, kind: str, name: str) -> tuple[pathlib.Path, str]:
        builtin, user = self._dirs(kind)
        if not _NAME.match(name):
            raise ConfigError(f"invalid config name '{name}'")
        for d, src in ((builtin, "builtin"), (user, "user")):
            p = d / f"{name}.yaml"
            if p.exists():
                return p, src
        raise ConfigError(f"no {kind} named '{name}'", 404)

    def read(self, kind: str, name: str) -> dict[str, Any]:
        p, src = self.path(kind, name)
        text = p.read_text(encoding="utf-8")
        res = self.validate(kind, text)
        return {"kind": kind, "name": name, "source": src, "yaml": text, "data": res.get("data"),
                "unverified": res.get("unverified", []), "ok": res["ok"], "errors": res["errors"],
                "warnings": res["warnings"]}

    def validate(self, kind: str, text: str) -> dict[str, Any]:
        _, model = _kind(kind)
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            return {"ok": False, "errors": [{"loc": "", "msg": f"YAML: {exc}"}], "warnings": []}
        if not isinstance(raw, dict):
            return {"ok": False, "errors": [{"loc": "", "msg": "the file must be a YAML mapping"}], "warnings": []}
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                obj = model.model_validate(raw)
            except ValidationError as exc:
                errs = [{"loc": ".".join(str(x) for x in e["loc"]), "msg": e["msg"]} for e in exc.errors()]
                return {"ok": False, "errors": errs, "warnings": [str(w.message) for w in caught]}
        out: dict[str, Any] = {"ok": True, "errors": [], "warnings": [str(w.message) for w in caught],
                               "data": obj.model_dump(mode="json")}
        if isinstance(obj, HardwareProfile):
            out["unverified"] = get_unverified_fields(obj)
        return out

    def diff(self, kind: str, base: str, text: str) -> dict[str, Any]:
        _, model = _kind(kind)
        p, _ = self.path(kind, base)
        before_text = p.read_text(encoding="utf-8")
        before = _flatten(yaml.safe_load(before_text) or {})
        try:
            after = _flatten(yaml.safe_load(text) or {})
        except yaml.YAMLError as exc:
            raise ConfigError(f"YAML: {exc}") from exc
        changes = []
        for k in sorted(set(before) | set(after)):
            if (k in before) != (k in after) or before.get(k) != after.get(k):
                changes.append({"path": k, "before": before.get(k), "after": after.get(k),
                                "key": registry_key(model, k)})
        unified = "".join(difflib.unified_diff(before_text.splitlines(True), text.splitlines(True),
                                               fromfile=f"{base}.yaml", tofile="draft.yaml"))
        return {"changes": changes, "unified": unified}

    def save(self, kind: str, name: str, text: str) -> dict[str, Any]:
        builtin, user = self._dirs(kind)
        if not _NAME.match(name):
            raise ConfigError(f"invalid config name '{name}' (letters, digits, _ . - only)")
        if (builtin / f"{name}.yaml").exists():
            raise ConfigError(f"'{name}' is a shipped {kind}; save the draft under a new name")
        res = self.validate(kind, text)
        if not res["ok"]:
            raise ConfigError("; ".join(f"{e['loc']}: {e['msg']}" for e in res["errors"]))
        user.mkdir(parents=True, exist_ok=True)
        (user / f"{name}.yaml").write_text(text, encoding="utf-8")
        return {"kind": kind, "name": name, "source": "user"}

    def load_profile(self, name: str) -> HardwareProfile:
        p, _ = self.path("profile", name)
        return HardwareProfile.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")))

    def load_device(self, name: str | None) -> DeviceSpec | None:
        if not name:
            return None
        p, _ = self.path("device", name)
        return DeviceSpec.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")))

    def profile_from(self, name: str | None, text: str | None) -> HardwareProfile:
        """A profile from draft text when given, else by name."""
        if text:
            obj = self._from_text("profile", text)
            assert isinstance(obj, HardwareProfile)
            return obj
        return self.load_profile(name or "qblox_cluster_5q")

    def device_from(self, name: str | None, text: str | None) -> DeviceSpec | None:
        if text:
            obj = self._from_text("device", text)
            assert isinstance(obj, DeviceSpec)
            return obj
        return self.load_device(name)

    def _from_text(self, kind: str, text: str) -> BaseModel:
        res = self.validate(kind, text)
        if not res["ok"]:
            raise ConfigError("; ".join(f"{e['loc']}: {e['msg']}" for e in res["errors"]))
        _, model = _kind(kind)
        return model.model_validate(yaml.safe_load(text))
