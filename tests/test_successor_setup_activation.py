from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


class SuccessorSetupActivationTests(unittest.TestCase):
    def test_plan_only_preserves_central_offset_and_existing_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "repo"
            project.mkdir()
            self._git(project, "init")
            (project / "tracked.txt").write_text("baseline\n", encoding="utf-8")
            self._git(project, "add", "tracked.txt")
            self._git(
                project,
                "-c",
                "user.name=Momentum Hunter Tests",
                "-c",
                "user.email=tests@example.invalid",
                "commit",
                "-m",
                "baseline",
            )
            head = self._git(project, "rev-parse", "HEAD").stdout.strip()
            service = root / "service"
            service.mkdir()
            session = (datetime.now().date() + timedelta(days=3)).isoformat()
            session_id = session.replace("-", "")
            manifest = {
                "jobs": [
                    {
                        "jobId": f"opening-capture-{session_id}",
                        "kind": "opening_capture",
                        "scheduledAt": f"{session}T08:35:00-05:00",
                        "latestStartAt": f"{session}T08:40:00-05:00",
                        "enabled": True,
                        "expectedGitHead": head,
                    }
                ]
            }
            (service / "automation-manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            script = Path(__file__).resolve().parents[1] / "tools" / (
                "set_successor_setup_research_jobs.ps1"
            )

            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-SessionDate",
                    session,
                    "-ProjectRoot",
                    str(project),
                    "-PythonExe",
                    sys.executable,
                    "-ServiceRoot",
                    str(service),
                    "-EnableSuccessorSetupResearch",
                    "-PlanOnly",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                f"opening-capture-{session_id}",
                payload["openingDependency"],
            )
            self.assertEqual(head, payload["expectedGitHead"])
            self.assertRegex(payload["jobs"][0]["scheduledAt"], r"[+-]\d{2}:\d{2}$")
            self.assertRegex(payload["jobs"][1]["scheduledAt"], r"[+-]\d{2}:\d{2}$")
            self.assertFalse(payload["providerCalls"])
            self.assertFalse(payload["accountCalls"])
            self.assertEqual("UNAVAILABLE", payload["orderTransmission"])
            self.assertEqual(1, len(manifest["jobs"]))

    @staticmethod
    def _git(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(project), *arguments],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
