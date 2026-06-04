from __future__ import annotations

import os
from pathlib import Path


def startup_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def startup_script_path() -> Path:
    return startup_dir() / "Momentum Hunter.vbs"


def legacy_startup_script_path() -> Path:
    return startup_dir() / "Momentum Hunter.bat"


def launcher_python_path(project_root: Path) -> Path:
    python_path = project_root / ".venv" / "Scripts" / "pythonw.exe"
    if not python_path.exists():
        python_path = project_root / ".venv" / "Scripts" / "python.exe"
    return python_path


def startup_script_content(project_root: Path) -> str:
    python_path = launcher_python_path(project_root)
    run_path = project_root / "run.py"
    return (
        'Set shell = CreateObject("WScript.Shell")\n'
        f'shell.CurrentDirectory = "{escape_vbs(project_root)}"\n'
        f'shell.Run """{escape_vbs(python_path)}"" ""{escape_vbs(run_path)}""", 0, False\n'
    )


def escape_vbs(path: Path) -> str:
    return str(path).replace('"', '""')


def install_startup_script(project_root: Path) -> Path:
    startup_dir = startup_script_path().parent
    startup_dir.mkdir(parents=True, exist_ok=True)
    path = startup_script_path()
    path.write_text(startup_script_content(project_root), encoding="utf-8")
    legacy_path = legacy_startup_script_path()
    if legacy_path.exists():
        legacy_path.unlink()
    return path


def is_startup_installed() -> bool:
    return startup_script_path().exists() and not legacy_startup_script_path().exists()
