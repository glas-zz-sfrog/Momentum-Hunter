from __future__ import annotations

import ast
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from momentum_hunter.sequential_breakout_outcomes import (
    COHORT_INSUFFICIENT,
    COHORT_READY_FOR_LATER_ADJUDICATION,
    COHORT_THRESHOLD_UNSET,
    OUTCOME_COMPLETE,
    OUTCOME_GAP,
    OUTCOME_PENDING,
    OUTCOME_SESSION_UNAVAILABLE,
    SequentialBreakoutOutcomeError,
    SequentialBreakoutOutcomeLedger,
    SequentialBreakoutOutcomePolicy,
    SequentialBreakoutOutcomeStore,
    assess_outcome,
    build_cohort_snapshot,
    build_outcome_assessments,
    expected_outcome_id,
    outcome_fingerprint,
    outcome_ledger_to_wire,
    source_breakout_ledger_fingerprint,
    validate_cohort_snapshot,
    validate_outcome,
    validate_outcome_ledger,
)
from momentum_hunter.sequential_breakout_research import (
    BREAKOUT_CONFIRMED,
    HISTORICAL_REPLAY,
    PROSPECTIVE,
    RESEARCH_ONLY,
    SequentialBreakoutLedger,
    SequentialBreakoutPolicy,
    build_observation,
    detect_sequential_breakout_events,
    event_sort_key,
)


BASE = datetime.fromisoformat("2026-08-10T09:30:00-04:00")
FAMILY = "OPENING_BOOTSTRAP"


class SequentialBreakoutOutcomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "breakout-outcomes.json"
        self.source_policy = SequentialBreakoutPolicy(
            prior_range_bars=3,
            opening_range_bars=3,
            range_baseline_bars=3,
            volume_baseline_bars=3,
            impulse_window_bars=2,
            impulse_range_multiple=1.0,
            volume_confirmation_multiple=1.5,
            missed_range_multiple=0.5,
            pullback_range_multiple=0.25,
            exhaustion_range_multiple=3.0,
            max_sequence_bars=10,
            opening_range_start="09:30",
            opening_breakout_cutoff="10:30",
        )
        self.policy = SequentialBreakoutOutcomePolicy(horizons_minutes=(5,))

    def bar(
        self,
        minute: int,
        *,
        base: datetime = BASE,
        symbol: str = "ABC",
        mode: str = HISTORICAL_REPLAY,
        open: float = 9.9,
        high: float = 10.0,
        low: float = 9.8,
        close: float = 9.9,
        volume: float = 100.0,
        source: str = "SCHWAB_PRICE_HISTORY",
    ):
        provider = base + timedelta(minutes=minute)
        return build_observation(
            symbol=symbol,
            session_date=provider.date().isoformat(),
            provider_timestamp=provider,
            receipt_timestamp=provider + timedelta(seconds=1),
            open=open,
            high=high,
            low=low,
            close=close,
            volume=volume,
            source=source,
            source_state="RECONCILED",
            observation_mode=mode,
        )

    def source_ledger(
        self,
        *,
        symbol: str = "ABC",
        mode: str = HISTORICAL_REPLAY,
        base: datetime = BASE,
    ) -> SequentialBreakoutLedger:
        observations = (
            self.bar(0, symbol=symbol, mode=mode, base=base),
            self.bar(1, symbol=symbol, mode=mode, base=base),
            self.bar(2, symbol=symbol, mode=mode, base=base),
            self.bar(
                3,
                symbol=symbol,
                mode=mode,
                base=base,
                open=10.05,
                high=10.30,
                low=10.01,
                close=10.20,
                volume=200.0,
            ),
        )
        events = detect_sequential_breakout_events(
            observations,
            originating_evidence_family=FAMILY,
            policy=self.source_policy,
        )
        self.assertIn(BREAKOUT_CONFIRMED, [event.event_type for event in events])
        return SequentialBreakoutLedger(policy=self.source_policy, events=events)

    def anchor(self, ledger: SequentialBreakoutLedger):
        return next(
            event for event in ledger.events if event.event_type == BREAKOUT_CONFIRMED
        )

    def forward_bars(
        self,
        *,
        symbol: str = "ABC",
        mode: str = HISTORICAL_REPLAY,
        base: datetime = BASE,
    ):
        return (
            self.bar(
                4,
                symbol=symbol,
                mode=mode,
                base=base,
                open=10.20,
                high=10.35,
                low=10.10,
                close=10.30,
                volume=140.0,
            ),
            self.bar(
                5,
                symbol=symbol,
                mode=mode,
                base=base,
                open=10.30,
                high=10.32,
                low=10.05,
                close=10.10,
                volume=120.0,
            ),
            self.bar(
                6,
                symbol=symbol,
                mode=mode,
                base=base,
                open=10.10,
                high=10.15,
                low=9.80,
                close=9.90,
                volume=160.0,
            ),
            self.bar(
                7,
                symbol=symbol,
                mode=mode,
                base=base,
                open=9.90,
                high=10.45,
                low=9.90,
                close=10.40,
                volume=180.0,
            ),
            self.bar(
                8,
                symbol=symbol,
                mode=mode,
                base=base,
                open=10.40,
                high=10.60,
                low=10.30,
                close=10.50,
                volume=190.0,
            ),
        )

    def assess(
        self,
        ledger: SequentialBreakoutLedger | None = None,
        bars=None,
        *,
        as_of: datetime | None = None,
        previous=(),
        policy: SequentialBreakoutOutcomePolicy | None = None,
    ):
        source = ledger or self.source_ledger()
        selected_bars = self.forward_bars() if bars is None else tuple(bars)
        event = self.anchor(source)
        identity = (event.symbol, event.session_date)
        return build_outcome_assessments(
            source,
            {identity: selected_bars},
            as_of=as_of or (BASE + timedelta(minutes=8, seconds=2)),
            policy=policy or self.policy,
            previous_outcomes=previous,
        )

    def test_complete_outcome_preserves_identity_and_metrics(self) -> None:
        ledger = self.source_ledger()
        outcome = self.assess(ledger)[0]
        event = self.anchor(ledger)
        self.assertEqual(outcome.status, OUTCOME_COMPLETE)
        self.assertEqual(outcome.source_event_id, event.event_id)
        self.assertEqual(outcome.opportunity_id, event.opportunity_id)
        self.assertEqual(outcome.setup_id, event.setup_id)
        self.assertEqual(outcome.observed_bar_count, 5)
        self.assertEqual(outcome.outcome_close, 10.5)
        self.assertAlmostEqual(outcome.forward_return_pct, 2.941176, places=6)
        self.assertAlmostEqual(
            outcome.max_favorable_excursion_pct, 3.921569, places=6
        )
        self.assertAlmostEqual(
            outcome.max_adverse_excursion_pct, -3.921569, places=6
        )
        self.assertFalse(outcome.held_above_trigger)
        self.assertTrue(outcome.failed_below_trigger)
        self.assertEqual(outcome.first_failure_timestamp, self.forward_bars()[2].provider_timestamp)
        self.assertEqual(outcome.authority, RESEARCH_ONLY)
        self.assertFalse(outcome.execution_authority)
        self.assertFalse(outcome.conclusion_authority)

    def test_bars_after_exact_horizon_cannot_change_outcome(self) -> None:
        ledger = self.source_ledger()
        bars = self.forward_bars()
        later = bars + (
            self.bar(9, open=10.5, high=50.0, low=1.0, close=40.0),
            self.bar(10, open=40.0, high=60.0, low=0.5, close=2.0),
        )
        as_of = BASE + timedelta(minutes=10, seconds=2)
        first = self.assess(ledger, bars, as_of=as_of)[0]
        second = self.assess(ledger, later, as_of=as_of)[0]
        self.assertEqual(first, second)

    def test_unrelated_new_event_does_not_revise_existing_outcome(self) -> None:
        first_ledger = self.source_ledger(symbol="ABC")
        first = self.assess(first_ledger)[0]
        second_ledger = self.source_ledger(symbol="XYZ")
        expanded = SequentialBreakoutLedger(
            policy=self.source_policy,
            events=tuple(
                sorted(first_ledger.events + second_ledger.events, key=event_sort_key)
            ),
        )
        outcomes = build_outcome_assessments(
            expanded,
            {
                ("ABC", "2026-08-10"): self.forward_bars(symbol="ABC"),
                ("XYZ", "2026-08-10"): self.forward_bars(symbol="XYZ"),
            },
            as_of=BASE + timedelta(minutes=9),
            policy=self.policy,
            previous_outcomes=(first,),
        )
        retained = next(
            outcome for outcome in outcomes if outcome.source_event_id == first.source_event_id
        )
        self.assertEqual(retained, first)

    def test_pending_window_reports_no_partial_metrics(self) -> None:
        ledger = self.source_ledger()
        pending = self.assess(
            ledger,
            self.forward_bars()[:2],
            as_of=BASE + timedelta(minutes=6, seconds=2),
        )[0]
        self.assertEqual(pending.status, OUTCOME_PENDING)
        self.assertEqual(pending.observed_bar_count, 0)
        self.assertIsNone(pending.forward_return_pct)
        self.assertIsNone(pending.max_favorable_excursion_pct)

    def test_pending_to_complete_is_append_only_revision(self) -> None:
        ledger = self.source_ledger()
        pending = self.assess(
            ledger,
            self.forward_bars()[:2],
            as_of=BASE + timedelta(minutes=6, seconds=2),
        )[0]
        complete = self.assess(ledger, previous=(pending,))[0]
        self.assertEqual(complete.status, OUTCOME_COMPLETE)
        self.assertEqual(complete.revision, 2)
        self.assertEqual(complete.previous_outcome_id, pending.outcome_id)
        self.assertFalse(complete.corrected)

    def test_gap_is_explicit_and_has_no_performance_metrics(self) -> None:
        bars = self.forward_bars()
        gap = self.assess(bars=bars[:2] + bars[3:])[0]
        self.assertEqual(gap.status, OUTCOME_GAP)
        self.assertEqual(gap.observed_bar_count, 4)
        self.assertIsNone(gap.forward_return_pct)
        self.assertIn("missing 1", gap.reason)

    def test_late_gap_backfill_is_a_new_revision(self) -> None:
        ledger = self.source_ledger()
        bars = self.forward_bars()
        gap = self.assess(ledger, bars[:2] + bars[3:])[0]
        complete = self.assess(ledger, bars, previous=(gap,))[0]
        self.assertEqual(complete.revision, 2)
        self.assertEqual(complete.previous_outcome_id, gap.outcome_id)
        self.assertTrue(complete.corrected)

    def test_completed_bar_correction_is_preserved_as_revision(self) -> None:
        ledger = self.source_ledger()
        complete = self.assess(ledger)[0]
        bars = list(self.forward_bars())
        bars[-1] = self.bar(
            8,
            open=10.40,
            high=10.70,
            low=10.30,
            close=10.60,
            volume=195.0,
        )
        corrected = self.assess(ledger, bars, previous=(complete,))[0]
        self.assertEqual(corrected.revision, 2)
        self.assertTrue(corrected.corrected)
        self.assertNotEqual(corrected.source_bar_fingerprints, complete.source_bar_fingerprints)
        self.assertEqual(corrected.outcome_close, 10.6)

    def test_completed_outcome_cannot_regress_to_gap(self) -> None:
        ledger = self.source_ledger()
        complete = self.assess(ledger)[0]
        bars = self.forward_bars()
        with self.assertRaisesRegex(SequentialBreakoutOutcomeError, "cannot regress"):
            self.assess(ledger, bars[:-1], previous=(complete,))

    def test_horizon_beyond_same_session_is_unavailable(self) -> None:
        ledger = self.source_ledger()
        policy = replace(self.policy, session_end_time="09:36")
        outcome = self.assess(
            ledger,
            (),
            as_of=BASE + timedelta(minutes=10),
            policy=policy,
        )[0]
        self.assertEqual(outcome.status, OUTCOME_SESSION_UNAVAILABLE)
        self.assertIsNone(outcome.forward_return_pct)
        self.assertIn("same-session", outcome.reason)

    def test_multi_horizon_policy_preserves_pending_denominator(self) -> None:
        policy = SequentialBreakoutOutcomePolicy(horizons_minutes=(5, 15))
        outcomes = self.assess(policy=policy)
        self.assertEqual([item.horizon_minutes for item in outcomes], [5, 15])
        self.assertEqual(outcomes[0].status, OUTCOME_COMPLETE)
        self.assertEqual(outcomes[1].status, OUTCOME_PENDING)

    def test_historical_rows_never_satisfy_prospective_threshold(self) -> None:
        ledger = self.source_ledger(mode=HISTORICAL_REPLAY)
        policy = replace(self.policy, minimum_prospective_events=1)
        outcomes = self.assess(ledger, policy=policy)
        snapshot = build_cohort_snapshot(
            ledger,
            outcomes,
            created_at=BASE + timedelta(minutes=9),
            policy=policy,
        )
        self.assertEqual(snapshot.historical_anchor_event_count, 1)
        self.assertEqual(snapshot.prospective_anchor_event_count, 0)
        self.assertEqual(snapshot.cohort_status, COHORT_INSUFFICIENT)
        self.assertFalse(snapshot.conclusions_authorized)

    def test_unset_cohort_threshold_withholds_readiness(self) -> None:
        ledger = self.source_ledger(mode=PROSPECTIVE)
        bars = self.forward_bars(mode=PROSPECTIVE)
        outcomes = self.assess(ledger, bars)
        snapshot = build_cohort_snapshot(
            ledger,
            outcomes,
            created_at=BASE + timedelta(minutes=9),
            policy=self.policy,
        )
        self.assertEqual(snapshot.cohort_status, COHORT_THRESHOLD_UNSET)
        self.assertFalse(snapshot.conclusions_authorized)

    def test_prospective_minimum_only_unlocks_later_adjudication(self) -> None:
        first = self.source_ledger(symbol="ABC", mode=PROSPECTIVE)
        second = self.source_ledger(symbol="XYZ", mode=PROSPECTIVE)
        ledger = SequentialBreakoutLedger(
            policy=self.source_policy,
            events=tuple(sorted(first.events + second.events, key=event_sort_key)),
        )
        policy = replace(self.policy, minimum_prospective_events=2)
        observations = {
            ("ABC", "2026-08-10"): self.forward_bars(
                symbol="ABC", mode=PROSPECTIVE
            ),
            ("XYZ", "2026-08-10"): self.forward_bars(
                symbol="XYZ", mode=PROSPECTIVE
            ),
        }
        outcomes = build_outcome_assessments(
            ledger,
            observations,
            as_of=BASE + timedelta(minutes=9),
            policy=policy,
        )
        snapshot = build_cohort_snapshot(
            ledger,
            outcomes,
            created_at=BASE + timedelta(minutes=9),
            policy=policy,
        )
        self.assertEqual(snapshot.prospective_anchor_event_count, 2)
        self.assertEqual(snapshot.cohort_status, COHORT_READY_FOR_LATER_ADJUDICATION)
        self.assertFalse(snapshot.conclusions_authorized)
        prospective = next(
            summary
            for summary in snapshot.summaries
            if summary.observation_mode == PROSPECTIVE
        )
        self.assertEqual(prospective.eligible_event_count, 2)
        self.assertEqual(prospective.complete_count, 2)

    def test_prospective_threshold_stays_blocked_while_horizon_is_pending(self) -> None:
        policy = SequentialBreakoutOutcomePolicy(
            horizons_minutes=(5, 15),
            minimum_prospective_events=1,
        )
        ledger = self.source_ledger(mode=PROSPECTIVE)
        outcomes = self.assess(
            ledger,
            self.forward_bars(mode=PROSPECTIVE),
            policy=policy,
        )
        snapshot = build_cohort_snapshot(
            ledger,
            outcomes,
            created_at=BASE + timedelta(minutes=9),
            policy=policy,
        )
        self.assertEqual(snapshot.cohort_status, COHORT_INSUFFICIENT)
        pending_summary = next(
            summary
            for summary in snapshot.summaries
            if summary.observation_mode == PROSPECTIVE
            and summary.horizon_minutes == 15
        )
        self.assertEqual(pending_summary.pending_count, 1)
        self.assertFalse(snapshot.conclusions_authorized)

    def test_missing_outcome_is_visible_in_cohort_denominator(self) -> None:
        ledger = self.source_ledger(mode=PROSPECTIVE)
        snapshot = build_cohort_snapshot(
            ledger,
            (),
            created_at=BASE + timedelta(minutes=9),
            policy=self.policy,
        )
        summary = next(
            item
            for item in snapshot.summaries
            if item.observation_mode == PROSPECTIVE
        )
        self.assertEqual(summary.eligible_event_count, 1)
        self.assertEqual(summary.missing_outcome_count, 1)
        self.assertEqual(summary.complete_count, 0)

    def test_source_event_denominator_includes_ineligible_sequence_events(self) -> None:
        ledger = self.source_ledger()
        outcomes = self.assess(ledger)
        snapshot = build_cohort_snapshot(
            ledger,
            outcomes,
            created_at=BASE + timedelta(minutes=9),
            policy=self.policy,
        )
        self.assertGreater(snapshot.source_event_count, snapshot.eligible_anchor_event_count)
        self.assertEqual(
            snapshot.source_event_count,
            snapshot.eligible_anchor_event_count
            + snapshot.ineligible_source_event_count,
        )

    def test_store_is_idempotent_and_preserves_revision_chain(self) -> None:
        ledger = self.source_ledger()
        pending = self.assess(
            ledger,
            self.forward_bars()[:2],
            as_of=BASE + timedelta(minutes=6, seconds=2),
        )[0]
        complete = self.assess(ledger, previous=(pending,))[0]
        store = SequentialBreakoutOutcomeStore(self.path, policy=self.policy)
        first = store.append((pending, complete))
        before = self.path.read_bytes()
        second = store.append((pending, complete))
        self.assertEqual(first, second)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual([item.revision for item in second.outcomes], [1, 2])

    def test_atomic_replace_failure_preserves_prior_ledger(self) -> None:
        ledger = self.source_ledger()
        pending = self.assess(
            ledger,
            self.forward_bars()[:2],
            as_of=BASE + timedelta(minutes=6, seconds=2),
        )[0]
        complete = self.assess(ledger, previous=(pending,))[0]
        store = SequentialBreakoutOutcomeStore(self.path, policy=self.policy)
        stored = store.append((pending,))
        before = self.path.read_bytes()
        with mock.patch(
            "momentum_hunter.sequential_breakout_outcomes.os.replace",
            side_effect=OSError("synthetic replacement failure"),
        ):
            with self.assertRaisesRegex(OSError, "synthetic replacement failure"):
                store.append((complete,))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(store.load(), stored)

    def test_store_rejects_stale_revision_branch(self) -> None:
        ledger = self.source_ledger()
        pending = self.assess(
            ledger,
            self.forward_bars()[:2],
            as_of=BASE + timedelta(minutes=6, seconds=2),
        )[0]
        complete = self.assess(ledger, previous=(pending,))[0]
        store = SequentialBreakoutOutcomeStore(self.path, policy=self.policy)
        store.append((pending, complete))
        branch = replace(complete, revision=2, previous_outcome_id=pending.outcome_id)
        branch = replace(branch, outcome_close=10.7, forward_return_pct=4.901961)
        branch = self.rehash(branch)
        with self.assertRaisesRegex(SequentialBreakoutOutcomeError, "stale evidence"):
            store.append((branch,))

    def test_tampered_file_fails_closed(self) -> None:
        outcome = self.assess()[0]
        store = SequentialBreakoutOutcomeStore(self.path, policy=self.policy)
        store.append((outcome,))
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["outcomes"][0]["reason"] = "tampered"
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(SequentialBreakoutOutcomeError, "ID|fingerprint"):
            store.load()

    def test_forged_authority_fails_even_when_rehashed(self) -> None:
        forged = replace(self.assess()[0], execution_authority=True)
        forged = self.rehash(forged)
        with self.assertRaisesRegex(SequentialBreakoutOutcomeError, "gain authority"):
            validate_outcome(forged, policy=self.policy)

    def test_rehashed_source_field_tamper_fails_cohort_binding(self) -> None:
        ledger = self.source_ledger()
        forged = replace(self.assess(ledger)[0], setup_family="RECLAIM")
        forged = self.rehash(forged)
        with self.assertRaisesRegex(
            SequentialBreakoutOutcomeError, "setup_family.*source event"
        ):
            build_cohort_snapshot(
                ledger,
                (forged,),
                created_at=BASE + timedelta(minutes=9),
                policy=self.policy,
            )

    def test_rehashed_bar_timestamp_tamper_fails_structural_validation(self) -> None:
        outcome = self.assess()[0]
        timestamps = list(outcome.source_bar_timestamps)
        timestamps[1] = timestamps[0]
        forged = replace(outcome, source_bar_timestamps=tuple(timestamps))
        forged = self.rehash(forged)
        with self.assertRaisesRegex(
            SequentialBreakoutOutcomeError, "duplicated or nonchronological"
        ):
            validate_outcome(forged, policy=self.policy)

    def test_source_evidence_is_not_mutated(self) -> None:
        ledger = self.source_ledger()
        bars = self.forward_bars()
        before_ledger = asdict(ledger)
        before_bars = tuple(asdict(bar) for bar in bars)
        self.assess(ledger, bars)
        self.assertEqual(asdict(ledger), before_ledger)
        self.assertEqual(tuple(asdict(bar) for bar in bars), before_bars)

    def test_source_ledger_fingerprint_is_deterministic(self) -> None:
        ledger = self.source_ledger()
        first = source_breakout_ledger_fingerprint(ledger)
        second = source_breakout_ledger_fingerprint(ledger)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_ledger_and_cohort_validation_reject_contradictions(self) -> None:
        outcome = self.assess()[0]
        malformed = replace(outcome, observed_bar_count=4)
        malformed = self.rehash(malformed)
        with self.assertRaisesRegex(SequentialBreakoutOutcomeError, "observed bar count"):
            validate_outcome(malformed, policy=self.policy)

        ledger = SequentialBreakoutOutcomeLedger(
            policy=self.policy,
            outcomes=(outcome,),
        )
        validate_outcome_ledger(ledger)
        snapshot = build_cohort_snapshot(
            self.source_ledger(),
            (outcome,),
            created_at=BASE + timedelta(minutes=9),
            policy=self.policy,
        )
        forged_snapshot = replace(snapshot, conclusions_authorized=True)
        with self.assertRaisesRegex(SequentialBreakoutOutcomeError, "gain authority"):
            validate_cohort_snapshot(forged_snapshot, policy=self.policy)

    def test_policy_rejects_implicit_or_nonminute_windows(self) -> None:
        with self.assertRaisesRegex(SequentialBreakoutOutcomeError, "at least one"):
            SequentialBreakoutOutcomeStore(
                self.path,
                policy=SequentialBreakoutOutcomePolicy(horizons_minutes=()),
            )
        with self.assertRaisesRegex(SequentialBreakoutOutcomeError, "one-minute"):
            SequentialBreakoutOutcomeStore(
                self.path,
                policy=SequentialBreakoutOutcomePolicy(expected_bar_seconds=30),
            )

    def test_module_has_no_runtime_or_provider_capability(self) -> None:
        module_path = (
            Path(__file__).resolve().parents[1]
            / "momentum_hunter"
            / "sequential_breakout_outcomes.py"
        )
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        forbidden_imports = {
            "requests",
            "urllib",
            "httpx",
            "socket",
            "websocket",
            "subprocess",
        }
        forbidden_names = {
            "submit_order",
            "cancel_order",
            "replace_order",
            "TradePlan",
            "RiskGovernor",
            "score_candidate",
            "readiness",
        }
        imported = {
            node.names[0].name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
        }
        imported.update(
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        attributes = {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        self.assertFalse(imported & forbidden_imports)
        self.assertFalse((names | attributes) & forbidden_names)

        root = Path(__file__).resolve().parents[1]
        importers: list[str] = []
        for path in (root / "momentum_hunter").rglob("*.py"):
            if path == module_path:
                continue
            parsed = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(parsed):
                if isinstance(node, ast.ImportFrom) and node.module == (
                    "momentum_hunter.sequential_breakout_outcomes"
                ):
                    importers.append(path.relative_to(root).as_posix())
                if isinstance(node, ast.Import) and any(
                    alias.name == "momentum_hunter.sequential_breakout_outcomes"
                    for alias in node.names
                ):
                    importers.append(path.relative_to(root).as_posix())
        self.assertEqual(importers, [])

    @staticmethod
    def rehash(outcome):
        without_identity = replace(outcome, outcome_id="", fingerprint="")
        with_identity = replace(
            without_identity,
            outcome_id=expected_outcome_id(without_identity),
        )
        return replace(with_identity, fingerprint=outcome_fingerprint(with_identity))


if __name__ == "__main__":
    unittest.main()
