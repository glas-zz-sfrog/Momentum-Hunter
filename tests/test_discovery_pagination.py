from __future__ import annotations

import ast
import json
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from momentum_hunter.broad_discovery import (
    BOUNDED_PAGE_PREFIX,
    COMPLETE_FILTERED_RESULT_SET,
    COVERAGE_SCOPE_FILTERED_PROVIDER_QUERY,
    PAGINATED_DISCOVERY_SNAPSHOT_CONTRACT_VERSION,
    PARTIAL_PROVIDER_FAILURE,
    REQUEST_BUDGET_EXHAUSTED,
    ROW_RELATIONSHIP_DUPLICATE_SOURCE,
    SNAPSHOT_STATUS_COMPLETE,
    SNAPSHOT_STATUS_PARTIAL_PROVIDER_FAILURE,
    SNAPSHOT_STATUS_REQUEST_BUDGET_EXHAUSTED,
    TRUNCATION_MAX_ELAPSED_TIME,
    TRUNCATION_MAX_PAGES,
    DiscoveryPageInput,
    DiscoveryPaginationError,
    DiscoveryPaginationPolicy,
    DiscoveryQueryIdentity,
    DiscoverySnapshot,
    DiscoverySourceRow,
    build_discovery_snapshot,
    build_paginated_discovery_snapshot,
    pagination_page_bound,
)
from momentum_hunter.continuous_composition import (
    ContinuousCompositionPolicy,
    build_readiness_request,
)
from momentum_hunter.hot_universe import (
    HotUniversePolicy,
    apply_discovery_snapshot,
)
from momentum_hunter.models import Candidate, INSTITUTIONAL_MOMENTUM
from momentum_hunter.providers import FINVIZ_CANONICAL_SCREENER_COLUMNS, FinvizProvider
from momentum_hunter.time_utils import CENTRAL_TZ


BASE = datetime(2026, 8, 17, 10, 0, tzinfo=CENTRAL_TZ)
SOURCE_CONTRACT = "a" * 64
SEMANTIC = "b" * 64


def policy(**changes: object) -> DiscoveryPaginationPolicy:
    values = {
        "max_pages": 5,
        "max_rows": 100,
        "maximum_elapsed_time_seconds": 30.0,
        "per_page_timeout_seconds": 5.0,
    }
    values.update(changes)
    return DiscoveryPaginationPolicy(**values)


def query(page_policy: DiscoveryPaginationPolicy) -> DiscoveryQueryIdentity:
    return DiscoveryQueryIdentity.from_criteria(
        INSTITUTIONAL_MOMENTUM,
        source_query="https://finviz.example/screener.ashx?v=151&f=canonical&o=-volume",
        sort_order="-volume",
        page_bound=pagination_page_bound(page_policy),
    )


def source_row(
    ordinal: int,
    symbol: str,
    *,
    qualified: bool = True,
    price: float | None = None,
) -> DiscoverySourceRow:
    actual_price = price if price is not None else 20.0 + ordinal
    return DiscoverySourceRow.from_mapping(
        source_row_ordinal=ordinal,
        source_row_identity=str(ordinal),
        source_values={
            "No.": str(ordinal),
            "Ticker": symbol,
            "Price": f"{actual_price:.2f}",
            "Change %": "4.00%" if qualified else "1.00%",
        },
        candidate=Candidate(
            ticker=symbol,
            company=f"{symbol} Incorporated",
            sector="Technology",
            industry="Software",
            market_cap=10_000_000_000,
            price=actual_price,
            percent_change=4.0 if qualified else 1.0,
            volume=4_000_000 + ordinal,
            relative_volume=2.0,
            float_shares=450_000_000,
            atr=2.5,
        ),
    )


