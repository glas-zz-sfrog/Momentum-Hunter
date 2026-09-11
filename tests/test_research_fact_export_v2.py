from __future__ import annotations

from copy import deepcopy
import ast
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from momentum_hunter import research_fact_export_v2 as facade_module
from momentum_hunter.continuous_research_export import (
    ContinuousResearchExportConflict,
    ContinuousResearchExportError,
    SimulatedPublicationCrash,
    evidence_present,
    producer_identity,
    time_evidence,
)
from momentum_hunter.research_fact_export_v2 import ResearchFactExporterV2
from momentum_hunter.strategy_science_recorder import (
    StrategyScienceRecorder,
    canonical_json_v1,
    parse_export_envelope_v1,
    parse_export_envelope_v2,
    sha256_hex,
)
from momentum_hunter.strategy_science_recorder.contract import (
    REPAIRED_EXPORT_SCHEMA_VERSION,
    REPAIRED_SOURCE_CONTRACT,
    REPAIRED_SOURCE_CONTRACT_VERSION,
    SCIENCE_OFFLINE_EXPORT_PROFILE_V2,
)
from tests import test_continuous_research_export_v2 as fixture
from tests import test_strategy_science_recorder_contract as historical


def configuration(root: Path, **overrides: object) -> dict[str, object]:
    values = dict(
        export_root=root,
        session_id=deepcopy(fixture.SESSION),
        source_owner_identity="opening-fact-owner",
        source_interface_identity="opening-facts-v2-offline",
        source_root_identity=fixture.SOURCE_ROOT,
        schema_version=REPAIRED_EXPORT_SCHEMA_VERSION,
        source_contract=REPAIRED_SOURCE_CONTRACT,
        source_contract_version=REPAIRED_SOURCE_CONTRACT_VERSION,
        offline_reference_profile=SCIENCE_OFFLINE_EXPORT_PROFILE_V2,
        science_custody_roots=[root.parent / "science-custody"],
        protected_roots=[root.parent / "protected-runtime"],
    )
    values.update(overrides)
    return values


def writer(root: Path, **overrides: object) -> ResearchFactExporterV2:
    return ResearchFactExporterV2(**configuration(root, **overrides)).initialize()


def start(exporter: ResearchFactExporterV2):
    return exporter.start(
        fixture.start_payload(), stream_id="session", source_event_id="start",
        emitted_at=fixture.START_TIME, event_time=fixture.START_TIME,
        effective_known_at=fixture.START_TIME,
    )


def discovery(exporter: ResearchFactExporterV2, payload=None, event_id="cycle-1"):
    facts = fixture.discovery_payload() if payload is None else payload
    return exporter.discovery_cycle(
        facts["discovery_cycle"], facts["observations"], stream_id="discovery",
        source_event_id=event_id, emitted_at=fixture.DISCOVERY_TIME,
    )


def decision(exporter: ResearchFactExporterV2, payload=None, event_id="decision-1"):
    facts = fixture.decision_payload() if payload is None else payload
    return exporter.decision(
        facts["decision_event"], reference_plan=facts.get("reference_plan"),
        stream_id="decision", source_event_id=event_id, emitted_at=fixture.DECISION_TIME,
    )


def finalize(exporter: ResearchFactExporterV2, **overrides: object):
    kwargs = dict(
        stream_id="session", source_event_id="final", closed_at=fixture.FINAL_TIME,
        close_reason="OFFLINE_FIXTURE_COMPLETE", terminal_proven=True,
        pending_source_events=0, source_gap_count=0, upstream_conflict_count=0,
    )
    kwargs.update(overrides)
    return exporter.finalize(**kwargs)


def inventory(root: Path) -> dict[str, str]:
    # Windows rejects reading the byte range held by the canonical writer lock.
    # All persisted semantic bytes and checkpoints remain covered by this proof.
    return {str(p.relative_to(root)): sha256_hex(p.read_bytes()) for p in root.rglob("*") if p.is_file() and p.name != ".writer.lock"}


