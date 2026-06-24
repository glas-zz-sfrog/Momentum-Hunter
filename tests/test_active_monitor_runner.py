from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.active_monitor_runner import (
    build_active_monitor_command,
    load_active_monitor_runner_state,
    save_active_monitor_runner_state,
    start_active_monitor_background,
    stop_active_monitor_background,
)


class FakeProcess:
    def __init__(self, pid: int = 4321) -> None:
        self.pid = pid


class ActiveMonitorRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-active-monitor-runner-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.runner_path = self.root / "active-monitor-runner.json"
        self.status_path = self.root / "active-monitor-status.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_command_includes_loop_flags_and_quote_option(self) -> None:
        command = build_active_monitor_command(
            python_executable="python-test",
            cycles=4,
            interval_seconds=300,
            fetch_missing_market_data=True,
            refresh_target_market_data=True,
            status_path=self.status_path,
        )

        self.assertEqual("python-test", command[0])
        self.assertIn("momentum_hunter.active_monitor", command)
        self.assertIn("--cycles", command)
        self.assertIn("4", command)
        self.assertIn("--interval-seconds", command)
        self.assertIn("300", command)
        self.assertIn("--fetch-missing-market-data", command)
        self.assertIn("--refresh-target-market-data", command)
        self.assertIn(str(self.status_path), command)

    def test_start_writes_runner_state_without_real_process(self) -> None:
        calls = []

        def fake_popen(command, **kwargs):
            calls.append((command, kwargs))
            return FakeProcess(2222)

        state = start_active_monitor_background(
            cycles=9,
            interval_seconds=60,
            fetch_missing_market_data=True,
            refresh_target_market_data=True,
            status_path=self.status_path,
            runner_path=self.runner_path,
            python_executable="python-test",
            popen_factory=fake_popen,
            process_checker=lambda pid: False,
        )
        loaded = load_active_monitor_runner_state(self.runner_path)

        self.assertEqual("RUNNING", state.state)
        self.assertEqual(2222, state.pid)
        self.assertEqual(9, state.cycles)
        self.assertEqual(60, state.interval_seconds)
        self.assertTrue(state.fetch_missing_market_data)
        self.assertTrue(state.refresh_target_market_data)
        self.assertEqual(state, loaded)
        self.assertEqual(1, len(calls))

    def test_start_reuses_existing_running_process(self) -> None:
        first = start_active_monitor_background(
            runner_path=self.runner_path,
            python_executable="python-test",
            popen_factory=lambda command, **kwargs: FakeProcess(3333),
            process_checker=lambda pid: False,
        )
        second = start_active_monitor_background(
            runner_path=self.runner_path,
            python_executable="python-test",
            popen_factory=lambda command, **kwargs: (_ for _ in ()).throw(RuntimeError("should not launch")),
            process_checker=lambda pid: pid == first.pid,
        )

        self.assertEqual(first, second)

    def test_stop_marks_runner_stopped_and_calls_terminator(self) -> None:
        started = start_active_monitor_background(
            runner_path=self.runner_path,
            python_executable="python-test",
            popen_factory=lambda command, **kwargs: FakeProcess(4444),
            process_checker=lambda pid: False,
        )
        killed = []

        state = stop_active_monitor_background(
            runner_path=self.runner_path,
            process_checker=lambda pid: pid == started.pid,
            terminator=lambda pid: killed.append(pid),
        )

        self.assertEqual("STOPPED", state.state)
        self.assertEqual([4444], killed)
        self.assertEqual("STOPPED", load_active_monitor_runner_state(self.runner_path).state)

    def test_stop_without_state_writes_stopped_record(self) -> None:
        state = stop_active_monitor_background(runner_path=self.runner_path)

        self.assertEqual("STOPPED", state.state)
        self.assertIn("No active monitor", state.last_error)