def page(
    page_number: int,
    rows: list[DiscoverySourceRow],
    *,
    total: int | None,
    page_size: int = 20,
    terminal: bool = False,
    failure: str | None = None,
    request_offset_seconds: int | None = None,
) -> DiscoveryPageInput:
    offset_seconds = (
        request_offset_seconds if request_offset_seconds is not None else page_number - 1
    )
    requested = BASE + timedelta(seconds=offset_seconds)
    received = requested + timedelta(milliseconds=25)
    return DiscoveryPageInput(
        page_number=page_number,
        page_offset=1 + ((page_number - 1) * page_size),
        requested_at=requested,
        received_at=received,
        request_duration_milliseconds=25,
        source_rows=tuple(rows) if failure is None else (),
        raw_row_count=len(rows) if failure is None else 0,
        source_contract_fingerprint=SOURCE_CONTRACT if failure is None else "",
        semantic_plausibility_fingerprint=SEMANTIC if failure is None else "",
        provider_total_results=total if failure is None else None,
        provider_page_size=page_size if failure is None else None,
        terminal_page=terminal,
        failure_reason=failure,
    )


def rows(start: int, count: int, *, qualified: bool = True) -> list[DiscoverySourceRow]:
    return [
        source_row(
            ordinal,
            f"S{ordinal:04d}",
            qualified=qualified,
        )
        for ordinal in range(start, start + count)
    ]


def snapshot(
    pages: list[DiscoveryPageInput],
    *,
    page_policy: DiscoveryPaginationPolicy | None = None,
    termination_reason: str | None = None,
) -> DiscoverySnapshot:
    resolved_policy = page_policy or policy()
    return build_paginated_discovery_snapshot(
        source="finviz",
        source_version="synthetic-finviz-pagination-v1",
        evaluated_at=BASE + timedelta(minutes=1),
        query_identity=query(resolved_policy),
        pagination_policy=resolved_policy,
        page_inputs=pages,
        termination_reason=termination_reason,
    )


def finviz_row(ordinal: int, symbol: str, *, qualified: bool = True) -> str:
    values = {
        "No.": str(ordinal),
        "Ticker": f'<td data-boxover-ticker="{symbol}">{symbol}</td>',
        "Company": f"{symbol} Incorporated",
        "Sector": "Technology",
        "Industry": "Software",
        "Market Cap": "10B",
        "Float": "450M",
        "ATR": "2.5",
        "Rel Volume": "2.0",
        "Volume": f"{4_000_000 + ordinal:,}",
        "Price": f"{25.0 + ordinal:.2f}",
        "Change %": "4.00%" if qualified else "1.00%",
    }
    cells = []
    for header in FINVIZ_CANONICAL_SCREENER_COLUMNS:
        value = values[header]
        cells.append(value if header == "Ticker" else f"<td>{value}</td>")
    return "<tr>" + "".join(cells) + "</tr>"


def finviz_html(start: int, count: int, *, total: int, malformed: bool = False) -> str:
    if malformed:
        return '<table class="screener_table"><tr><td>No.</td><td>Ticker</td></tr></table>'
    headers = "".join(
        f"<td>{header}</td>" for header in FINVIZ_CANONICAL_SCREENER_COLUMNS
    )
    rows_html = "".join(
        finviz_row(ordinal, f"P{ordinal:04d}")
        for ordinal in range(start, start + count)
    )
    return (
        f"<div>{total} Total</div>"
        f'<table class="screener_table"><tr>{headers}</tr>{rows_html}</table>'
    )


def provider_for_pages(pages: dict[int, str], calls: list[tuple[str, float]]) -> FinvizProvider:
    provider = FinvizProvider(sleeper=lambda _seconds: None, backoff_seconds=())

    class Response:
        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

    def get(url: str, **kwargs: object) -> Response:
        timeout = float(kwargs["timeout"])
        calls.append((url, timeout))
        offset = 1
        if "&r=" in url:
            offset = int(url.rsplit("&r=", 1)[1])
        return Response(pages[offset])

    provider.session.get = get
    return provider


