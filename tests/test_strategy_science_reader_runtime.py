from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.strategy_science_reader_runtime import (
    ACCEPTED_READER_MODULE_SHA256,
    DEPLOYMENT_CLASS,
    INVOCATION_CONTRACT,
    RUNTIME_CONFIG_VERSION,
    RUNTIME_IDENTITY,
    RUNTIME_PROFILE,
    STORAGE_CLASS,
    UPSTREAM_SOURCE_DEPENDENCY,
    ReaderRuntimeConfigError,
    ReaderRuntimeIdentityError,
    ReaderRuntimeSingletonError,
    StrategyScienceReaderRuntime,
    derive_publication_root_identity,
    initialize_state,
    load_runtime_config,
    probe_instance_state,
    validate_state,
    verify_accepted_reader_bytes,
)
from momentum_hunter.strategy_science_recorder import canonical_json_v1, sha256_hex
from momentum_hunter.strategy_science_source_reader import (
    SimulatedSourceReaderCrash,
    SourceReaderPublicationError,
    StrategyScienceSourceReaderV2,
)
from tests.test_continuous_research_export_v2 import SOURCE_ROOT, exporter
from tests.test_strategy_science_source_reader_v2 import (
    publication_files,
    publish_complete,
)


class StrategyScienceReaderRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_empty_source(self) -> Path:
        producer = self.root / "producer"
        with exporter(producer):
            pass
        return producer

    def write_config(
        self,
        producer: Path,
        *,
        name: str = "runtime-config.json",
        changes: dict[str, object] | None = None,
    ) -> Path:
        metadata = (producer / "publication-identity.json").read_bytes()
        published = producer / "published"
        value: dict[str, object] = {
            "authority": "RESEARCH_ONLY",
            "deployment_class": DEPLOYMENT_CLASS,
            "deployment_instance_id": "science-reader-002-primary",
            "execution_authority": "NONE",
            "expected_publication_metadata_sha256": sha256_hex(metadata),
            "expected_publication_root_identity": derive_publication_root_identity(
                published,
                metadata_sha256=sha256_hex(metadata),
                source_root_identity=SOURCE_ROOT,
            ),
            "expected_source_root_identity": SOURCE_ROOT,
            "invocation_contract": INVOCATION_CONTRACT,
            "poll_interval_milliseconds": 100,
            "publication_root": str(published),
            "runtime_config_version": RUNTIME_CONFIG_VERSION,
            "runtime_identity": RUNTIME_IDENTITY,
            "runtime_profile": RUNTIME_PROFILE,
            "science_root": str(self.root / "science"),
            "state_root": str(self.root / "state"),
            "storage_class": STORAGE_CLASS,
            "upstream_source_dependency": UPSTREAM_SOURCE_DEPENDENCY,
        }
        if changes:
            value.update(changes)
        path = self.root / name
        path.write_bytes(canonical_json_v1(value))
        return path

    def configured(self, *, complete: bool = False):
        producer = self.root / "producer"
        if complete:
            publish_complete(producer)
        else:
            self.create_empty_source()
        config = load_runtime_config(self.write_config(producer))
        return producer, config

    @staticmethod
    def file_hash(path: Path) -> str:
        return sha256_hex(path.read_bytes())

    def test_exact_accepted_reader_module_is_gated(self) -> None:
        self.assertEqual(ACCEPTED_READER_MODULE_SHA256, verify_accepted_reader_bytes())
        with patch(
            "momentum_hunter.strategy_science_reader_runtime.ACCEPTED_READER_MODULE_SHA256",
            "0" * 64,
        ):
            with self.assertRaises(ReaderRuntimeIdentityError):
                verify_accepted_reader_bytes()

    def test_config_and_runtime_identity_are_stable_and_explicit(self) -> None:
        producer, first = self.configured()
        second = load_runtime_config(self.write_config(producer, name="copy.json"))
        self.assertEqual(RUNTIME_IDENTITY, first.runtime_identity)
        self.assertEqual(first.fingerprint_sha256, second.fingerprint_sha256)
        self.assertTrue(first.publication_root.is_absolute())
        self.assertTrue(first.state_root.is_absolute())
        self.assertTrue(first.science_root.is_absolute())

    def test_config_has_no_safety_critical_defaults(self) -> None:
        producer = self.create_empty_source()
        path = self.write_config(producer)
        value = json.loads(path.read_bytes())
        del value["state_root"]
        path.write_bytes(canonical_json_v1(value))
        with self.assertRaises(ReaderRuntimeConfigError):
            load_runtime_config(path)

    def test_relative_root_is_rejected(self) -> None:
        producer = self.create_empty_source()
        path = self.write_config(producer, changes={"science_root": "relative/science"})
        with self.assertRaises(ReaderRuntimeConfigError):
            load_runtime_config(path)

    def test_missing_publication_fails_without_creating_source_or_state(self) -> None:
        producer = self.create_empty_source()
        config_path = self.write_config(producer)
        (producer / "published").rmdir()
        config = load_runtime_config(config_path)
        with self.assertRaises(ReaderRuntimeIdentityError):
            initialize_state(config)
        self.assertFalse(config.state_root.exists())
        self.assertFalse(config.science_root.exists())
        self.assertFalse((producer / "published").exists())

    def test_publication_metadata_mismatch_fails_closed(self) -> None:
        producer = self.create_empty_source()
        config = load_runtime_config(
            self.write_config(
                producer,
                changes={"expected_publication_metadata_sha256": "0" * 64},
            )
        )
        with self.assertRaises(ReaderRuntimeIdentityError):
            initialize_state(config)
        self.assertFalse(config.state_root.exists())

    def test_state_initialization_is_deterministic_and_creates_no_history(self) -> None:
        producer, config = self.configured()
        before = tuple(publication_files(producer))
        first = initialize_state(config)
        identity_paths = (
            config.state_root / "reader-state-identity.json",
            config.state_root / "runtime" / "runtime-identity.json",
            config.science_root / "reader-custody-root-identity.json",
        )
        hashes = tuple(self.file_hash(path) for path in identity_paths)
        second = initialize_state(config)
        self.assertEqual(first["state_binding_sha256"], second["state_binding_sha256"])
        self.assertEqual(hashes, tuple(self.file_hash(path) for path in identity_paths))
        self.assertEqual(before, tuple(publication_files(producer)))
        self.assertFalse((config.state_root / "cursors").exists())
        self.assertEqual((), publication_files(producer))

    def test_missing_or_changed_state_identity_fails_closed(self) -> None:
        _producer, config = self.configured()
        initialize_state(config)
        identity = config.state_root / "reader-state-identity.json"
        identity.unlink()
        with self.assertRaises(ReaderRuntimeIdentityError):
            validate_state(config)

    def test_zero_instance_and_clean_shutdown_are_proven(self) -> None:
        _producer, config = self.configured()
        initialize_state(config)
        self.assertEqual("ZERO_INSTANCES", probe_instance_state(config))
        with StrategyScienceReaderRuntime(config):
            self.assertEqual("ONE_AUTHORIZED_INSTANCE", probe_instance_state(config))
        self.assertEqual("ZERO_INSTANCES", probe_instance_state(config))
        owner = json.loads(
            (config.state_root / "runtime" / "active-owner.json").read_bytes()
        )
        self.assertEqual("STOPPED", owner["status"])

    def test_duplicate_runtime_ownership_fails_closed(self) -> None:
        _producer, config = self.configured()
        initialize_state(config)
        first = StrategyScienceReaderRuntime(config)
        first.start()
        try:
            second = StrategyScienceReaderRuntime(config)
            with self.assertRaises(ReaderRuntimeSingletonError):
                second.start()
        finally:
            first.stop()

    def test_ambiguous_owner_identity_fails_closed(self) -> None:
        _producer, config = self.configured()
        initialize_state(config)
        path = config.state_root / "runtime" / "active-owner.json"
        value = json.loads(path.read_bytes())
        value["status"] = "UNKNOWN"
        path.write_bytes(canonical_json_v1(value))
        with self.assertRaises(ReaderRuntimeSingletonError):
            probe_instance_state(config)

    def test_runtime_invokes_exact_reader_and_preserves_source_bytes(self) -> None:
        producer, config = self.configured(complete=True)
        before = {path.name: self.file_hash(path) for path in publication_files(producer)}
        initialize_state(config)
        with StrategyScienceReaderRuntime(config) as runtime:
            self.assertIs(type(runtime._reader), StrategyScienceSourceReaderV2)
            result = runtime.consume_once()
        self.assertEqual("TERMINAL_FINAL_ADMITTED", result.status)
        self.assertEqual(
            before,
            {path.name: self.file_hash(path) for path in publication_files(producer)},
        )

    def test_restart_does_not_duplicate_publication_or_custody(self) -> None:
        _producer, config = self.configured(complete=True)
        initialize_state(config)
        with StrategyScienceReaderRuntime(config) as runtime:
            first = runtime.consume_once()
        cursor_paths = tuple((config.state_root / "cursors").glob("*.json"))
        custody_paths = tuple(config.science_root.rglob("*.source.json"))
        with StrategyScienceReaderRuntime(config) as runtime:
            second = runtime.consume_once()
        self.assertGreater(len(first.admissions), 0)
        self.assertEqual(0, len(second.admissions))
        self.assertEqual(cursor_paths, tuple((config.state_root / "cursors").glob("*.json")))
        self.assertEqual(custody_paths, tuple(config.science_root.rglob("*.source.json")))

    def test_crash_after_custody_cannot_overadvance_and_restart_is_idempotent(self) -> None:
        _producer, config = self.configured(complete=True)
        initialize_state(config)
        with StrategyScienceReaderRuntime(config) as runtime:
            with self.assertRaises(SimulatedSourceReaderCrash):
                runtime.consume_once(max_items=1, crash_phase="after_custody_before_cursor")
        self.assertEqual((), tuple((config.state_root / "cursors").glob("*.json")))
        staged = tuple(config.science_root.rglob("*.source.json"))
        self.assertEqual(1, len(staged))
        with StrategyScienceReaderRuntime(config) as runtime:
            result = runtime.consume_once()
        self.assertTrue(result.cursor.terminal)
        self.assertEqual(
            len(tuple((config.state_root / "cursors").glob("*.json"))),
            len(tuple(config.science_root.rglob("*.source.json"))),
        )

    def test_committed_cursor_survives_post_commit_interruption_without_duplicate(self) -> None:
        _producer, config = self.configured(complete=True)
        initialize_state(config)
        with StrategyScienceReaderRuntime(config) as runtime:
            with self.assertRaises(SimulatedSourceReaderCrash):
                runtime.consume_once(max_items=1, crash_phase="after_cursor_commit")
        self.assertEqual(1, len(tuple((config.state_root / "cursors").glob("*.json"))))
        with StrategyScienceReaderRuntime(config) as runtime:
            result = runtime.consume_once()
        self.assertTrue(result.cursor.terminal)
        self.assertEqual(
            len(tuple((config.state_root / "cursors").glob("*.json"))),
            len(tuple(config.science_root.rglob("*.source.json"))),
        )

    def test_gap_stops_before_later_evidence_and_restart_cannot_skip(self) -> None:
        producer, config = self.configured(complete=True)
        paths = publication_files(producer)
        missing = paths[1]
        held = self.root / missing.name
        missing.replace(held)
        initialize_state(config)
        with StrategyScienceReaderRuntime(config) as runtime:
            with self.assertRaises(SourceReaderPublicationError) as failure:
                runtime.consume_once()
        self.assertIn("gap", str(failure.exception).lower())
        cursors = tuple((config.state_root / "cursors").glob("*.json"))
        self.assertEqual(1, len(cursors))
        held.replace(missing)
        with StrategyScienceReaderRuntime(config) as runtime:
            result = runtime.consume_once()
        self.assertTrue(result.cursor.terminal)
        self.assertEqual(len(paths), result.cursor.last_publication_ordinal)

    def test_stop_request_is_deterministic_without_fabricating_publication(self) -> None:
        producer, config = self.configured()
        initialize_state(config)
        stop = threading.Event()
        stop.set()
        with StrategyScienceReaderRuntime(config) as runtime:
            result = runtime.run_until_stopped(stop)
        self.assertEqual("STOP_REQUESTED", result["reason"])
        self.assertEqual((), publication_files(producer))
        self.assertEqual((), tuple((config.state_root / "cursors").glob("*.json")))

    def test_cli_is_service_compatible_but_only_probes_during_test(self) -> None:
        _producer, config = self.configured()
        initialize_state(config)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "momentum_hunter.strategy_science_reader_runtime",
                "probe",
                "--config",
                str(self.root / "runtime-config.json"),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(0, completed.returncode, completed.stderr.decode())
        self.assertEqual("ZERO_INSTANCES", json.loads(completed.stdout)["singleton_state"])

    def test_runtime_has_no_provider_service_scheduler_or_execution_imports(self) -> None:
        source = Path(
            sys.modules[
                "momentum_hunter.strategy_science_reader_runtime"
            ].__file__
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            str(node.module)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        prohibited = {
            "requests",
            "httpx",
            "schwab",
            "subprocess",
            "momentum_hunter.automation_service",
            "momentum_hunter.order_execution",
        }
        self.assertTrue(imported.isdisjoint(prohibited))


if __name__ == "__main__":
    unittest.main()
