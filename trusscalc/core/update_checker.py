"""Background update checks for the app and default truss library."""
from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from trusscalc.version import APP_VERSION, GITHUB_OWNER, GITHUB_REPO

HTTP_TIMEOUT_S = 4


@dataclass
class UpdateCheckResult:
    ok: bool = False
    error: str = ""
    local_version: str = APP_VERSION
    latest_version: str = ""
    release_url: str = ""
    program_update_available: bool = False
    local_truss_count: int = 0
    remote_truss_count: int = 0
    new_default_trusses: list[str] = field(default_factory=list)


def check_for_updates(local_default_json: Path) -> UpdateCheckResult:
    """Checks GitHub for a newer release and new default truss entries.

    Network failures are expected and returned as a quiet non-ok result so the
    app startup never depends on internet availability.
    """
    result = UpdateCheckResult()
    owner = os.environ.get("TRUSSCALC_UPDATE_OWNER", GITHUB_OWNER)
    repo = os.environ.get("TRUSSCALC_UPDATE_REPO", GITHUB_REPO)
    try:
        release = _fetch_json(
            f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
        )
        tag = str(release.get("tag_name") or "").lstrip("v")
        result.latest_version = tag
        result.release_url = str(release.get("html_url") or "")
        result.program_update_available = _version_tuple(tag) > _version_tuple(APP_VERSION)

        remote_defaults = _fetch_json(
            f"https://raw.githubusercontent.com/{owner}/{repo}/main/"
            "trusscalc/resources/default_truss_types.json"
        )
        local_defaults = json.loads(local_default_json.read_text(encoding="utf-8"))
        local_keys = {_truss_key(t) for t in local_defaults.get("truss_types", [])}
        remote_trusses = remote_defaults.get("truss_types", [])
        result.local_truss_count = len(local_keys)
        result.remote_truss_count = len(remote_trusses)
        for truss in remote_trusses:
            if _truss_key(truss) not in local_keys:
                result.new_default_trusses.append(_truss_label(truss))
        result.ok = True
    except Exception as exc:
        result.error = str(exc)
    return result


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"TrussCalc/{APP_VERSION}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as response:
        return json.loads(response.read().decode("utf-8"))


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", value or "")
    return tuple(int(p) for p in parts[:4]) if parts else (0,)


def _truss_key(truss: dict) -> tuple[str, str, str]:
    return (
        str(truss.get("manufacturer") or "").strip().lower(),
        str(truss.get("name") or "").strip().lower(),
        str(truss.get("model_code") or "").strip().lower(),
    )


def _truss_label(truss: dict) -> str:
    manufacturer = str(truss.get("manufacturer") or "").strip()
    name = str(truss.get("name") or "").strip()
    return f"{manufacturer} {name}".strip() or "Unbenannte Traverse"
