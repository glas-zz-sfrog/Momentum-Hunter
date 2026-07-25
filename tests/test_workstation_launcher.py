from __future__ import annotations

import shutil
import subprocess
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock

from momentum_hunter.workstation_launcher import (
    WORKSTATION_EXECUTABLE,
    WorkstationExecutableNotFoundError,
    build_launch_plan,
    launch_workstation,
)


class WorkstationLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_root = Path(__file__).resolve().parents[1] / ".tmp"
        temp_root.mkdir(exist_ok=True)
        self.base = temp_root / f"workstation-launcher-{uuid.uuid4().hex}"
        self.project_root = self.base / "Project"
        self.local_app_data = self.base / "LocalAppData"
        self.project_root.mkdir(parents=True)
        self.local_app_data.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)

    def test_release_build_is_the_canonical_checkout_target(self) -> None:
        release = self._release_executable()
        installed = self._installed_executable()
        self._touch(release)
        self._touch(installed)

        plan = build_launch_plan(
            self.project_root,
            local_app_data=self.local_app_data,
        )

        self.assertEqual(release.resolve(), plan.executable)
        self.assertEqual(self.project_root.resolve(), plan.working_directory)
        self.assertEqual("repository Release build", plan.source)

    def test_installed_workstation_is_used_when_checkout_has_no_release_build(self) -> None:
        installed = self._installed_executable()
        self._touch(installed)

        plan = build_launch_plan(
            self.project_root,
            local_app_data=self.local_app_data,
        )

        self.assertEqual(installed.resolve(), plan.executable)
        self.assertEqual("installed local workstation", plan.source)

    def test_review_builds_are_never_selected_implicitly(self) -> None:
        review = (
            self.local_app_data
            / "MomentumHunter"
            / "Builds"
            / "R028-integrated-chrome-review"
            / WORKSTATION_EXECUTABLE
        )
        self._touch(review)

        with self.assertRaises(WorkstationExecutableNotFoundError) as raised:
            build_launch_plan(
                self.project_root,
                local_app_data=self.local_app_data,
            )

        self.assertNotIn("Builds", str(raised.exception))

    def test_launch_uses_direct_executable_without_shell_or_legacy_qt(self) -> None:
        release = self._release_executable()
        self._touch(release)
        process = Mock(spec=subprocess.Popen)
        process_factory = Mock(return_value=process)

        result = launch_workstation(
            self.project_root,
            local_app_data=self.local_app_data,
            process_factory=process_factory,
        )

        self.assertIs(process, result)
        args, kwargs = process_factory.call_args
        self.assertEqual([str(release.resolve())], args[0])
        self.assertEqual(str(self.project_root.resolve()), kwargs["cwd"])
        self.assertTrue(kwargs["close_fds"])
        self.assertNotIn("shell", kwargs)

    def test_missing_workstation_fails_with_exact_checked_paths(self) -> None:
        with self.assertRaises(WorkstationExecutableNotFoundError) as raised:
            build_launch_plan(
                self.project_root,
                local_app_data=self.local_app_data,
            )

        message = str(raised.exception)
        self.assertIn(str(self._release_executable()), message)
        self.assertIn(str(self._installed_executable()), message)
        self.assertNotIn("pythonw", message.lower())
        self.assertNotIn("run.py", message.lower())

    def test_repository_entrypoint_routes_to_wpf_launcher(self) -> None:
        root = Path(__file__).resolve().parents[1]
        entrypoint = (root / "run.py").read_text(encoding="utf-8")

        self.assertIn("from momentum_hunter.workstation_launcher import main", entrypoint)
        self.assertNotIn("from momentum_hunter.app import main", entrypoint)

    def test_all_tracked_normal_launchers_converge_on_repository_entrypoint(self) -> None:
        root = Path(__file__).resolve().parents[1]
        launcher_paths = (
            root / "Momentum Hunter.bat",
            root / "Momentum Hunter.vbs",
            root / "tools" / "launch_momentum_hunter.ps1",
        )

        for path in launcher_paths:
            with self.subTest(path=path.name):
                content = path.read_text(encoding="utf-8")
                self.assertIn("run.py", content)
                self.assertNotIn("momentum_hunter.app", content)

    def test_legacy_qt_requires_an_explicit_module_launch(self) -> None:
        root = Path(__file__).resolve().parents[1]
        legacy_app = (root / "momentum_hunter" / "app.py").read_text(encoding="utf-8")

        self.assertIn('if __name__ == "__main__":', legacy_app)
        self.assertTrue(legacy_app.rstrip().endswith("main()"))

    def _release_executable(self) -> Path:
        return (
            self.project_root
            / "src"
            / "MomentumHunter.Desktop.Wpf"
            / "bin"
            / "Release"
            / "net8.0-windows"
            / WORKSTATION_EXECUTABLE
        )

    def _installed_executable(self) -> Path:
        return (
            self.local_app_data
            / "MomentumHunter"
            / "Workstation"
            / WORKSTATION_EXECUTABLE
        )

    @staticmethod
    def _touch(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")


if __name__ == "__main__":
    unittest.main()
