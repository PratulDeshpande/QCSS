"""Bridge settings. Tokens live here and only here: no route ever serializes them."""
from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field


def _default_workspace() -> pathlib.Path:
    return pathlib.Path(os.environ.get("QCSS_DASHBOARD_HOME", pathlib.Path.home() / ".qcss-dashboard"))


@dataclass
class Settings:
    workspace: pathlib.Path = field(default_factory=_default_workspace)   # user configs, audit log, chip state
    lab_target: str | None = "127.0.0.1:50051"
    admin_target: str | None = "127.0.0.1:50052"
    lab_token: str | None = field(default=None, repr=False)
    admin_token: str | None = field(default=None, repr=False)
    ca_file: pathlib.Path | None = None
    access_token: str | None = field(default=None, repr=False)          # dashboard login, required off-loopback
    read_only: bool = False
    embedded_chassis: bool = True             # run a chassis inside the bridge (local virtual lab)
    chassis_profile: str = "qblox_cluster_5q"
    chassis_device: str | None = "transmon_5q"
    chassis_time_scale: float = 1.0
    static_dir: pathlib.Path | None = None    # built frontend (web/dist) served at /
    poll_interval_s: float = 2.0
    allowed_hosts: list[str] | None = None    # Host names the bridge answers to; None = loopback names only

    def public(self) -> dict:
        """What the browser may know about the bridge: never a token."""
        return {"lab_target": self.lab_target, "admin_target": self.admin_target, "read_only": self.read_only,
                "has_lab_token": bool(self.lab_token), "has_admin_token": bool(self.admin_token),
                "tls_to_chassis": self.ca_file is not None, "embedded_chassis": self.embedded_chassis,
                "chassis_profile": self.chassis_profile, "chassis_device": self.chassis_device,
                "chassis_time_scale": self.chassis_time_scale}
