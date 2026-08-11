from __future__ import annotations

import ast
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from momentum_hunter.macro_event_context import (
    BLOCK_NEW_ENTRY,
    CANCELLED,
    CAUTION,
    COMPANY_EARNINGS,
    CRITICAL,
    CURRENT,
    DATA_STALE,
    FED_DECISION,
    FED_SPEAKER,
    HIGH,
    INFLATION_RELEASE,
    JOBS_REPORT,
    LOW,
    MARKET,
    MARKET_HOLIDAY,
    MEDIUM,
    NORMAL,
    NO_SCORE_AUTHORITY,
    APPROVED_OTHER,
    EARLY_CLOSE,
    SECTOR,
    STALE,
    SYMBOL,
    TREASURY_AUCTION,
    UNKNOWN,
    CalendarEvent,
    EventCalendarStore,
    EventConsequenceRule,
    EventDefinition,
    EventRiskPolicy,
    EventRiskTarget,
    MacroEventContextError,
    build_event_calendar,
    evaluate_event_risk,
    expected_event_id,
    fan_out_event_risk,
)


BASE = datetime(2026, 8, 10, 13, 0, tzinfo=timezone.utc)


class MacroEventContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = policy()

    def calendar(self, *definitions: EventDefinition, **kwargs):
        return build_event_calendar(
            definitions=definitions,
            generated_at=kwargs.pop("generated_at", BASE),
            valid_through=kwargs.pop("valid_through", BASE + timedelta(hours=10)),
            **kwargs,
        )

    def evaluate(self, calendar, **kwargs):
        return evaluate_event_risk(
            calendar=calendar,
            policy=kwargs.pop("policy", self.policy),
            evaluated_at=kwargs.pop("evaluated_at", BASE + timedelta(hours=1)),
            **kwargs,
        )

    def test_market_event_blocks_new_entry_under_explicit_policy(self) -> None:
        definition = event(FED_DECISION, HIGH, scope=MARKET)
        calendar = self.calendar(definition)

        context = self.evaluate(calendar)

        self.assertEqual(BLOCK_NEW_ENTRY, context.status)
        self.assertEqual((expected_event_id(definition.source_identity, definition.source_event_id),), context.active_event_ids)
        self.assertEqual(self.policy, context.policy)
        self.assertEqual(self.policy.fingerprint, context.policy_fingerprint)
        self.assertEqual(NO_SCORE_AUTHORITY, context.score_authority)
        self.assertFalse(context.can_initiate_trade)

    def test_lower_importance_market_event_produces_caution(self) -> None:
        calendar = self.calendar(event(FED_SPEAKER, MEDIUM, scope=MARKET))

        context = self.evaluate(calendar)

        self.assertEqual(CAUTION, context.status)
        self.assertEqual("ACTIVE_EVENT_POLICY_APPLIED", context.reason)

    def test_no_active_event_is_normal(self) -> None:
        calendar = self.calendar(event(FED_DECISION, HIGH, scope=MARKET))

        context = self.evaluate(
            calendar,
            evaluated_at=BASE + timedelta(minutes=10),
        )

        self.assertEqual(NORMAL, context.status)
        self.assertEqual((), context.active_event_ids)

    def test_strongest_active_consequence_wins(self) -> None:
        calendar = self.calendar(
            event(FED_SPEAKER, MEDIUM, scope=MARKET, source_event_id="speaker"),
            event(FED_DECISION, HIGH, scope=MARKET, source_event_id="decision"),
        )

        context = self.evaluate(calendar)

        self.assertEqual(BLOCK_NEW_ENTRY, context.status)
        self.assertEqual(2, len(context.active_event_ids))

    def test_expired_calendar_is_data_stale(self) -> None:
        calendar = self.calendar(
            event(FED_DECISION, HIGH, scope=MARKET),
            valid_through=BASE + timedelta(minutes=30),
        )

        context = self.evaluate(calendar)

        self.assertEqual(DATA_STALE, context.status)
        self.assertEqual("CALENDAR_VALIDITY_EXPIRED", context.reason)

    def test_active_unknown_or_stale_event_fails_closed(self) -> None:
        for state in (UNKNOWN, STALE):
            with self.subTest(state=state):
                calendar = self.calendar(
                    event(FED_DECISION, HIGH, scope=MARKET, evidence_state=state)
                )
                context = self.evaluate(calendar)
                self.assertEqual(DATA_STALE, context.status)
                self.assertEqual("ACTIVE_EVENT_EVIDENCE_UNSAFE", context.reason)

    def test_cancelled_event_is_not_active_context(self) -> None:
        calendar = self.calendar(
            event(FED_DECISION, HIGH, scope=MARKET, evidence_state=CANCELLED)
        )

        context = self.evaluate(calendar)

        self.assertEqual(NORMAL, context.status)
        self.assertEqual((), context.active_event_ids)

    def test_cancelled_event_is_not_listed_when_calendar_is_expired(self) -> None:
        calendar = self.calendar(
            event(FED_DECISION, HIGH, scope=MARKET, evidence_state=CANCELLED),
            valid_through=BASE + timedelta(minutes=30),
        )

        context = self.evaluate(calendar)

        self.assertEqual(DATA_STALE, context.status)
        self.assertEqual((), context.active_event_ids)

    def test_missing_policy_rule_fails_closed(self) -> None:
        calendar = self.calendar(event(COMPANY_EARNINGS, HIGH, scope=SYMBOL, symbols=("NVDA",)))
        incomplete = replace(
            self.policy,
            rules=tuple(
                rule for rule in self.policy.rules if rule.category != COMPANY_EARNINGS
            ),
        )

        context = self.evaluate(
            calendar,
            policy=incomplete,
            target=EventRiskTarget("opportunity-nvda", "NVDA"),
        )

        self.assertEqual(DATA_STALE, context.status)
        self.assertEqual("ACTIVE_EVENT_POLICY_RULE_MISSING", context.reason)

    def test_symbol_scope_does_not_leak_to_other_candidate(self) -> None:
        calendar = self.calendar(
            event(COMPANY_EARNINGS, HIGH, scope=SYMBOL, symbols=("NVDA",))
        )

        nvda = self.evaluate(
            calendar,
            target=EventRiskTarget("opportunity-nvda", "NVDA"),
        )
        amd = self.evaluate(
            calendar,
            target=EventRiskTarget("opportunity-amd", "AMD"),
        )

        self.assertEqual(CAUTION, nvda.status)
        self.assertEqual(NORMAL, amd.status)

    def test_sector_scope_requires_matching_sector_mapping(self) -> None:
        calendar = self.calendar(
            event(FED_SPEAKER, MEDIUM, scope=SECTOR, sectors=("XLK",))
        )

        matching = self.evaluate(
            calendar,
            target=EventRiskTarget("opportunity-nvda", "NVDA", "XLK"),
        )
        unavailable = self.evaluate(
            calendar,
            target=EventRiskTarget("opportunity-nvda", "NVDA"),
        )

        self.assertEqual(CAUTION, matching.status)
        self.assertEqual(NORMAL, unavailable.status)

    def test_market_level_context_excludes_symbol_only_events(self) -> None:
        calendar = self.calendar(
            event(COMPANY_EARNINGS, HIGH, scope=SYMBOL, symbols=("NVDA",))
        )

        context = self.evaluate(calendar)

        self.assertEqual(NORMAL, context.status)

    def test_context_replay_is_deterministic(self) -> None:
        calendar = self.calendar(event(FED_DECISION, HIGH, scope=MARKET))

        first = self.evaluate(calendar)
        second = self.evaluate(calendar)

        self.assertEqual(first, second)
        self.assertEqual(first.context_id, second.context_id)
        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_future_calendar_cannot_create_lookahead_context(self) -> None:
        calendar = self.calendar(
            event(FED_DECISION, HIGH, scope=MARKET),
            generated_at=BASE + timedelta(minutes=10),
            valid_through=BASE + timedelta(hours=10),
        )

        with self.assertRaisesRegex(MacroEventContextError, "generated in the future"):
            self.evaluate(calendar, evaluated_at=BASE + timedelta(minutes=5))


