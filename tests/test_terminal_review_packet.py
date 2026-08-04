from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from momentum_hunter.shadow_market_validity import SHADOW_SELECTOR_ARM_CONFIRMATION
from momentum_hunter.shadow_opening import (
    build_https_clock_skew_proof,
    build_shadow_handoff_receipt,
)
from momentum_hunter.shadow_selection import AutomaticShadowSelector
from momentum_hunter.shadow_trading import (
    OFFICIAL_SHADOW_SAMPLE_VERSION,
    SHADOW_SAMPLE_ACTIVATION_CONFIRMATION,
    ShadowExecutionPolicy,
    ShadowOutcome,
    ShadowQuote,
    ShadowStateStore,
    ShadowTradingService,
    ShadowTradingState,
    append_trade_event,
)
from momentum_hunter.terminal_review_packet import (
    TerminalReviewPacketError,
    TerminalReviewPacketRequest,
    build_terminal_review_packet,
    main,
    verify_packet_security,
)
from tests.shadow_proof_fixtures import write_synthetic_proof_artifacts
from tests.test_shadow_trading import report_payload as shadow_report_payload


DECISION_AT = datetime.fromisoformat("2026-07-30T08:45:00-05:00")


class _ClockedQuoteSource:
    def __init__(self, quote_timestamp: datetime) -> None:
        self.quote_timestamp = quote_timestamp

    def quotes_with_clock(self, symbols, *, decision_at):
        quotes = {}
        for symbol in symbols:
            price = 9.94 if symbol == "TEST" else 100.0
            quotes[symbol] = {
                "symbol": symbol,
                "timestamp": self.quote_timestamp.isoformat(),
                "bid": price,
                "ask": price + 0.01,
                "last": price,
                "session": "regular",
                "trading_state": "tradable",
                "source": "synthetic-terminal-review",
            }
        return SimpleNamespace(
            quotes=quotes,
            clock_skew_proof=build_https_clock_skew_proof(
                request_started_at=decision_at,
                response_received_at=decision_at,
                remote_date_header=format_datetime(decision_at),
                source_identity="synthetic-terminal-review-clock",
            ),
        )


class TerminalReviewPacketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_completed_winner_packet_is_hash_bound_and_classified(self) -> None:
        request = self._chain("winner")

        result = build_terminal_review_packet(request)
        packet = self._packet(result.json_path)

        self.assertEqual("COMPLETED_WINNER", result.event_kind)
        self.assertEqual(10, len(packet["sections"]))
        self.assertEqual(
            "STORED_FACT",
            packet["sections"]["G_PERFORMANCE"]["executableDollarPnl"]["classification"],
        )
        self.assertTrue(packet["sections"]["G_PERFORMANCE"]["executableDollarPnl"]["value"] > 0)
        self.assertEqual(6, len(packet["inputFiles"]))
        self.assertFalse(packet["boundaries"]["codexInvoked"])
        self.assertFalse(packet["boundaries"]["networkUsed"])
        self.assertIn("not a Codex interpretation", result.markdown_path.read_text(encoding="utf-8"))

    def test_completed_loser_and_flat_packets_preserve_terminal_classification(self) -> None:
        for kind, expected, comparison in (
            ("loser", "COMPLETED_LOSER", lambda value: value < 0),
            ("flat", "COMPLETED_FLAT", lambda value: value == 0),
        ):
            with self.subTest(kind=kind):
                request = self._chain(kind, folder=kind)
                result = build_terminal_review_packet(request)
                packet = self._packet(result.json_path)
                pnl = packet["sections"]["G_PERFORMANCE"]["executableDollarPnl"]["value"]
                self.assertEqual(expected, result.event_kind)
                self.assertTrue(comparison(pnl), pnl)

    def test_unfilled_cancelled_and_invalidated_packets_have_no_fabricated_performance(self) -> None:
        for kind, expected in (
            ("unfilled", "UNFILLED_ORDER"),
            ("cancelled", "CANCELLED_ORDER"),
            ("invalidated", "INVALIDATED_TRADE"),
        ):
            with self.subTest(kind=kind):
                result = build_terminal_review_packet(self._chain(kind, folder=kind))
                packet = self._packet(result.json_path)
                performance = packet["sections"]["G_PERFORMANCE"]
                self.assertEqual(expected, result.event_kind)
                self.assertEqual("MISSING", performance["executableDollarPnl"]["classification"])
                self.assertEqual("MISSING", performance["executableR"]["classification"])

    def test_no_eligible_risk_block_and_stale_quote_are_terminal_no_trade_packets(self) -> None:
        for kind, reason_fragment in (
            ("no_eligible", "No candidate passed"),
            ("risk_blocked", "stop"),
            ("stale_quote", "stale"),
        ):
            with self.subTest(kind=kind):
                result = build_terminal_review_packet(self._chain(kind, folder=kind))
                packet = self._packet(result.json_path)
                selection = packet["sections"]["E_SELECTION_RESULT"]
                self.assertEqual("NO_TRADE", result.event_kind)
                self.assertEqual("NO_ELIGIBLE_CANDIDATE", selection["status"]["value"])
                serialized = json.dumps(packet).lower()
                self.assertIn(reason_fragment.lower(), serialized)
                self.assertTrue(selection["proofNoOrderOrPosition"]["value"])

    def test_counterfactuals_are_never_presented_as_official_trades(self) -> None:
        request = self._chain("winner")
        cycle_payload = self._read(request.decision_cycles_path)
        cycle = cycle_payload["cycles"][0]
        cycle["deterministic_random_eligible"] = {"symbol": "ALT", "canonical_rank": 2}
        cycle["counterfactual_marks"] = [
            {
                "symbol": "ALT",
                "available": True,
                "measurement": "mark_to_latest",
                "return_percent": 1.25,
            }
        ]
        self._write(request.decision_cycles_path, cycle_payload)

        result = build_terminal_review_packet(request)
        section = self._packet(result.json_path)["sections"]["H_COUNTERFACTUALS_AND_BENCHMARKS"]

        self.assertEqual(
            "COUNTERFACTUAL — NOT AN OFFICIAL TRADE",
            section["deterministicRandomCandidate"]["value"]["status"],
        )
        self.assertEqual(
            "COUNTERFACTUAL — NOT AN OFFICIAL TRADE",
            section["observedMarks"]["value"][0]["status"],
        )

    def test_missing_optional_evidence_is_explicit(self) -> None:
        result = build_terminal_review_packet(self._chain("cancelled"))
        packet = self._packet(result.json_path)

        self.assertEqual(
            "MISSING",
            packet["sections"]["G_PERFORMANCE"]["idealResult"]["classification"],
        )
        self.assertEqual(
            "MISSING",
            packet["sections"]["I_DATA_AND_SYSTEM_QUALITY"]["restartOrDowntimeEvidence"]["classification"],
        )

    def test_missing_required_identity_fails_closed(self) -> None:
        request = self._chain("winner")
        payload = self._read(request.decision_cycles_path)
        payload["cycles"][0]["cycle_id"] = ""
        self._write(request.decision_cycles_path, payload)

        with self.assertRaisesRegex(TerminalReviewPacketError, "identities are missing"):
            build_terminal_review_packet(request)
        self.assertEqual([], list(request.output_dir.glob("terminal-review-*")))

    def test_sample_fill_model_policy_arm_and_opportunity_mismatches_fail_closed(self) -> None:
        mutations = {
            "sample": lambda request: self._mutate_activation(
                request, "sample_version", "official-shadow-v999"
            ),
            "fill": lambda request: self._mutate_activation(
                request, "fill_model_version", "different-fill-model"
            ),
            "policy": lambda request: self._mutate_cycle(
                request, "selection_policy_fingerprint", "0" * 64
            ),
            "arm": lambda request: self._mutate_cycle(request, "selector_arm_id", "other-arm"),
            "opportunity": lambda request: self._mutate_cycle(
                request, "opportunity_id", "other-opportunity"
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                request = self._chain("winner", folder=name)
                mutate(request)
                with self.assertRaises(TerminalReviewPacketError):
                    build_terminal_review_packet(request)

    def test_report_hash_tampering_fails_closed(self) -> None:
        request = self._chain("winner")
        request.report_path.write_bytes(request.report_path.read_bytes() + b"\n")

        with self.assertRaisesRegex(TerminalReviewPacketError, "Source report hash"):
            build_terminal_review_packet(request)

    def test_exact_duplicate_is_idempotent_and_byte_identical(self) -> None:
        request = self._chain("winner")
        first = build_terminal_review_packet(request)
        before = (first.json_path.read_bytes(), first.markdown_path.read_bytes())

        second = build_terminal_review_packet(request)

        self.assertTrue(second.duplicate)
        self.assertEqual(first.packet_id, second.packet_id)
        self.assertEqual(before, (second.json_path.read_bytes(), second.markdown_path.read_bytes()))

    def test_conflicting_existing_output_fails_without_overwrite(self) -> None:
        request = self._chain("winner")
        request.output_dir.mkdir(parents=True)
        target = request.output_dir / f"terminal-review-{request.event_id}.json"
        target.write_text("existing-user-content", encoding="utf-8")

        with self.assertRaisesRegex(TerminalReviewPacketError, "Conflicting packet output"):
            build_terminal_review_packet(request)
        self.assertEqual("existing-user-content", target.read_text(encoding="utf-8"))
        self.assertFalse(target.with_suffix(".md").exists())

    def test_second_output_failure_rolls_back_new_json(self) -> None:
        request = self._chain("winner")
        original_open = Path.open

        def failing_open(path, mode="r", *args, **kwargs):
            if Path(path).suffix == ".md" and mode == "xb":
                raise OSError("synthetic write failure")
            return original_open(path, mode, *args, **kwargs)

        with patch("pathlib.Path.open", new=failing_open):
            with self.assertRaisesRegex(TerminalReviewPacketError, "rolled back"):
                build_terminal_review_packet(request)

        self.assertEqual([], list(request.output_dir.glob("terminal-review-*")))

    def test_source_change_after_output_creation_removes_only_new_outputs(self) -> None:
        request = self._chain("winner")
        checks = 0

        def changing_check(_hashes):
            nonlocal checks
            checks += 1
            if checks == 2:
                raise TerminalReviewPacketError(
                    "Source evidence changed during packet construction: handoff.json"
                )

        with patch(
            "momentum_hunter.terminal_review_packet._assert_sources_unchanged",
            side_effect=changing_check,
        ):
            with self.assertRaisesRegex(TerminalReviewPacketError, "Source evidence changed"):
                build_terminal_review_packet(request)

        self.assertEqual([], list(request.output_dir.glob("terminal-review-*")))

    def test_security_scan_rejects_secret_keys_values_and_known_live_values(self) -> None:
        cases = (
            (b'{"access_token":"abc"}', ()),
            (b'{"value":"Bearer abcdefghijklmnop"}', ()),
            (b'{"value":"private-live-value"}', ("private-live-value",)),
        )
        for payload, known in cases:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(TerminalReviewPacketError, "security scan"):
                    verify_packet_security(payload, known_sensitive_values=known)

    def test_builder_does_not_mutate_any_source_file(self) -> None:
        request = self._chain("winner")
        sources = self._source_paths(request)
        before = {path: path.read_bytes() for path in sources}

        build_terminal_review_packet(request)

        self.assertEqual(before, {path: path.read_bytes() for path in sources})

    def test_module_has_no_network_provider_broker_service_or_codex_capability(self) -> None:
        source = Path("momentum_hunter/terminal_review_packet.py").read_text(encoding="utf-8")
        forbidden_imports = (
            "requests",
            "httpx",
            "urllib",
            "socket",
            "schwab",
            "openai",
            "engine_host",
            "automation_service",
        )
        for name in forbidden_imports:
            self.assertNotRegex(source, rf"(?m)^\s*(?:from|import)\s+{name}\b")
        for method in ("submit_order(", "cancel_order(", "replace_order(", "process_quote("):
            self.assertNotIn(method, source)

    def test_cli_returns_structured_success_and_redacted_failure(self) -> None:
        request = self._chain("winner")
        argv = self._argv(request)
        with patch("builtins.print") as output:
            self.assertEqual(0, main(argv))
        success = json.loads(output.call_args.args[0])
        self.assertEqual("CREATED", success["status"])
        self.assertFalse(success["networkUsed"])

        request.handoff_path.write_text('{"access_token":"Bearer secret-value-12345"}', encoding="utf-8")
        with patch("builtins.print") as output:
            self.assertEqual(2, main(argv))
        failure = json.loads(output.call_args.args[0])
        self.assertEqual("FAILED_CLOSED", failure["status"])
        self.assertNotIn("secret-value", json.dumps(failure))

    def _chain(self, kind: str, *, folder: str = "case") -> TerminalReviewPacketRequest:
        root = self.root / folder
        root.mkdir(parents=True, exist_ok=True)
        report_path = root / "trade-plan-briefing-synthetic.json"
        report = report_payload()
        if kind in {"no_eligible", "risk_blocked"}:
            report["candidates"][0]["trade_plan"]["bullish_stop"] = None
            report["top_5_for_capital"][0]["trade_plan"]["bullish_stop"] = None
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

        store = ShadowStateStore(root / "shadow-state.json")
        store.save(ShadowTradingState())
        service = ShadowTradingService(
            store=store,
            policy=ShadowExecutionPolicy(
                slippage_bps=10,
                minimum_fill_delay_seconds=1,
                buying_power=10_000,
                max_open_positions=3,
            ),
            sample_version=OFFICIAL_SHADOW_SAMPLE_VERSION,
        )
        with patch(
            "momentum_hunter.shadow_trading.now_central",
            return_value=DECISION_AT - timedelta(minutes=3),
        ):
            service.activate_official_sample(
                confirmation=SHADOW_SAMPLE_ACTIVATION_CONFIRMATION,
                sample_version=OFFICIAL_SHADOW_SAMPLE_VERSION,
            )
        service.arm_automatic_selector(
            confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
            prerequisite_proof_paths=write_synthetic_proof_artifacts(
                root,
                kind,
                sample_version=service.sample_definition.sample_version,
                activation_path=service.activation_store.path,
                verified_at=DECISION_AT - timedelta(minutes=2, seconds=30),
            ),
            armed_at=DECISION_AT - timedelta(minutes=2),
        )
        quote_at = (
            DECISION_AT - timedelta(minutes=3)
            if kind == "stale_quote"
            else DECISION_AT - timedelta(seconds=5)
        )
        selector = AutomaticShadowSelector(
            service,
            quote_source=_ClockedQuoteSource(quote_at),
        )
        selection = selector.select(report_path, decision_at=DECISION_AT)

        if selection.shadow_trade_id:
            self._terminalize_trade(service, kind)
            event_id = selection.shadow_trade_id
        else:
            event_id = selection.decision_cycle_id

        report_sha256 = hashlib.sha256(report_path.read_bytes()).hexdigest()
        handoff = build_shadow_handoff_receipt(
            report_path=report_path,
            report_sha256=report_sha256,
            capture_id=f"synthetic-capture-{kind}",
            cycle=SimpleNamespace(
                accepted=True,
                code="COLLECTION_COMPLETED",
                command_id=f"engine-cycle-{kind}",
                payload={"shadowAutomaticSelection": selection.to_dict()},
                snapshot={
                    "identity": {
                        "hostInstanceId": "synthetic-host",
                        "processId": 1234,
                        "protocolVersion": "synthetic-v1",
                        "transport": "offline-test",
                    },
                    "collection": {
                        "lastCompletedCycleAtUtc": (
                            DECISION_AT + timedelta(minutes=31)
                        ).astimezone().isoformat()
                    },
                },
            ),
            recorded_at=DECISION_AT + timedelta(minutes=32),
        )
        handoff_path = root / "handoff.json"
        self._write(handoff_path, handoff)
        return TerminalReviewPacketRequest(
            event_id=event_id,
            output_dir=root / "output",
            state_path=store.path,
            decision_cycles_path=service.decision_cycle_store.path,
            handoff_path=handoff_path,
            report_path=report_path,
            activation_path=service.activation_store.path,
            selection_policy_path=service.selection_policy_store.path,
        )

    def _terminalize_trade(self, service: ShadowTradingService, kind: str) -> None:
        if kind == "unfilled":
            state = service.store.load()
            trade = state.trades[0]
            rejected_order = replace(
                trade.order,
                status="rejected",
                last_update_at=(DECISION_AT + timedelta(minutes=1)).isoformat(),
                reason="Synthetic terminal unfilled rejection.",
            )
            rejected = append_trade_event(
                replace(trade, status="entry_rejected", order=rejected_order),
                timestamp=rejected_order.last_update_at,
                event_type="fake_order_rejected",
                requested_action="fake_entry_rejected",
                result="rejected",
                reason=rejected_order.reason,
                payload={"order_id": rejected_order.order_id},
            )
            service.store.save(replace(state, trades=(rejected,)))
            return
        if kind == "cancelled":
            service.process_quote(
                quote(DECISION_AT.replace(hour=15, minute=0), bid=10.04, ask=10.05),
                received_at=DECISION_AT.replace(hour=15, minute=0),
            )
            return

        service.process_quote(
            quote(DECISION_AT + timedelta(seconds=5), bid=9.94, ask=9.95),
            received_at=DECISION_AT + timedelta(seconds=5),
        )
        if kind == "invalidated":
            service.process_quote(
                quote(
                    DECISION_AT + timedelta(minutes=1),
                    bid=10.50,
                    ask=10.51,
                    open=9.0,
                    high=10.70,
                    low=8.90,
                ),
                received_at=DECISION_AT + timedelta(minutes=1),
            )
        elif kind == "loser":
            service.process_quote(
                quote(
                    DECISION_AT + timedelta(minutes=30),
                    bid=9.45,
                    ask=9.46,
                    high=9.50,
                    low=9.40,
                ),
                received_at=DECISION_AT + timedelta(minutes=30),
            )
        elif kind == "flat":
            service.process_quote(
                quote(
                    DECISION_AT.replace(hour=15, minute=0),
                    bid=9.97,
                    ask=9.98,
                    high=9.98,
                    low=9.95,
                ),
                received_at=DECISION_AT.replace(hour=15, minute=0),
            )
        else:
            service.process_quote(
                quote(
                    DECISION_AT + timedelta(minutes=30),
                    bid=10.55,
                    ask=10.56,
                    high=10.57,
                    low=10.50,
                ),
                received_at=DECISION_AT + timedelta(minutes=30),
            )

    @staticmethod
    def _read(path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write(path: Path, payload) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _mutate_activation(self, request, key, value) -> None:
        payload = self._read(request.activation_path)
        payload["sample_metadata"][key] = value
        self._write(request.activation_path, payload)

    def _mutate_cycle(self, request, key, value) -> None:
        payload = self._read(request.decision_cycles_path)
        payload["cycles"][0][key] = value
        self._write(request.decision_cycles_path, payload)

    @staticmethod
    def _packet(path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _source_paths(request):
        return (
            request.state_path,
            request.decision_cycles_path,
            request.handoff_path,
            request.report_path,
            request.activation_path,
            request.selection_policy_path,
        )

    @staticmethod
    def _argv(request):
        return [
            "--event-id",
            request.event_id,
            "--output-dir",
            str(request.output_dir),
            "--state-path",
            str(request.state_path),
            "--decision-cycles-path",
            str(request.decision_cycles_path),
            "--handoff-path",
            str(request.handoff_path),
            "--report-path",
            str(request.report_path),
            "--activation-path",
            str(request.activation_path),
            "--selection-policy-path",
            str(request.selection_policy_path),
        ]


def report_payload() -> dict:
    payload = shadow_report_payload()
    payload["metadata"]["generated_at"] = "2026-07-30T08:44:00-05:00"
    payload["metadata"]["source_capture_time"] = "2026-07-30T08:43:00-05:00"
    return payload


def quote(
    timestamp: datetime,
    *,
    bid: float,
    ask: float,
    open: float | None = None,
    high: float | None = None,
    low: float | None = None,
) -> ShadowQuote:
    return ShadowQuote(
        symbol="TEST",
        timestamp=timestamp.isoformat(),
        bid=bid,
        ask=ask,
        last=bid,
        open=open,
        high=high,
        low=low,
        session="regular",
        trading_state="tradable",
        source="synthetic-terminal-review",
    )


if __name__ == "__main__":
    unittest.main()
