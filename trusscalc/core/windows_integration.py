"""Small Windows shell integrations for the packaged application."""

from __future__ import annotations

import ctypes
import base64
import platform
import subprocess
import sys
from pathlib import Path

from trusscalc.version import APP_USER_MODEL_ID


def set_app_user_model_id() -> None:
    """Set a stable Windows AppUserModelID so the taskbar uses TrussCalc's icon."""
    if platform.system() != "Windows":
        return

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        # This is cosmetic; startup must never fail because the shell API is unavailable.
        return


def ensure_windows_shortcuts(icon_path: Path) -> None:
    """Create or refresh Desktop and Start Menu shortcuts for a frozen Windows build."""
    if platform.system() != "Windows" or not getattr(sys, "frozen", False):
        return

    exe_path = Path(sys.executable)
    if not exe_path.exists():
        return

    script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$exePath = __EXE_PATH__
$iconPath = __ICON_PATH__

$wsh = New-Object -ComObject WScript.Shell
$desktop = $wsh.SpecialFolders.Item('Desktop')
$programs = $wsh.SpecialFolders.Item('Programs')
$startFolder = Join-Path $programs 'TrussCalc'
[System.IO.Directory]::CreateDirectory($startFolder) | Out-Null

function Set-TrussCalcShortcut($path) {
    $shortcut = $wsh.CreateShortcut($path)
    $shortcut.TargetPath = $exePath
    $shortcut.WorkingDirectory = Split-Path -Parent $exePath
    $shortcut.Description = 'TrussCalc'
    if (Test-Path $iconPath) {
        $shortcut.IconLocation = "$iconPath,0"
    }
    $shortcut.Save()
}

Set-TrussCalcShortcut (Join-Path $desktop 'TrussCalc.lnk')
Set-TrussCalcShortcut (Join-Path $startFolder 'TrussCalc.lnk')
"""
    script = script.replace("__EXE_PATH__", _powershell_string(str(exe_path)))
    script = script.replace("__ICON_PATH__", _powershell_string(str(icon_path)))

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    encoded_script = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded_script,
            ],
            check=False,
            creationflags=creationflags,
            timeout=8,
        )
    except Exception:
        return


def _powershell_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
