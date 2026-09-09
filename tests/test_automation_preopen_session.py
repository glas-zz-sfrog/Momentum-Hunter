from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from momentum_hunter.automation_preopen_guardian import parse_session_date, continuous_phase_liveness
from momentum_hunter.automation_state_recovery import digest, prospective_epoch
from momentum_hunter.automation_supervisor import AutomationJob, AutomationManifest, AutomationSupervisor
from tests import test_automation_preopen_guardian as guardian_fixtures
from tests import test_automation_state_recovery as recovery_fixtures
from tests import test_automation_supervisor as supervisor_fixtures


def run_cli_fixture():
    """Run the real CLI; substitute only OS queries, clock and environment probe."""
    context = json.loads(Path(sys.argv[2]).read_bytes())
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime.fromisoformat(context["now"])
            return value.astimezone(tz) if tz else value

    def os_query(command, **kwargs):
        if command[0] == "git" and command[1:3] == ["--no-optional-locks", "-C"]:
            if command[4:] in (["rev-parse", "HEAD"], ["rev-parse", "origin/master"]):
                output = context["head"]
            elif command[4:] == ["status", "--porcelain"]:
                output = ""
            else:
                raise AssertionError(command)
        elif command[:4] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]:
            assert "Get-CimInstance Win32_Service" in command[4]
            output = json.dumps(list(context["services"].values()))
        else:
            raise AssertionError("UNEXPECTED_OS_QUERY:" + str(command))
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    cli = Path(__file__).resolve().parents[1] / "tools/check_automation_preopen.py"
    arguments = sys.argv[4:]
    with patch("sys.argv", [str(cli), *arguments]), patch("datetime.datetime", Clock), \
         patch("subprocess.run", side_effect=os_query), \
         patch("momentum_hunter.opening_runtime_identity.probe_runtime_environment", return_value=context["environment"]):
        runpy.run_path(str(cli), run_name="__main__")


