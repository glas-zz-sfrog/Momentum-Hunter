from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


WORKSTATION_EXECUTABLE = "MomentumHunter.Desktop.Wpf.exe"


class WorkstationExecutableNotFoundError(FileNotFoundError):
    """Raised when no approved WPF workstation build is available."""


@dataclass(frozen=True)
class WorkstationLaunchPlan:
    executable: Path
    working_directory: Path
    source: str


def build_launch_plan(
    project_root: Path | None = None,
    *,
    local_app_data: Path | None = None,
) -> WorkstationLaunchPlan:
    root = (project_root or Path(__file__).resolve().parents[1]).resolve()
    app_data = (
        local_app_data
        or Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    ).resolve()

    candidates = (
        (
            root
            / "src"
            / "MomentumHunter.Desktop.Wpf"
            / "bin"
            / "Release"
            / "net8.0-windows"
            / WORKSTATION_EXECUTABLE,
            "repository Release build",
        ),
        (
            app_data / "MomentumHunter" / "Workstation" / WORKSTATION_EXECUTABLE,
            "installed local workstation",
        ),
    )
    for executable, source in candidates:
        if executable.is_file():
            return WorkstationLaunchPlan(executable.resolve(), root, source)

    checked = "\n".join(f"- {path}" for path, _ in candidates)
    raise WorkstationExecutableNotFoundError(
        "Momentum Hunter could not find an approved WPF workstation build.\n"
        "Build the Release workstation or install a verified local copy.\n"
        f"Checked:\n{checked}"
    )


def launch_workstation(
    project_root: Path | None = None,
    *,
    local_app_data: Path | None = None,
    process_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
) -> subprocess.Popen[bytes]:
    plan = build_launch_plan(project_root, local_app_data=local_app_data)
    options: dict[str, object] = {
        "cwd": str(plan.working_directory),
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    return process_factory([str(plan.executable)], **options)


def main() -> int:
    try:
        launch_workstation()
    except WorkstationExecutableNotFoundError as exc:
        _show_launch_error(str(exc))
        return 1
    return 0


def _show_launch_error(message: str) -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
            0,
            message,
            "Momentum Hunter",
            0x10,
        )
        return
    print(message, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