class DiscoveryPaginationTests(unittest.TestCase):
    def test_legacy_single_page_contract_remains_v1(self) -> None:
        source = [source_row(1, "LEGACY")]
        legacy = build_discovery_snapshot(
            source="finviz",
            source_version="synthetic-v1",
            requested_at=BASE,
            received_at=BASE,
            evaluated_at=BASE,
            query_identity=DiscoveryQueryIdentity.from_criteria(
                INSTITUTIONAL_MOMENTUM,
                source_query="synthetic://legacy",
                sort_order="-volume",
            ),
            source_contract_fingerprint=SOURCE_CONTRACT,
            semantic_plausibility_fingerprint=SEMANTIC,
            source_rows=source,
        )
        payload = legacy.to_dict()
        self.assertEqual(1, legacy.contract_version)
        self.assertNotIn("pageReceipts", payload)
        self.assertNotIn("coverageState", payload)

    def test_two_complete_pages_preserve_every_row_and_coordinates(self) -> None:
        result = snapshot(
            [
                page(1, rows(1, 20), total=40),
                page(2, rows(21, 20), total=40, terminal=True),
            ],
            page_policy=policy(max_pages=2, max_rows=40),
        )
        self.assertEqual(PAGINATED_DISCOVERY_SNAPSHOT_CONTRACT_VERSION, result.contract_version)
        self.assertEqual(COMPLETE_FILTERED_RESULT_SET, result.coverage_state)
        self.assertEqual(SNAPSHOT_STATUS_COMPLETE, result.status)
        self.assertEqual(40, result.represented_row_count)
        self.assertEqual(40, result.total_results_reported_by_provider)
        self.assertEqual(2, result.pages_available)
        self.assertEqual(0, result.unseen_row_count)
        self.assertEqual(1, result.rows[0].source_page_number)
        self.assertEqual(2, result.rows[-1].source_page_number)
        self.assertEqual(40, result.rows[-1].global_observation_ordinal)
        restored = DiscoverySnapshot.from_dict(json.loads(result.canonical_json()))
        self.assertEqual(result.canonical_json(), restored.canonical_json())

    def test_later_page_candidate_flows_to_universe_and_compose_readiness(self) -> None:
        first = rows(1, 20, qualified=False)
        second = rows(21, 20, qualified=False)
        second[-1] = source_row(40, "LATE", qualified=True)
        discovered = snapshot(
            [
                page(1, first, total=40),
                page(2, second, total=40, terminal=True),
            ],
            page_policy=policy(max_pages=2, max_rows=40),
        )
        universe = apply_discovery_snapshot(
            None,
            policy=HotUniversePolicy(),
            snapshot=discovered,
        )
        member = next(item for item in universe.state.members if item.symbol == "LATE")
        request = build_readiness_request(
            member,
            requested_at=BASE + timedelta(minutes=5),
            policy=ContinuousCompositionPolicy(),
        )
        self.assertEqual("LATE", request.symbol)
        self.assertEqual(member.member_id, request.universe_member_id)

    def test_five_page_complete_result_has_no_unseen_rows(self) -> None:
        result = snapshot(
            [
                page(number, rows((number - 1) * 20 + 1, 20), total=100, terminal=number == 5)
                for number in range(1, 6)
            ],
            page_policy=policy(max_pages=5, max_rows=100),
        )
        self.assertEqual(COMPLETE_FILTERED_RESULT_SET, result.coverage_state)
        self.assertEqual(100, result.represented_row_count)
        self.assertEqual(5, result.pages_received)

    def test_bounded_prefix_remains_explicit(self) -> None:
        result = snapshot(
            [
                page(number, rows((number - 1) * 20 + 1, 20), total=400)
                for number in range(1, 6)
            ],
            page_policy=policy(max_pages=5, max_rows=100),
        )
        self.assertEqual(BOUNDED_PAGE_PREFIX, result.coverage_state)
        self.assertEqual(TRUNCATION_MAX_PAGES, result.truncation_reason)
        self.assertEqual(300, result.unseen_row_count)
        self.assertNotEqual(COMPLETE_FILTERED_RESULT_SET, result.coverage_state)

    def test_page_failure_is_not_rewritten_as_a_shorter_prefix(self) -> None:
        result = snapshot(
            [
                page(1, rows(1, 20), total=60),
                page(2, rows(21, 20), total=60),
                page(3, [], total=None, failure="contract_drift:ProviderContractError"),
            ]
        )
        self.assertEqual(PARTIAL_PROVIDER_FAILURE, result.coverage_state)
        self.assertEqual(SNAPSHOT_STATUS_PARTIAL_PROVIDER_FAILURE, result.status)
        self.assertEqual(40, result.represented_row_count)
        self.assertEqual("contract_drift:ProviderContractError", result.failure_reason)

    def test_explicit_request_budget_is_neither_complete_nor_prefix(self) -> None:
        result = snapshot(
            [
                page(1, rows(1, 20), total=100),
                page(2, rows(21, 20), total=100),
            ],
            termination_reason=TRUNCATION_MAX_ELAPSED_TIME,
        )
        self.assertEqual(REQUEST_BUDGET_EXHAUSTED, result.coverage_state)
        self.assertEqual(SNAPSHOT_STATUS_REQUEST_BUDGET_EXHAUSTED, result.status)
        self.assertEqual(TRUNCATION_MAX_ELAPSED_TIME, result.truncation_reason)

    def test_identical_cross_page_duplicate_is_preserved_not_deduplicated(self) -> None:
        duplicate_a = source_row(1, "DUPL", qualified=True, price=25.0)
        duplicate_b = source_row(1, "DUPL", qualified=True, price=25.0)
        result = snapshot(
            [
                page(1, [duplicate_a], total=2, page_size=1),
                page(2, [duplicate_b], total=2, page_size=1, terminal=True),
            ],
            page_policy=policy(max_pages=2, max_rows=2),
        )
        self.assertEqual(2, result.represented_row_count)
        self.assertEqual(
            [ROW_RELATIONSHIP_DUPLICATE_SOURCE, ROW_RELATIONSHIP_DUPLICATE_SOURCE],
            [row.source_relationship for row in result.rows],
        )

    def test_conflicting_duplicate_symbol_fails_closed(self) -> None:
        with self.assertRaisesRegex(DiscoveryPaginationError, "Conflicting duplicate"):
            snapshot(
                [
                    page(1, [source_row(1, "DUPL", price=25.0)], total=2, page_size=1),
                    page(
                        2,
                        [source_row(1, "DUPL", price=26.0)],
                        total=2,
                        page_size=1,
                        terminal=True,
                    ),
                ],
                page_policy=policy(max_pages=2, max_rows=2),
            )

    def test_invalid_page_order_query_and_metadata_fail_closed(self) -> None:
        with self.assertRaisesRegex(DiscoveryPaginationError, "consecutive"):
            snapshot([page(2, rows(1, 20), total=20, terminal=True)])
        invalid_policy = policy(max_pages=2, max_rows=40)
        with self.assertRaisesRegex(DiscoveryPaginationError, "bind"):
            build_paginated_discovery_snapshot(
                source="finviz",
                source_version="synthetic",
                evaluated_at=BASE,
                query_identity=DiscoveryQueryIdentity.from_criteria(
                    INSTITUTIONAL_MOMENTUM,
                    source_query="synthetic://wrong",
                    sort_order="-volume",
                ),
                pagination_policy=invalid_policy,
                page_inputs=[page(1, rows(1, 20), total=20, terminal=True)],
            )
        with self.assertRaises(DiscoveryPaginationError):
            DiscoveryPaginationPolicy(
                max_pages=0,
                max_rows=20,
                maximum_elapsed_time_seconds=1,
                per_page_timeout_seconds=1,
            )
        with self.assertRaises(DiscoveryPaginationError):
            DiscoveryPaginationPolicy(
                max_pages=1,
                max_rows=0,
                maximum_elapsed_time_seconds=1,
                per_page_timeout_seconds=1,
            )

    def test_contradictory_totals_and_extra_pages_fail_closed(self) -> None:
        with self.assertRaisesRegex(DiscoveryPaginationError, "total result metadata"):
            snapshot(
                [
                    page(1, rows(1, 20), total=40),
                    page(2, rows(21, 20), total=60, terminal=True),
                ],
                page_policy=policy(max_pages=2, max_rows=40),
            )
        with self.assertRaisesRegex(DiscoveryPaginationError, "fewer pages"):
            snapshot(
                [
                    page(1, rows(1, 20), total=20),
                    page(2, rows(21, 20), total=20, terminal=True),
                ],
                page_policy=policy(max_pages=2, max_rows=40),
            )

    def test_unknown_total_uses_unknown_unseen_count_only_when_terminal_is_explicit(self) -> None:
        result = snapshot(
            [page(1, rows(1, 3), total=None, page_size=20, terminal=True)],
            page_policy=policy(max_pages=1, max_rows=20),
        )
        self.assertEqual(COMPLETE_FILTERED_RESULT_SET, result.coverage_state)
        self.assertEqual("UNKNOWN", result.unseen_row_count)
        self.assertIsNone(result.total_results_reported_by_provider)

    def test_partial_snapshot_cannot_mutate_hot_universe(self) -> None:
        partial = snapshot(
            [
                page(1, rows(1, 20), total=40),
                page(2, [], total=None, failure="timeout:ProviderUnavailableError"),
            ]
        )
        with self.assertRaisesRegex(ValueError, "Only completed discovery snapshots"):
            apply_discovery_snapshot(
                None,
                policy=HotUniversePolicy(),
                snapshot=partial,
            )

    def test_replay_is_deterministic_and_query_or_policy_changes_identity(self) -> None:
        pages = [
            page(1, rows(1, 20), total=40),
            page(2, rows(21, 20), total=40, terminal=True),
        ]
        first = snapshot(pages, page_policy=policy(max_pages=2, max_rows=40))
        second = snapshot(pages, page_policy=policy(max_pages=2, max_rows=40))
        changed = snapshot(pages, page_policy=policy(max_pages=3, max_rows=60))
        self.assertEqual(first.canonical_json(), second.canonical_json())
        self.assertNotEqual(first.fingerprint, changed.fingerprint)
        self.assertNotEqual(first.query_fingerprint, changed.query_fingerprint)

    def test_scale_fixtures_remain_bounded(self) -> None:
        measured: dict[int, tuple[float, float, float, int]] = {}
        for page_count in (1, 2, 5, 10, 25):
            row_count = page_count * 20
            scale_policy = policy(max_pages=page_count, max_rows=row_count)
            inputs = [
                page(
                    number,
                    rows((number - 1) * 20 + 1, 20),
                    total=row_count,
                    terminal=number == page_count,
                )
                for number in range(1, page_count + 1)
            ]
            started = time.perf_counter()
            result = snapshot(inputs, page_policy=scale_policy)
            construction = time.perf_counter() - started
            started = time.perf_counter()
            wire = result.canonical_json()
            serialization = time.perf_counter() - started
            started = time.perf_counter()
            restored = DiscoverySnapshot.from_dict(json.loads(wire))
            validation = time.perf_counter() - started
            self.assertEqual(result.fingerprint, restored.fingerprint)
            self.assertLess(construction, 5.0)
            self.assertLess(serialization, 5.0)
            self.assertLess(validation, 5.0)
            measured[row_count] = (construction, serialization, validation, len(wire))
        self.assertEqual({20, 40, 100, 200, 500}, set(measured))
        self.assertGreater(measured[500][3], measured[20][3])

    def test_pure_aggregator_has_no_runtime_broker_or_network_imports(self) -> None:
        source_path = Path("momentum_hunter/broad_discovery.py")
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        forbidden = {
            "requests",
            "urllib",
            "sqlite3",
            "subprocess",
            "schedule",
            "momentum_hunter.alpaca_paper",
            "momentum_hunter.schwab_market_data",
            "momentum_hunter.trade_planning",
            "momentum_hunter.risk_governor",
        }
        self.assertFalse(imported.intersection(forbidden))

    def test_opt_in_provider_requests_bounded_offsets_and_preserves_total(self) -> None:
        calls: list[tuple[str, float]] = []
        provider = provider_for_pages(
            {
                1: finviz_html(1, 20, total=40),
                21: finviz_html(21, 20, total=40),
            },
            calls,
        )
        result = provider.discover_paginated(
            INSTITUTIONAL_MOMENTUM,
            pagination_policy=policy(
                max_pages=2,
                max_rows=40,
                per_page_timeout_seconds=3.5,
            ),
            requested_at=BASE,
            evaluated_at=BASE + timedelta(minutes=1),
        )
        self.assertEqual(COMPLETE_FILTERED_RESULT_SET, result.coverage_state)
        self.assertEqual(40, result.total_results_reported_by_provider)
        self.assertEqual(2, len(calls))
        self.assertNotIn("&r=", calls[0][0])
        self.assertTrue(calls[1][0].endswith("&r=21"))
        self.assertEqual([3.5, 3.5], [item[1] for item in calls])

    def test_evidence_timestamp_does_not_consume_live_request_budget(self) -> None:
        calls: list[tuple[str, float]] = []
        provider = provider_for_pages(
            {
                1: finviz_html(1, 20, total=40),
                21: finviz_html(21, 20, total=40),
            },
            calls,
        )
        result = provider.discover_paginated(
            INSTITUTIONAL_MOMENTUM,
            pagination_policy=policy(max_pages=2, max_rows=40),
            requested_at=BASE - timedelta(days=30),
            evaluated_at=BASE,
        )
        self.assertEqual(COMPLETE_FILTERED_RESULT_SET, result.coverage_state)
        self.assertEqual(2, len(calls))

    def test_opt_in_provider_preserves_second_page_contract_failure(self) -> None:
        calls: list[tuple[str, float]] = []
        provider = provider_for_pages(
            {
                1: finviz_html(1, 20, total=40),
                21: finviz_html(21, 0, total=40, malformed=True),
            },
            calls,
        )
        result = provider.discover_paginated(
            INSTITUTIONAL_MOMENTUM,
            pagination_policy=policy(max_pages=2, max_rows=40),
            requested_at=BASE,
            evaluated_at=BASE + timedelta(minutes=1),
        )
        self.assertEqual(PARTIAL_PROVIDER_FAILURE, result.coverage_state)
        self.assertEqual(20, result.represented_row_count)
        self.assertIn("contract_drift", result.failure_reason or "")

    def test_opt_in_provider_stops_before_an_over_budget_next_page(self) -> None:
        calls: list[tuple[str, float]] = []
        provider = provider_for_pages({1: finviz_html(1, 20, total=160)}, calls)
        result = provider.discover_paginated(
            INSTITUTIONAL_MOMENTUM,
            pagination_policy=policy(max_pages=5, max_rows=25),
            evaluated_at=BASE + timedelta(minutes=1),
        )
        self.assertEqual(BOUNDED_PAGE_PREFIX, result.coverage_state)
        self.assertEqual("MAX_ROWS_REACHED", result.truncation_reason)
        self.assertEqual(20, result.represented_row_count)
        self.assertEqual(1, len(calls))

    def test_opening_scan_remains_single_page_and_never_references_pagination(self) -> None:
        calls: list[tuple[str, float]] = []
        provider = provider_for_pages({1: finviz_html(1, 20, total=40)}, calls)
        candidates = provider.scan(INSTITUTIONAL_MOMENTUM)
        self.assertEqual(20, len(candidates))
        self.assertEqual(1, len(calls))
        self.assertNotIn("&r=", calls[0][0])
        opening_source = Path("momentum_hunter/automation_opening_capture.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("discover_paginated", opening_source)


if __name__ == "__main__":
    unittest.main()