class EventCalendarIdentityTests(unittest.TestCase):
    def test_all_architecture_approved_event_categories_are_modeled(self) -> None:
        categories = {
            FED_DECISION,
            FED_SPEAKER,
            INFLATION_RELEASE,
            JOBS_REPORT,
            TREASURY_AUCTION,
            COMPANY_EARNINGS,
            MARKET_HOLIDAY,
            EARLY_CLOSE,
            APPROVED_OTHER,
        }
        definitions = tuple(
            event(
                category,
                LOW,
                scope=MARKET,
                source_event_id=f"event-{index}",
            )
            for index, category in enumerate(sorted(categories))
        )

        calendar = build_event_calendar(
            definitions=definitions,
            generated_at=BASE,
            valid_through=BASE + timedelta(hours=10),
        )

        self.assertEqual(categories, {item.category for item in calendar.events})

    def test_snapshot_is_order_independent_and_deterministic(self) -> None:
        first = event(FED_DECISION, HIGH, scope=MARKET, source_event_id="b")
        second = event(FED_SPEAKER, MEDIUM, scope=MARKET, source_event_id="a")

        one = build_event_calendar(
            definitions=(first, second),
            generated_at=BASE,
            valid_through=BASE + timedelta(hours=10),
        )
        two = build_event_calendar(
            definitions=(second, first),
            generated_at=BASE,
            valid_through=BASE + timedelta(hours=10),
        )

        self.assertEqual(one, two)
        self.assertEqual(one.calendar_id, two.calendar_id)

    def test_calendar_build_does_not_mutate_source_definitions(self) -> None:
        definition = event(FED_DECISION, HIGH, scope=MARKET)
        before = repr(definition)

        build_event_calendar(
            definitions=(definition,),
            generated_at=BASE,
            valid_through=BASE + timedelta(hours=10),
        )

        self.assertEqual(before, repr(definition))

    def test_same_revision_identity_cannot_change_event(self) -> None:
        original = event(FED_DECISION, HIGH, scope=MARKET)
        first = build_event_calendar(
            definitions=(original,),
            generated_at=BASE,
            valid_through=BASE + timedelta(hours=10),
        )
        changed = replace(original, title="Changed without a new revision")

        with self.assertRaisesRegex(MacroEventContextError, "revision identity"):
            build_event_calendar(
                definitions=(changed,),
                generated_at=BASE + timedelta(minutes=1),
                valid_through=BASE + timedelta(hours=10),
                previous_snapshot=first,
            )

    def test_new_revision_preserves_predecessor_calendar(self) -> None:
        original = event(FED_DECISION, HIGH, scope=MARKET)
        first = build_event_calendar(
            definitions=(original,),
            generated_at=BASE,
            valid_through=BASE + timedelta(hours=10),
        )
        revised = replace(
            original,
            revision_identity="revision-2",
            title="Revised source title",
        )

        second = build_event_calendar(
            definitions=(revised,),
            generated_at=BASE + timedelta(minutes=1),
            valid_through=BASE + timedelta(hours=10),
            previous_snapshot=first,
        )

        self.assertEqual(first.calendar_id, second.previous_calendar_id)
        self.assertEqual(first.events[0].event_id, second.events[0].event_id)
        self.assertNotEqual(first.events[0].fingerprint, second.events[0].fingerprint)
        self.assertEqual(2, second.sequence)

    def test_explicit_sequence_cannot_skip_the_chain(self) -> None:
        with self.assertRaisesRegex(MacroEventContextError, "sequence"):
            build_event_calendar(
                definitions=(),
                generated_at=BASE,
                valid_through=BASE + timedelta(hours=10),
                sequence=2,
            )

    def test_event_source_and_window_chronology_are_validated(self) -> None:
        bad_source = replace(
            event(FED_DECISION, HIGH, scope=MARKET),
            provider_timestamp=(BASE - timedelta(minutes=1)).isoformat(),
            receipt_timestamp=(BASE - timedelta(minutes=2)).isoformat(),
        )
        with self.assertRaisesRegex(MacroEventContextError, "source chronology"):
            build_event_calendar(
                definitions=(bad_source,),
                generated_at=BASE,
                valid_through=BASE + timedelta(hours=10),
            )

        good = event(FED_DECISION, HIGH, scope=MARKET)
        bad_window = replace(good, risk_window_start=good.scheduled_end)
        with self.assertRaisesRegex(MacroEventContextError, "windows"):
            build_event_calendar(
                definitions=(bad_window,),
                generated_at=BASE,
                valid_through=BASE + timedelta(hours=10),
            )

    def test_scope_shape_is_fail_closed(self) -> None:
        bad = event(FED_DECISION, HIGH, scope=MARKET, symbols=("NVDA",))

        with self.assertRaisesRegex(MacroEventContextError, "Market-wide"):
            build_event_calendar(
                definitions=(bad,),
                generated_at=BASE,
                valid_through=BASE + timedelta(hours=10),
            )


class EventFanOutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = policy()
        self.calendar = build_event_calendar(
            definitions=(
                event(COMPANY_EARNINGS, HIGH, scope=SYMBOL, symbols=("NVDA",)),
            ),
            generated_at=BASE,
            valid_through=BASE + timedelta(hours=10),
        )

    def test_fan_out_preserves_candidate_order_and_scope(self) -> None:
        contexts = fan_out_event_risk(
            calendar=self.calendar,
            policy=self.policy,
            evaluated_at=BASE + timedelta(hours=1),
            targets=(
                EventRiskTarget("opportunity-amd", "AMD"),
                EventRiskTarget("opportunity-nvda", "NVDA"),
            ),
        )

        self.assertEqual(("AMD", "NVDA"), tuple(item.target_symbol for item in contexts))
        self.assertEqual((NORMAL, CAUTION), tuple(item.status for item in contexts))

    def test_fan_out_limit_and_duplicate_identity_fail_closed(self) -> None:
        too_many = tuple(
            EventRiskTarget(f"opportunity-{index}", f"A{index}")
            for index in range(self.policy.maximum_candidate_fan_out + 1)
        )
        with self.assertRaisesRegex(MacroEventContextError, "bounded candidate"):
            fan_out_event_risk(
                calendar=self.calendar,
                policy=self.policy,
                evaluated_at=BASE + timedelta(hours=1),
                targets=too_many,
            )

        with self.assertRaisesRegex(MacroEventContextError, "repeated an opportunity"):
            fan_out_event_risk(
                calendar=self.calendar,
                policy=self.policy,
                evaluated_at=BASE + timedelta(hours=1),
                targets=(
                    EventRiskTarget("same", "AMD"),
                    EventRiskTarget("same", "NVDA"),
                ),
            )


class EventCalendarStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "event-calendar.json"
        self.store = EventCalendarStore(self.path)

    def snapshot(self, *, previous=None, offset=0, revision="revision-1"):
        return build_event_calendar(
            definitions=(
                event(
                    FED_DECISION,
                    HIGH,
                    scope=MARKET,
                    revision_identity=revision,
                ),
            ),
            generated_at=BASE + timedelta(minutes=offset),
            valid_through=BASE + timedelta(hours=10),
            previous_snapshot=previous,
        )

    def test_append_reload_and_exact_duplicate_are_byte_stable(self) -> None:
        snapshot = self.snapshot()
        self.store.append(snapshot)
        before = self.path.read_bytes()

        repeated = self.store.append(snapshot)

        self.assertEqual(snapshot, repeated)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual((snapshot,), self.store.load().snapshots)

    def test_snapshot_must_extend_current_chain(self) -> None:
        first = self.snapshot()
        self.store.append(first)
        unrelated = self.snapshot(offset=1, revision="revision-2")

        with self.assertRaisesRegex(MacroEventContextError, "sequence|extend"):
            self.store.append(unrelated)

    def test_atomic_replace_failure_preserves_prior_calendar(self) -> None:
        first = self.snapshot()
        self.store.append(first)
        before = self.path.read_bytes()
        second = self.snapshot(previous=first, offset=1, revision="revision-2")

        with mock.patch(
            "momentum_hunter.macro_event_context.os.replace",
            side_effect=OSError("synthetic replace failure"),
        ):
            with self.assertRaises(OSError):
                self.store.append(second)

        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual((first,), self.store.load().snapshots)

    def test_tampered_calendar_fails_closed(self) -> None:
        snapshot = self.snapshot()
        self.store.append(snapshot)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["snapshots"][0]["events"][0]["title"] = "tampered"
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(MacroEventContextError, "fingerprint"):
            self.store.load()


