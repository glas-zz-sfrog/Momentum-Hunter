from __future__ import annotations

import os
from pathlib import Path


def startup_script_path() -> Path:
    startup_dir = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return startup_dir / "Momentum Hunter.bat"


def install_startup_script(project_root: Path) -> Path:
    startup_dir = startup_script_path().parent
    startup_dir.mkdir(parents=True, exist_ok=True)
    python_path = project_root / ".venv" / "Scripts" / "pythonw.exe"
    if not python_path.exists():
        python_path = project_root / ".venv" / "Scripts" / "python.exe"
    run_path = project_root / "run.py"
    script = (
        "@echo off\n"
        f'cd /d "{project_root}"\n'
        f'start "" "{python_path}" "{run_path}"\n'
    )
    path = startup_script_path()
    path.write_text(script, encoding="utf-8")
    return path


def is_startup_installed() -> bool:
    return startup_script_path().exists()