class SessionTests(unittest.TestCase):
    def fixture(self, session="2026-09-10", first_session=None):
        value = guardian_fixtures.GuardianTests()
        value.session_date = session
        value.first_session = first_session or session
        value.epoch_floor = datetime.fromisoformat(value.first_session + "T09:00:00").replace(tzinfo=ZoneInfo("America/Chicago")) - timedelta(days=1)
        value.setUp()
        self.addCleanup(value.tearDown)
        return value

    def cli(self, fixture, session):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        expected = root / "expected.json"
        expected.write_text(json.dumps(fixture.expectations))
        context = root / "os-fixture.json"
        context.write_text(json.dumps({"now":fixture.now.isoformat(), "head":"a"*40,
            "services":fixture.services, "environment":fixture.opening.environment}))
        arguments = ["--manifest", str(fixture.manifest), "--state", str(fixture.fixture.path),
            "--continuous", str(fixture.continuous), "--canonical", str(fixture.opening.repository),
            "--output-root", str(root / "output"), "--expectations", str(expected),
            "--expected-manifest-sha256", digest(fixture.manifest.read_bytes()),
            "--expected-continuous-sha256", digest(fixture.continuous.read_bytes()),
            "--expected-canonical", "a"*40, "--expected-expectations-sha256", digest(expected.read_bytes())]
        if session is not None:
            arguments += ["--session-date", session]
        before = {str(p):p.read_bytes() for directory in (fixture.root, fixture.opening.root)
                  for p in directory.rglob("*") if p.is_file()}
        result = subprocess.run([sys.executable, "-B", "-m", "tests.test_automation_preopen_session",
            "--cli-fixture", str(context), "--", *arguments], capture_output=True, text=True, timeout=45)
        self.assertEqual(before, {str(p):p.read_bytes() for directory in (fixture.root, fixture.opening.root)
                                 for p in directory.rglob("*") if p.is_file()})
        report = root / "output/TOMORROW-OPENING-READINESS.json"
        return result, json.loads(report.read_bytes()) if report.exists() else None

    def test_strict_dates_not_locale_or_implicit_today(self):
        for value in (None, "", "09/10/2026", "2026-9-10", "2026-02-30", "20260910", "2026-09-10T00:00:00", " 2026-09-10"):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                parse_session_date(value)
        self.assertEqual("2026-09-10", parse_session_date("2026-09-10").isoformat())

    def test_programmatic_invalid_or_unbound_date_is_red(self):
        value = self.fixture()
        for session in (None, "", "2026-9-10", "2026-09-09", "2026-09-11"):
            with self.subTest(session=session):
                result = value.inspect(session_date=session)
                self.assertEqual("RED_NOT_READY", result["status"])
                self.assertFalse(result["gates"]["TARGET_SESSION_CONTRACT_VALID"])

    def test_sep10_green_and_future_configured_cst_green_without_source_change(self):
        for session in ("2026-09-10", "2026-11-10"):
            with self.subTest(session=session):
                value = self.fixture(session)
                result = value.inspect()
                self.assertEqual([], result["failedGates"])
                self.assertEqual("GREEN_READY", result["status"])

    def test_expected_contract_cannot_hide_wrong_timezone_offset_or_handoff(self):
        value = self.fixture("2026-11-10")
        original = dict(value.expectations["targetSession"])
        for key, wrong in (("timezone", "UTC"), ("jobId", "opening-capture-20261111"),
            ("scheduledAt", "2026-11-10T08:35:00-05:00"), ("observerId", "impostor"),
            ("approvedRuntimeChannel", "other"), ("latestStartAt", "2026-11-10T08:30:00-06:00")):
            value.expectations["targetSession"] = dict(original, **{key:wrong})
            with self.subTest(key=key):
                self.assertFalse(value.inspect()["gates"]["TARGET_SESSION_CONTRACT_VALID"])

    def test_epoch_boundary_explicit_expectation_is_mandatory(self):
        value = self.fixture()
        value.expectations.pop("expectedEpochBoundary")
        self.assertFalse(value.inspect()["gates"]["EPOCH_BOUNDARY_VALID"])

    def phase_fixture(self, phase, check):
        value = self.fixture()
        state = value.state()
        state.service_started_at = (check-timedelta(minutes=1)).isoformat()
        state.last_heartbeat_at = check.isoformat()
        value.fixture.store().save(state)
        value.services["MomentumHunterAutomation"]["ProcessCreatedAt"] = (check-timedelta(minutes=2)).isoformat()
        value.expectations["automationRuntime"].update(wrapperCreatedAt=(check-timedelta(minutes=2)).isoformat(),
            serviceStartedAt=state.service_started_at)
        status = json.loads(value.status_path.read_bytes())
        started = check-timedelta(days=2)
        closed = phase == "SESSION_CLOSED"
        status.update(state="IDLE_OUT_OF_SESSION" if closed else "RUNNING", sessionPhase=phase,
            resolvedDiscoveryCadenceSeconds=None if closed else (600 if phase == "PREMARKET" else 300))
        status["health"].update(started_at=started.isoformat(),
            uptime_seconds=(check.astimezone(timezone.utc)-started.astimezone(timezone.utc)).total_seconds(),
            last_heartbeat_at=(check-timedelta(hours=12) if closed else check).isoformat(),
            last_tick_at=None if closed else check.isoformat(), process_state="READY" if closed else "RUNNING")
        value.write_status(status)
        value.now = check
        return value

    def test_closed_fresh_snapshot_old_heartbeat_is_healthy(self):
        value = self.phase_fixture("SESSION_CLOSED", datetime(2026,9,10,5,50,tzinfo=ZoneInfo("America/Chicago")))
        result = value.inspect()
        self.assertEqual([], result["failedGates"])
        self.assertEqual("CLOSED_SESSION", result["continuousPhaseEvidence"]["guardianPhase"])

    def test_premarket_exact_cli_green_without_market_quote_success(self):
        value = self.phase_fixture("PREMARKET", datetime(2026,9,10,7,25,tzinfo=ZoneInfo("America/Chicago")))
        result, report = self.cli(value, "2026-09-10")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("GREEN_READY", report["status"])
        self.assertEqual("PREOPEN", report["continuousPhaseEvidence"]["guardianPhase"])
        self.assertEqual("FUTURE_PROVIDER_RESULTS_UNPROVEN", report["providerReadiness"])

    def test_active_stale_heartbeat_and_stale_tick_each_red(self):
        for phase, hour in (("PREMARKET",7), ("REGULAR_SESSION",8)):
            value = self.phase_fixture(phase, datetime(2026,9,10,hour,35,tzinfo=ZoneInfo("America/Chicago")))
            original = json.loads(value.status_path.read_bytes())
            for key in ("last_heartbeat_at", "last_tick_at"):
                status = json.loads(json.dumps(original))
                status["health"][key] = (value.now-timedelta(seconds=121)).isoformat()
                value.write_status(status)
                with self.subTest(phase=phase, key=key):
                    self.assertFalse(value.inspect()["gates"]["CONTINUOUS_EXPECTED_LIVENESS"])

    def test_stale_or_future_serialized_status_fails_in_every_phase(self):
        for phase, hour in (("SESSION_CLOSED",5), ("PREMARKET",7), ("REGULAR_SESSION",8)):
            value = self.phase_fixture(phase, datetime(2026,9,10,hour,35,tzinfo=ZoneInfo("America/Chicago")))
            original = json.loads(value.status_path.read_bytes())
            for seconds in (-121, 1):
                status = json.loads(json.dumps(original))
                status["health"]["uptime_seconds"] += seconds
                value.write_status(status)
                with self.subTest(phase=phase, seconds=seconds):
                    self.assertFalse(value.inspect()["gates"]["CONTINUOUS_EXPECTED_LIVENESS"])

    def test_closed_status_cannot_waive_active_check_when_target_is_tomorrow(self):
        value = self.phase_fixture("SESSION_CLOSED", datetime(2026,9,9,10,0,tzinfo=ZoneInfo("America/Chicago")))
        self.assertEqual("2026-09-10", value.session_date)
        self.assertFalse(value.inspect()["gates"]["CONTINUOUS_EXPECTED_LIVENESS"])

    def test_transition_needs_new_matching_phase_snapshot(self):
        value = self.phase_fixture("PREMARKET", datetime(2026,9,10,8,29,59,tzinfo=ZoneInfo("America/Chicago")))
        status = json.loads(value.status_path.read_bytes())
        status["sessionPhase"] = "REGULAR_SESSION"
        status["resolvedDiscoveryCadenceSeconds"] = 300
        value.write_status(status)
        self.assertFalse(value.inspect(now=value.now+timedelta(seconds=1))["gates"]["CONTINUOUS_EXPECTED_LIVENESS"])

    def test_invalid_uptime_and_cadence_never_pass(self):
        value = self.phase_fixture("PREMARKET", datetime(2026,9,10,7,25,tzinfo=ZoneInfo("America/Chicago")))
        original = json.loads(value.status_path.read_bytes())
        for uptime in (True, "172800", -1, float("nan"), float("inf"), 1e300):
            status = json.loads(json.dumps(original))
            status["health"]["uptime_seconds"] = uptime
            value.write_status(status)
            with self.subTest(uptime=uptime):
                self.assertEqual("RED_NOT_READY", value.inspect()["status"])
        status = json.loads(json.dumps(original))
        status["resolvedDiscoveryCadenceSeconds"] = 300
        value.write_status(status)
        self.assertFalse(value.inspect()["gates"]["CONTINUOUS_EXPECTED_LIVENESS"])

    def test_degraded_closed_process_or_stalled_pipeline_remains_red(self):
        value = self.phase_fixture("SESSION_CLOSED", datetime(2026,9,10,5,50,tzinfo=ZoneInfo("America/Chicago")))
        original = json.loads(value.status_path.read_bytes())
        for field, wrong in (("process_state","DEGRADED"), ("pipeline_state","STALLED"),
            ("health_flags",["FAILED_FORWARD_PROGRESS"]), ("runtime_instance_id","impostor")):
            status = json.loads(json.dumps(original))
            status["health"][field] = wrong
            value.write_status(status)
            self.assertFalse(value.inspect()["gates"]["CONTINUOUS_EXPECTED_LIVENESS"])

    def test_actual_cli_twelve_case_matrix(self):
        cases = ("valid", "pre_epoch", "missing", "malformed", "no_job", "date_job_mismatch",
                 "wrong_start", "wrong_latest", "complete", "epoch_missing", "wrong_first", "future")
        for case in cases:
            with self.subTest(case=case):
                session = "2026-11-10" if case == "future" else "2026-09-10"
                value = self.fixture(session, first_session="2026-09-11" if case == "wrong_first" else None)
                argument = session
                if case == "pre_epoch":
                    argument = "2026-09-09"
                elif case == "missing":
                    argument = None
                elif case == "malformed":
                    argument = "09/10/2026"
                elif case in ("no_job", "date_job_mismatch", "wrong_start", "wrong_latest"):
                    payload = json.loads(value.manifest.read_bytes())
                    if case == "no_job":
                        payload["jobs"] = []
                    elif case == "date_job_mismatch":
                        payload["jobs"][0]["jobId"] = "opening-capture-20260911"
                    else:
                        key = "scheduledAt" if case == "wrong_start" else "latestStartAt"
                        payload["jobs"][0][key] = (value.now+timedelta(minutes=1)).isoformat()
                    value.manifest.write_text(json.dumps(payload))
                elif case == "complete":
                    value.fixture.store().save(value.state("COMPLETED"))
                elif case == "epoch_missing":
                    state = json.loads(value.fixture.path.read_bytes())
                    state.pop("prospective_epoch")
                    value.fixture.path.write_text(json.dumps(state))
                result, report = self.cli(value, argument)
                if case in ("valid", "future"):
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual("GREEN_READY", report["status"])
                elif case in ("missing", "malformed"):
                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertIsNone(report)
                else:
                    self.assertEqual(1, result.returncode, result.stderr)
                    self.assertEqual("RED_NOT_READY", report["status"])

    def test_sep10_schedule_restart_and_sep09_no_replay(self):
        zone = ZoneInfo("America/Chicago")
        start = datetime(2026, 9, 10, 8, 35, tzinfo=zone)
        floor = datetime(2026, 9, 9, 9, 0, tzinfo=zone)
        for minutes, launches, status in ((-1, 0, "PENDING"), (0, 1, "COMPLETED"), (4, 1, "COMPLETED"),
                                           (5, 1, "COMPLETED"), (6, 0, "MISSED")):
            with self.subTest(minutes=minutes):
                fixture = recovery_fixtures.RecoveryTests()
                fixture.setUp()
                try:
                    old = AutomationJob(job_id="opening-capture-20260909", kind="opening_capture", enabled=True,
                        scheduled_at=start-timedelta(days=1), latest_start_at=start-timedelta(days=1)+timedelta(minutes=5),
                        approved_runtime_channel="opening-capture")
                    new = AutomationJob(job_id="opening-capture-20260910", kind="opening_capture", enabled=True,
                        scheduled_at=start, latest_start_at=start+timedelta(minutes=5), approved_runtime_channel="opening-capture")
                    manifest = AutomationManifest(repository_root=fixture.root, python_executable=Path(sys.executable),
                        powershell_executable=Path("powershell.exe"), codex_executable=None, poll_interval_seconds=5,
                        state_directory=fixture.path.parent,
                        engine_host_state_directory=fixture.root/"engine", jobs=(old,new))
                    state = fixture.state()
                    state.jobs = {}
                    state.prospective_epoch = prospective_epoch(floor=floor, first_session="2026-09-10",
                        manifest_sha256="a"*64, corrupt_sha256=digest(bytes(36072)))
                    state.recovery_floor_at = floor.isoformat()
                    fixture.store().save(state)
                    calls = []
                    def supervisor():
                        return AutomationSupervisor(manifest, clock=lambda:start+timedelta(minutes=minutes),
                            engine_host_probe=lambda:{}, job_executor=lambda job,path:(calls.append(job.job_id) or 0,"fixture"),
                            runtime_gate=lambda job:supervisor_fixtures.AutomationSupervisorTests.runtime_gate_result())
                    first = supervisor().tick()
                    self.assertEqual(status, first.jobs[new.job_id].status)
                    self.assertEqual([new.job_id]*launches, calls)
                    supervisor().tick()
                    self.assertEqual([new.job_id]*launches, calls)
                    self.assertNotIn(old.job_id, calls)
                finally:
                    fixture.tearDown()


if __name__ == "__main__":
    if len(sys.argv)>1 and sys.argv[1] == "--cli-fixture":
        run_cli_fixture()
    else:
        unittest.main()