class ResearchFactExportV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "producer"

    def opened(self, **overrides: object) -> ResearchFactExporterV2:
        result = writer(self.root, **overrides)
        self.addCleanup(result.close)
        return result

    def test_import_and_construction_do_not_initialize_or_contact_anything(self) -> None:
        with patch.object(facade_module, "ContinuousResearchExporterV2") as publisher:
            result = ResearchFactExporterV2(**configuration(self.root))
            publisher.assert_not_called()
            self.assertFalse(self.root.exists())
            with self.assertRaisesRegex(ValueError, "initialize"):
                start(result)
        with patch("pathlib.Path.mkdir", side_effect=AssertionError("import wrote")), patch(
            "pathlib.Path.open", side_effect=AssertionError("import opened a file")
        ), patch("os.link", side_effect=AssertionError("import linked")):
            importlib.reload(facade_module)
        self.assertFalse(self.root.exists())

    def test_only_canonical_v2_profile_is_admitted_without_defaults(self) -> None:
        wrong = {
            "schema_version": ["1.0.0", "2", "2.0.1", None],
            "source_contract": ["ResearchExportEnvelopeV1", "ResearchExportEnvelopeV3", None],
            "source_contract_version": ["1.0.0-proposal", "2.0.0", None],
            "offline_reference_profile": ["ARGUS_SCIENCE_OFFLINE_RESEARCH_EXPORT_V1", None],
        }
        for field, values in wrong.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    ResearchFactExporterV2(**configuration(self.root, **{field: value}))
            arguments = configuration(self.root)
            del arguments[field]
            with self.subTest(missing=field), self.assertRaises(TypeError):
                ResearchFactExporterV2(**arguments)
        self.assertFalse(self.root.exists())

    def test_owner_session_authority_is_required_frozen_and_restart_bound(self) -> None:
        for field, value in (("source_owner_identity", ""), ("source_interface_identity", None),
                             ("source_root_identity", "bad"), ("session_id", {})):
            with self.subTest(field=field), self.assertRaises(ValueError):
                ResearchFactExporterV2(**configuration(self.root, **{field: value}))
        arguments = configuration(self.root)
        result = ResearchFactExporterV2(**arguments)
        arguments["session_id"]["owner_id"] = "caller-mutated"
        arguments["science_custody_roots"].clear()
        arguments["protected_roots"].clear()
        result.initialize()
        self.addCleanup(result.close)
        published = start(result)
        self.assertEqual(fixture.SESSION, parse_export_envelope_v2(published.raw_bytes).session_id)
        result.close()
        for field, value in (
            ("source_owner_identity", "other-owner"), ("source_interface_identity", "other-interface"),
            ("source_root_identity", "a" * 64),
            ("session_id", producer_identity("SESSION_ID", "other", "session")),
        ):
            before = inventory(self.root)
            with self.subTest(field=field), self.assertRaises(ContinuousResearchExportConflict):
                writer(self.root, **{field: value})
            self.assertEqual(before, inventory(self.root))

    def test_explicit_initialization_and_start_source_clocks_are_required(self) -> None:
        result = self.opened()
        with self.assertRaises(ValueError):
            result.initialize()
        with self.assertRaises(ContinuousResearchExportError):
            discovery(result)
        with self.assertRaises(TypeError):
            result.start(fixture.start_payload(), stream_id="session", source_event_id="start", emitted_at=fixture.START_TIME)
        with self.assertRaises(ValueError):
            result.start(fixture.start_payload(), stream_id="session", source_event_id="start", emitted_at=fixture.START_TIME, event_time="", effective_known_at="")
        self.assertEqual((), result.published())

    def test_named_families_preserve_exact_facts_times_missingness_and_plan(self) -> None:
        result = self.opened()
        start(result)
        source = fixture.discovery_payload()
        row = source["observations"][0]
        row["candidate_facts"].update({
            "rvol": fixture.absent(state="UNAVAILABLE", reason="SOURCE_UNAVAILABLE"),
            "market_cap": fixture.absent(),
        })
        row["catalyst_identities"] = [{
            "catalyst_id": producer_identity("CATALYST_ID", fixture.OWNER, "known-headline"),
            "source_owner": "existing-news-owner",
            **{field: time_evidence(role, "2026-09-02T09:30:00.123-04:00", "existing-news-owner") for field, role in (
                ("source_event_time", "SOURCE_EVENT_TIME"), ("source_publication_time", "SOURCE_PUBLICATION_TIME"),
                ("provider_known_at", "PROVIDER_KNOWN_AT"), ("provider_received_at", "PROVIDER_RECEIVED_AT"),
            )},
        }]
        observed = discovery(result, source)
        planned = decision(result)
        market = fixture.market_payload()["market_snapshot"]
        market["market_facts"].update({field: evidence_present(value, fixture.OWNER) for field, value in (
            ("bid", "12.49"), ("ask", "12.51"), ("mark", "12.50"), ("spread", "0.02"),
            ("rvol", "3.2"), ("market_cap", "2000000"), ("persisted_score", "79"),
        )})
        snapshot = result.market_snapshot(market, stream_id="market", source_event_id="market", emitted_at=fixture.MARKET_TIME)
        health = fixture.health_payload()["provider_health_event"]
        failure = result.provider_health(health, stream_id="health", source_event_id="health", emitted_at=fixture.MARKET_TIME)
        for published, expected in ((observed, source), (planned, fixture.decision_payload()),
                                    (snapshot, {"market_snapshot": market}), (failure, {"provider_health_event": health})):
            parsed = parse_export_envelope_v2(published.raw_bytes)
            self.assertEqual(expected, parsed.payload)
            wire = json.loads(published.raw_bytes)
            self.assertEqual("2.0.0", wire["schema_version"])
            self.assertEqual("ResearchExportEnvelopeV2", wire["source_contract"])
            self.assertEqual("2.0.0-proposal", wire["source_contract_version"])
            self.assertEqual("RESEARCH_ONLY", wire["authority"])
            self.assertEqual("NONE", wire["execution_authority"])
        source["observations"][0]["candidate_facts"].clear()
        self.assertEqual(observed.raw_bytes, result.published()[1].raw_bytes)
        self.assertEqual("FINAL_PUBLISHED", finalize(result).status)
        metadata = json.loads((self.root / "publication-identity.json").read_bytes())
        self.assertEqual("ARGUS_CONTINUOUS_RESEARCH_EXPORT_V2", metadata["exporter_profile"])
        self.assertEqual("opening-fact-owner", metadata["source_owner_identity"])

    def test_no_plan_states_never_manufacture_reference_levels(self) -> None:
        for state in ("READY", "BLOCKED", "REJECTED", "MISSED", "NO_PLAN"):
            with self.subTest(state=state):
                result = writer(self.base / state)
                try:
                    start(result)
                    discovery(result)
                    facts = fixture.decision_payload()
                    del facts["reference_plan"]
                    facts["decision_event"].update(decision_state=state, tradeplan_id=fixture.absent(), reference_plan_id=fixture.absent())
                    published = decision(result, facts)
                    self.assertEqual(facts, parse_export_envelope_v2(published.raw_bytes).payload)
                finally:
                    result.close()

    def test_declared_denominator_rejects_dropped_reordered_or_aliased_rows_before_write(self) -> None:
        result = self.opened()
        start(result)
        second = fixture.observation(fixture.OBSERVATION_2, ordinal=1)
        source = fixture.discovery_payload([fixture.observation(), second])
        mutations = (
            lambda p: p["observations"].pop(),
            lambda p: p["observations"].reverse(),
            lambda p: p["discovery_cycle"].update(returned_row_count=3),
            lambda p: p["observations"][1].update(source_row_ordinal=0),
            lambda p: p["observations"][1].update(discovery_cycle_id=producer_identity("DISCOVERY_CYCLE_ID", fixture.OWNER, "other")),
            lambda p: p["discovery_cycle"].update(zero_result=True),
        )
        for index, mutate in enumerate(mutations):
            bad = deepcopy(source)
            mutate(bad)
            before = inventory(self.root)
            with self.subTest(case=index), self.assertRaises(ValueError):
                discovery(result, bad)
            self.assertEqual(before, inventory(self.root))
        duplicate = fixture.discovery_payload([fixture.observation(), fixture.observation(ordinal=1)])
        with self.assertRaisesRegex(ValueError, "repeats"):
            discovery(result, duplicate)
        self.assertEqual(1, len(result.published()))

    def test_zero_partial_failed_and_all_provider_failures_are_retained(self) -> None:
        result = self.opened()
        start(result)
        for index, state in enumerate(("ZERO_RESULT", "PARTIAL", "FAILED")):
            rows = [] if state != "PARTIAL" else [fixture.observation()]
            facts = fixture.discovery_payload(rows)
            facts["discovery_cycle"].update(cycle_state=state, zero_result=state == "ZERO_RESULT")
            if state != "ZERO_RESULT":
                facts["discovery_cycle"]["completeness"] = fixture.absent(state="PARTIAL" if rows else "UNAVAILABLE", reason="SOURCE_FAILURE")
            self.assertEqual(facts, parse_export_envelope_v2(discovery(result, facts, f"cycle-{index}").raw_bytes).payload)
        for event_class in ("UNAVAILABLE", "STALE", "PARTIAL", "HTTP_FAILURE", "AUTH_REFRESH", "MISSING_QUOTE", "MISSING_CANDLE", "READINESS_FAILURE"):
            health = fixture.health_payload()["provider_health_event"]
            health.update(event_class=event_class, provider_health_event_id=producer_identity("PROVIDER_HEALTH_EVENT_ID", fixture.OWNER, event_class))
            raw = result.provider_health(health, stream_id="health", source_event_id=event_class, emitted_at=fixture.MARKET_TIME).raw_bytes
            self.assertEqual(health, parse_export_envelope_v2(raw).payload["provider_health_event"])
        self.assertEqual(12, len(result.published()))

    def test_repeated_ticker_distinct_setups_and_cycles_survive_actual_restart(self) -> None:
        first = self.opened()
        start(first)
        rows = [fixture.observation(), fixture.observation(fixture.OBSERVATION_2, ordinal=1)]
        rows[1]["candidate_or_setup_identity"] = producer_identity("SETUP", fixture.OWNER, "setup-2")
        initial = discovery(first, fixture.discovery_payload(rows))
        first.close()
        recovered = self.opened()
        self.assertEqual(initial.raw_bytes, recovered.published()[1].raw_bytes)
        cycle2 = producer_identity("DISCOVERY_CYCLE_ID", fixture.OWNER, "cycle-2")
        row3 = fixture.observation(producer_identity("OBSERVATION_ID", fixture.OWNER, "observation-3"))
        row3["discovery_cycle_id"] = cycle2
        source = fixture.discovery_payload([row3])
        source["discovery_cycle"]["discovery_cycle_id"] = cycle2
        later = discovery(recovered, source, "cycle-2")
        parsed = parse_export_envelope_v2(later.raw_bytes)
        self.assertEqual(2, parsed.source_sequence)
        self.assertEqual(initial.raw_sha256, parsed.previous_record_sha256)
        all_rows = rows + [row3]
        self.assertEqual({"AAA"}, {r["instrument_identity"]["symbol"]["value"] for r in all_rows})
        self.assertEqual(3, len({r["observation_id"]["recorder_id"] for r in all_rows}))
        self.assertEqual(2, len({r["candidate_or_setup_identity"]["recorder_id"] for r in all_rows}))

    def test_same_source_identity_is_idempotent_and_conflict_stops_final(self) -> None:
        result = self.opened()
        start(result)
        initial = discovery(result)
        self.assertEqual("IDEMPOTENT_ACK", discovery(result).status)
        changed = fixture.discovery_payload()
        changed["observations"][0]["rank"] = evidence_present(2, fixture.OWNER)
        with self.assertRaises(ContinuousResearchExportConflict):
            discovery(result, changed)
        self.assertEqual(initial.raw_bytes, result.published()[1].raw_bytes)
        self.assertEqual("INCOMPLETE_NO_FINAL", finalize(result).status)

    def test_missing_conflicting_or_science_owned_authority_never_publishes(self) -> None:
        result = self.opened()
        start(result)
        discovery(result)
        for mutation in (
            lambda d: d.update(outcome_eligibility_commitment_sha256="a" * 64),
            lambda d: d.update(science_eligibility={"eligible": True}),
            lambda d: d["decision_time"].pop("authority"),
            lambda d: d["decision_id"].update(owner_id="conflicting-frozen-key"),
            lambda d: d.update(account_id="not-a-real-account"),
        ):
            facts = deepcopy(fixture.decision_payload())
            mutation(facts["decision_event"])
            before = inventory(self.root)
            with self.assertRaises(ValueError):
                decision(result, facts)
            self.assertEqual(before, inventory(self.root))

    def test_exact_bytes_go_to_two_independent_science_clocks(self) -> None:
        result = self.opened()
        start(result)
        discovery(result)
        decision(result)
        original = tuple(p.raw_bytes for p in result.published())
        proofs = []
        for index, clock in enumerate(("2026-09-02T14:00:00Z", "2026-09-02T14:00:01Z")):
            root = self.base / f"science-{index}"
            recorder = StrategyScienceRecorder(root, source_root_identity=fixture.SOURCE_ROOT, writer_instance_id=f"science-{index}", clock=fixture.FixedClock(clock))
            try:
                for raw in original:
                    self.assertEqual("ACCEPTED", recorder.accept(raw).status)
                self.assertTrue(recorder.verify(fixture.SESSION).all_hashes_valid)
                eligibility = fixture.stored_records(root, "science-eligibility")[0][1]["science_eligibility"]
                proofs.append((fixture.observation_receipt_hash(root), eligibility["commitment_payload_sha256"]))
            finally:
                recorder.close()
        self.assertNotEqual(proofs[0][0], proofs[1][0])
        self.assertNotEqual(proofs[0][1], proofs[1][1])
        self.assertEqual(original, tuple(p.raw_bytes for p in result.published()))

    def test_two_non_continuous_owners_bind_distinct_publication_identity(self) -> None:
        values = []
        for owner in ("opening-runtime-facts", "manual-replay-facts"):
            result = writer(self.base / owner, source_owner_identity=owner, source_interface_identity=f"{owner}-v2")
            try:
                parsed = parse_export_envelope_v2(start(result).raw_bytes)
                self.assertEqual(owner, parsed.source_owner_identity)
                self.assertEqual(f"{owner}-v2", parsed.source_interface_identity)
                values.append(parsed.source_event_fingerprint_sha256)
            finally:
                result.close()
        self.assertNotEqual(*values)

    def test_composed_start_event_and_final_fault_recovery_preserves_bytes(self) -> None:
        phases = (
            "after_start_raw_before_publication", "after_start_publication_before_checkpoint",
            "after_event_raw_before_publication", "after_event_publication_before_checkpoint",
            "after_final_raw_before_publication", "after_final_publication_before_checkpoint",
        )
        for phase in phases:
            with self.subTest(phase=phase):
                root = self.base / phase
                result = writer(root)
                if "start" not in phase:
                    start(result)
                if "final" in phase:
                    discovery(result)
                # Synthetic fault remains private to the canonical publisher;
                # no producer callback or crash API is added to the facade.
                result._publisher.crash_hook = fixture.crash_at(phase)
                action = start if "start" in phase else finalize if "final" in phase else discovery
                try:
                    with self.assertRaises(SimulatedPublicationCrash):
                        action(result)
                finally:
                    result.close()
                frozen = {p.name: p.read_bytes() for p in (root / "published").glob("*.json")}
                staged = [p.read_bytes() for p in (root / "staging").glob("*.json")]
                recovered = writer(root)
                try:
                    self.assertEqual("IDEMPOTENT_ACK", action(recovered).status)
                    published = [p.raw_bytes for p in recovered.published()]
                    for raw in [*frozen.values(), *staged]:
                        self.assertIn(raw, published)
                finally:
                    recovered.close()

    def test_root_isolation_rejects_omission_overlap_traversal_and_relative_paths(self) -> None:
        for updates in (
            {"science_custody_roots": []}, {"protected_roots": []},
            {"science_custody_roots": [self.root]}, {"protected_roots": [self.base]},
            {"science_custody_roots": [self.root / "child"]},
            {"export_root": Path("relative")}, {"export_root": self.root / ".." / "escape"},
            {"protected_roots": [Path("relative-protected")]},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                ResearchFactExporterV2(**configuration(self.root, **updates))
        self.assertFalse(self.root.exists())

    def test_static_external_hardlinks_are_rejected_before_initialization_writes(self) -> None:
        outside = self.base / "outside.txt"
        outside.write_bytes(b"authoritative-protected-bytes")
        self.root.mkdir()
        os.link(outside, self.root / ".writer.lock")
        with self.assertRaisesRegex(ValueError, "hardlink"):
            writer(self.root)
        self.assertEqual(b"authoritative-protected-bytes", outside.read_bytes())
        self.assertEqual({".writer.lock"}, {p.name for p in self.root.iterdir()})

    def test_static_symlink_or_junction_is_rejected_before_initialization_writes(self) -> None:
        target = self.base / "protected-runtime"
        target.mkdir()
        try:
            self.root.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            if os.name != "nt":
                self.skipTest(f"OS did not permit creation of a synthetic symlink: {exc}")
            import _winapi
            _winapi.CreateJunction(str(target), str(self.root))
        with self.assertRaisesRegex(ValueError, "symlink|reparse"):
            writer(self.root)
        self.assertEqual([], list(target.iterdir()))

    def test_alias_after_initialization_blocks_write_and_close_retains_lock(self) -> None:
        result = self.opened()
        start(result)
        alias = self.base / "external-metadata-alias"
        os.link(self.root / "publication-identity.json", alias)
        before = inventory(self.root)
        try:
            with self.assertRaisesRegex(ValueError, "hardlink"):
                discovery(result)
            with self.assertRaisesRegex(ValueError, "hardlink"):
                result.close()
            self.assertIsNotNone(result._publisher.lock.handle)
            self.assertEqual(before, inventory(self.root))
        finally:
            # Remove only this test's synthetic alias; production performs no
            # automatic repair or release through an ambiguous root.
            alias.unlink()
        result.close()
        self.assertIsNone(result._publisher.lock.handle)

    def test_reparse_attribute_is_rejected_even_without_symlink_bit(self) -> None:
        self.root.mkdir()
        real_lstat = Path.lstat
        def reparse(path, *args, **kwargs):
            info = real_lstat(path, *args, **kwargs)
            if path == self.root:
                from types import SimpleNamespace
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info
        with patch.object(Path, "lstat", reparse), self.assertRaisesRegex(ValueError, "reparse"):
            writer(self.root)
        self.assertEqual([], list(self.root.iterdir()))

    def test_publisher_internal_link_unlink_crash_is_recoverable(self) -> None:
        result = self.opened()
        start(result)
        original_unlink = Path.unlink
        def crash_before_stage_unlink(path, *args, **kwargs):
            if path.parent == self.root / "staging":
                raise SimulatedPublicationCrash("after-link-before-unlink")
            return original_unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", crash_before_stage_unlink), self.assertRaises(SimulatedPublicationCrash):
            discovery(result)
        result.close()
        recovered = self.opened()
        self.assertEqual("IDEMPOTENT_ACK", discovery(recovered).status)
        self.assertEqual(2, len(recovered.published()))
        self.assertEqual([], list((self.root / "staging").iterdir()))

    def test_historical_v1_readability_keeps_original_bytes_and_no_coercion_surface(self) -> None:
        path = self.base / "historical-v1.json"
        raw = historical.start_envelope()
        path.write_bytes(raw)
        before = sha256_hex(path.read_bytes())
        self.assertEqual("SESSION_MANIFEST", parse_export_envelope_v1(raw).event_type)
        with self.assertRaises(ValueError):
            parse_export_envelope_v2(raw)
        result = self.opened()
        start(result)
        self.assertEqual(before, sha256_hex(path.read_bytes()))
        self.assertEqual(raw, path.read_bytes())
        for name in ("publish_event", "accept", "ingest", "outcome_attachment", "science_callback", "set_eligibility", "upgrade_v1"):
            self.assertFalse(hasattr(result, name), name)

    def test_public_surface_has_no_runtime_provider_account_or_reverse_control_capability(self) -> None:
        allowed = {"initialize", "start", "discovery_cycle", "decision", "market_snapshot", "provider_health", "finalize", "published", "close"}
        public = {name for name, member in ResearchFactExporterV2.__dict__.items() if callable(member) and not name.startswith("_")}
        self.assertEqual(allowed, public)
        tree = ast.parse(Path(facade_module.__file__).read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
            elif isinstance(node, ast.Import):
                imports.extend(item.name for item in node.names)
        self.assertEqual({"__future__", "copy", "pathlib", "typing", "os", "stat", "momentum_hunter.continuous_research_export", "momentum_hunter.strategy_science_recorder.canonical", "momentum_hunter.strategy_science_recorder.contract"}, set(imports))
        self.assertNotIn("ContinuousResearchExporterV2", [base.id for node in tree.body if isinstance(node, ast.ClassDef) for base in node.bases if isinstance(base, ast.Name)])


if __name__ == "__main__":
    unittest.main()
