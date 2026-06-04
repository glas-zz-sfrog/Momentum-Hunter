from __future__ import annotations

import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.startup import install_startup_script, is_startup_installed


class StartupLauncherTests(unittest.TestCase):
    def test_install_startup_script_uses_hidden_vbs_and_removes_legacy_batch(self) -> None:
        temp_root = Path(__file__).resolve().parents[1] / ".tmp"
        temp_root.mkdir(exist_ok=True)
        base = temp_root / f"startup-{uuid.uuid4().hex}"
        try:
            base.mkdir()
            appdata = base / "AppData"
            project_root = base / "Project"
            scripts_dir = project_root / ".venv" / "Scripts"
            scripts_dir.mkdir(parents=True)
            (scripts_dir / "pythonw.exe").write_text("", encoding="utf-8")
            (project_root / "run.py").write_text("", encoding="utf-8")

            startup_dir = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            startup_dir.mkdir(parents=True)
            legacy_batch = startup_dir / "Momentum Hunter.bat"
            legacy_batch.write_text("old launcher", encoding="utf-8")

            with patch.dict(os.environ, {"APPDATA": str(appdata)}):
                path = install_startup_script(project_root)

                self.assertEqual("Momentum Hunter.vbs", path.name)
                self.assertFalse(legacy_batch.exists())
                self.assertTrue(is_startup_installed())
                content = path.read_text(encoding="utf-8")
                self.assertIn("WScript.Shell", content)
                self.assertIn("pythonw.exe", content)
                self.assertIn(", 0, False", content)
        finally:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