class EventBoundaryTests(unittest.TestCase):
    def test_policy_cannot_treat_unsafe_or_unmapped_evidence_as_normal(self) -> None:
        invalid = replace(
            policy(),
            unknown_or_stale_event_context=NORMAL,
        )
        calendar = build_event_calendar(
            definitions=(),
            generated_at=BASE,
            valid_through=BASE + timedelta(hours=10),
        )

        with self.assertRaisesRegex(MacroEventContextError, "fail closed"):
            evaluate_event_risk(
                calendar=calendar,
                policy=invalid,
                evaluated_at=BASE + timedelta(hours=1),
            )

    def test_module_has_no_network_provider_broker_or_trading_import(self) -> None:
        path = Path(__file__).parents[1] / "momentum_hunter" / "macro_event_context.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        forbidden = (
            "requests",
            "urllib",
            "httpx",
            "socket",
            "alpaca",
            "schwab",
            "scoring",
            "trade_planning",
            "intraday_trade_plan",
            "risk_governor",
            "broker",
            "execution",
            "engine_host",
            "shadow",
        )
        self.assertFalse(
            [name for name in imports if any(part in name for part in forbidden)]
        )


def policy() -> EventRiskPolicy:
    return EventRiskPolicy(
        policy_version="synthetic-event-risk-policy-v1",
        rules=(
            EventConsequenceRule(FED_DECISION, HIGH, BLOCK_NEW_ENTRY),
            EventConsequenceRule(FED_SPEAKER, MEDIUM, CAUTION),
            EventConsequenceRule(COMPANY_EARNINGS, HIGH, CAUTION),
        ),
        maximum_candidate_fan_out=3,
    )


def event(
    category: str,
    importance: str,
    *,
    scope: str,
    source_event_id: str = "source-event-1",
    revision_identity: str = "revision-1",
    evidence_state: str = CURRENT,
    symbols: tuple[str, ...] = (),
    sectors: tuple[str, ...] = (),
) -> EventDefinition:
    return EventDefinition(
        source_event_id=source_event_id,
        revision_identity=revision_identity,
        category=category,
        title=f"Synthetic {category}",
        importance=importance,
        evidence_state=evidence_state,
        scheduled_start=(BASE + timedelta(hours=1)).isoformat(),
        scheduled_end=(BASE + timedelta(hours=1, minutes=5)).isoformat(),
        risk_window_start=(BASE + timedelta(minutes=45)).isoformat(),
        risk_window_end=(BASE + timedelta(hours=1, minutes=30)).isoformat(),
        observation_window_start=(BASE + timedelta(minutes=30)).isoformat(),
        observation_window_end=(BASE + timedelta(hours=2)).isoformat(),
        scope=scope,
        source_identity="synthetic-approved-calendar",
        provider_timestamp=(BASE - timedelta(minutes=10)).isoformat(),
        receipt_timestamp=(BASE - timedelta(minutes=9)).isoformat(),
        affected_symbols=symbols,
        affected_sector_symbols=sectors,
        notes="Synthetic fixture only.",
    )


if __name__ == "__main__":
    unittest.main()
