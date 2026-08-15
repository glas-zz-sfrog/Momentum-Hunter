from __future__ import annotations

import ast
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from momentum_hunter.broad_discovery import (
    COVERAGE_SCOPE_BOUNDED_PROVIDER_RESPONSE,
    PAGINATION_STATE_SINGLE_RESPONSE_UNPAGINATED,
    ROW_DISPOSITION_QUALIFIED,
    ROW_DISPOSITION_REJECTED_FILTER,
    SNAPSHOT_STATUS_COMPLETE,
    UNSEEN_ROW_COUNT_UNKNOWN,
    DiscoveryQueryIdentity,
    DiscoverySnapshot,
    DiscoverySourceRow,
    build_discovery_snapshot,
)
from momentum_hunter.models import BASE_MOMENTUM, INSTITUTIONAL_MOMENTUM, Candidate
from momentum_hunter.providers import (
    FINVIZ_CANONICAL_SCREENER_COLUMNS,
    FinvizProvider,
    ProviderContractError,
    ProviderSemanticPlausibilityError,
)


OBSERVED_AT = datetime(2026, 8, 17, 14, 35, tzinfo=timezone.utc)
CURRENT_HEADERS = list(FINVIZ_CANONICAL_SCREENER_COLUMNS)
LEGACY_HEADERS = [
    "No.",
    "Ticker",
    "Company",
    "Sector",
    "Industry",
    "Market Cap",
    "Shs Float",
    "ATR",
    "Rel Volume",
    "Volume",
    "Price",
    "Change",
]


def screener_row(
    ordinal: int,
    ticker: str,
    *,
    percent_change: float,
    volume: int = 4_000_000,
    price: float = 20.0,
    market_cap: str = "10B",
    relative_volume: float = 2.0,
    headers: list[str] = CURRENT_HEADERS,
) -> str:
    values = {
        "No.": str(ordinal),
        "Ticker": f'<td data-boxover-ticker="{ticker}">{ticker}</td>',
        "Company": f"{ticker} Incorporated",
        "Sector": "Technology",
        "Industry": "Software",
        "Market Cap": market_cap,
        "Float": "450M",
        "Shs Float": "450M",
        "ATR": "2.5",
        "Rel Volume": f"{relative_volume}",
        "Volume": f"{volume:,}",
        "Price": f"{price:.2f}",
        "Change %": f"{percent_change:.2f}%",
        "Change": f"{percent_change:.2f}%",
    }
    cells = []
    for header in headers:
        value = values[header]
        cells.append(value if header == "Ticker" else f"<td>{value}</td>")
    return "<tr>" + "".join(cells) + "</tr>"


def screener_html(rows: list[str], *, headers: list[str] = CURRENT_HEADERS) -> str:
    header_cells = "".join(f"<td>{header}</td>" for header in headers)
    return (
        '<table class="screener_table"><tr>'
        + header_cells
        + "</tr>"
        + "".join(rows)
        + "</table>"
    )


def provider_for_html(html: str) -> FinvizProvider:
    provider = FinvizProvider(sleeper=lambda _seconds: None, backoff_seconds=())

    class FakeResponse:
        text = html

        def raise_for_status(self) -> None:
            return None

    provider.session.get = lambda _url, **_kwargs: FakeResponse()
    return provider


def mixed_html() -> str:
    rows = [
        screener_row(1, "QONE", percent_change=4.0, volume=4_000_001, price=31.0),
        screener_row(2, "QTWO", percent_change=5.0, volume=4_000_002, price=32.0),
    ]
    rows.extend(
        screener_row(
            ordinal,
            f"R{ordinal:03d}",
            percent_change=1.0,
            volume=4_000_000 + ordinal,
            price=30.0 + ordinal,
        )
        for ordinal in range(3, 21)
    )
    return screener_html(rows)


def discover(provider: FinvizProvider) -> DiscoverySnapshot:
    return provider.discover(
        INSTITUTIONAL_MOMENTUM,
        requested_at=OBSERVED_AT,
        received_at=OBSERVED_AT,
        evaluated_at=OBSERVED_AT,
    )


class BroadDiscoverySnapshotTests(unittest.TestCase):
    def test_normal_mixed_response_reconciles_every_bounded_row(self) -> None:
        snapshot = discover(provider_for_html(mixed_html()))

        self.assertEqual(1, snapshot.contract_version)
        self.assertEqual(20, snapshot.raw_row_count)
        self.assertEqual(20, snapshot.parsed_row_count)
        self.assertEqual(20, snapshot.represented_row_count)
        self.assertEqual(2, snapshot.qualified_count)
        self.assertEqual(18, snapshot.rejected_count)
        self.assertEqual(20, len(snapshot.rows))
        self.assertEqual(
            20,
            snapshot.qualified_count + snapshot.rejected_count,
        )
        self.assertEqual(
            ["QTWO", "QONE"],
            [candidate.ticker for candidate in snapshot.qualified_candidates()],
        )
        self.assertEqual(
            ROW_DISPOSITION_QUALIFIED,
            snapshot.rows[0].disposition,
        )
        self.assertEqual(
            ROW_DISPOSITION_REJECTED_FILTER,
            snapshot.rows[2].disposition,
        )
        self.assertEqual(
            ("BELOW_MIN_PERCENT_CHANGE",),
            snapshot.rows[2].disposition_reasons,
        )

    def test_zero_qualified_response_is_complete_not_a_provider_failure(self) -> None:
        rows = [
            screener_row(
                ordinal,
                f"Z{ordinal:03d}",
                percent_change=1.0,
                volume=4_000_000 + ordinal,
                price=30.0 + ordinal,
            )
            for ordinal in range(1, 21)
        ]
        snapshot = discover(provider_for_html(screener_html(rows)))

        self.assertEqual(SNAPSHOT_STATUS_COMPLETE, snapshot.status)
        self.assertEqual(20, snapshot.represented_row_count)
        self.assertEqual(0, snapshot.qualified_count)
        self.assertEqual(20, snapshot.rejected_count)
        self.assertIsNone(snapshot.failure_reason)

    def test_header_only_response_preserves_existing_valid_empty_semantics(self) -> None:
        snapshot = discover(provider_for_html(screener_html([])))

        self.assertEqual(SNAPSHOT_STATUS_COMPLETE, snapshot.status)
        self.assertEqual(0, snapshot.raw_row_count)
        self.assertEqual(0, snapshot.parsed_row_count)
        self.assertEqual(0, snapshot.represented_row_count)
        self.assertEqual(0, snapshot.qualified_count)
        self.assertEqual(0, snapshot.rejected_count)

    def test_snapshot_explicitly_describes_bounded_single_response_coverage(self) -> None:
        snapshot = discover(provider_for_html(mixed_html()))

        self.assertEqual(
            COVERAGE_SCOPE_BOUNDED_PROVIDER_RESPONSE,
            snapshot.coverage_scope,
        )
        self.assertEqual(
            PAGINATION_STATE_SINGLE_RESPONSE_UNPAGINATED,
            snapshot.pagination_state,
        )
        self.assertEqual(1, snapshot.pages_requested)
        self.assertEqual(1, snapshot.pages_received)
        self.assertEqual(UNSEEN_ROW_COUNT_UNKNOWN, snapshot.unseen_row_count)
        self.assertNotIn("market", snapshot.coverage_scope.lower())

    def test_known_aliases_normalize_to_the_same_snapshot_contract(self) -> None:
        current = screener_html(
            [screener_row(1, "ALIAS", percent_change=4.0, price=35.0)]
        )
        legacy = screener_html(
            [
                screener_row(
                    1,
                    "ALIAS",
                    percent_change=4.0,
                    price=35.0,
                    headers=LEGACY_HEADERS,
                )
            ],
            headers=LEGACY_HEADERS,
        )

        current_snapshot = discover(provider_for_html(current))
        legacy_snapshot = discover(provider_for_html(legacy))

        self.assertEqual(current_snapshot.fingerprint, legacy_snapshot.fingerprint)
        self.assertEqual(
            "450M",
            legacy_snapshot.rows[0].source_values_dict()["Float"],
        )
        self.assertEqual(
            "4.00%",
            legacy_snapshot.rows[0].source_values_dict()["Change %"],
        )

    def test_query_or_policy_change_changes_snapshot_identity(self) -> None:
        first = discover(provider_for_html(mixed_html()))
        base_provider = provider_for_html(mixed_html())
        base_snapshot = base_provider.discover(
            BASE_MOMENTUM,
            requested_at=OBSERVED_AT,
            received_at=OBSERVED_AT,
            evaluated_at=OBSERVED_AT,
        )
        changed_query = DiscoveryQueryIdentity.from_criteria(
            INSTITUTIONAL_MOMENTUM,
            source_query="https://finviz.com/screener.ashx?v=151&f=changed&o=-volume&c=0",
            sort_order="-volume",
        )
        source_rows = [
            DiscoverySourceRow.from_mapping(
                source_row_ordinal=1,
                source_row_identity="1",
                source_values={"No.": "1", "Ticker": "QONE"},
                candidate=Candidate(
                    ticker="QONE",
                    company="QONE Incorporated",
                    sector="Technology",
                    industry="Software",
                    market_cap=10_000_000_000,
                    price=31.0,
                    percent_change=4.0,
                    volume=4_000_001,
                    relative_volume=2.0,
                    float_shares=450_000_000,
                    atr=2.5,
                ),
            )
        ]
        changed = build_discovery_snapshot(
            source="finviz",
            source_version=first.source_version,
            requested_at=OBSERVED_AT,
            received_at=OBSERVED_AT,
            evaluated_at=OBSERVED_AT,
            query_identity=changed_query,
            source_contract_fingerprint=first.source_contract_fingerprint,
            semantic_plausibility_fingerprint=first.semantic_plausibility_fingerprint,
            source_rows=source_rows,
        )

        self.assertNotEqual(first.query_fingerprint, base_snapshot.query_fingerprint)
        self.assertNotEqual(first.query_fingerprint, changed.query_fingerprint)
        self.assertNotEqual(first.snapshot_id, changed.snapshot_id)

    def test_duplicate_source_symbols_keep_distinct_row_identities_in_the_builder(self) -> None:
        query = DiscoveryQueryIdentity.from_criteria(
            INSTITUTIONAL_MOMENTUM,
            source_query="https://example.test/screener",
            sort_order="-volume",
        )
        source_rows = [
            DiscoverySourceRow.from_mapping(
                source_row_ordinal=ordinal,
                source_row_identity=str(ordinal),
                source_values={"No.": str(ordinal), "Ticker": "DUPL"},
                candidate=Candidate(
                    ticker="DUPL",
                    company="Duplicate Incorporated",
                    sector="Technology",
                    industry="Software",
                    market_cap=10_000_000_000,
                    price=20.0 + ordinal,
                    percent_change=4.0,
                    volume=4_000_000 + ordinal,
                    relative_volume=2.0,
                ),
            )
            for ordinal in (1, 2)
        ]
        snapshot = build_discovery_snapshot(
            source="finviz",
            source_version="test-v1",
            requested_at=OBSERVED_AT,
            received_at=OBSERVED_AT,
            evaluated_at=OBSERVED_AT,
            query_identity=query,
            source_contract_fingerprint="a" * 64,
            semantic_plausibility_fingerprint="b" * 64,
            source_rows=source_rows,
        )

        self.assertEqual(2, snapshot.represented_row_count)
        self.assertEqual(2, snapshot.qualified_count)
        self.assertNotEqual(snapshot.rows[0].row_id, snapshot.rows[1].row_id)
        self.assertNotEqual(
            snapshot.rows[0].candidate_identity,
            snapshot.rows[1].candidate_identity,
        )

    def test_provider_duplicate_symbol_failure_does_not_yield_a_valid_snapshot(self) -> None:
        html = screener_html(
            [
                screener_row(1, "DUPL", percent_change=4.0, price=20.0),
                screener_row(2, "DUPL", percent_change=4.0, price=21.0),
            ]
        )
        provider = provider_for_html(html)

        with self.assertRaises(ProviderSemanticPlausibilityError):
            discover(provider)

        self.assertIsNone(provider.last_discovery_snapshot)

    def test_structural_and_semantic_failures_cannot_become_empty_snapshots(self) -> None:
        malformed = """
            <table class="screener_table">
                <tr><td>No.</td><td>Ticker</td><td>Company</td></tr>
                <tr><td>1</td><td>BROKEN</td><td>Broken Incorporated</td></tr>
            </table>
        """
        structural_provider = provider_for_html(malformed)
        with self.assertRaises(ProviderContractError):
            discover(structural_provider)
        self.assertIsNone(structural_provider.last_discovery_snapshot)

        implausible = screener_html(
            [screener_row(1, "SCALE", percent_change=1434.0, price=50.0)]
        )
        semantic_provider = provider_for_html(implausible)
        with self.assertRaises(ProviderSemanticPlausibilityError):
            discover(semantic_provider)
        self.assertIsNone(semantic_provider.last_discovery_snapshot)

    def test_replay_is_byte_equivalent_and_tampering_is_rejected(self) -> None:
        first = discover(provider_for_html(mixed_html()))
        second = discover(provider_for_html(mixed_html()))

        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.canonical_json(), second.canonical_json())
        restored = DiscoverySnapshot.from_dict(json.loads(first.canonical_json()))
        self.assertEqual(first.canonical_json(), restored.canonical_json())

        tampered = first.to_dict()
        rows = tampered["rows"]
        assert isinstance(rows, list)
        first_row = rows[0]
        assert isinstance(first_row, dict)
        parsed_values = first_row["parsedValues"]
        assert isinstance(parsed_values, dict)
        parsed_values["price"] = 999.0
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            DiscoverySnapshot.from_dict(tampered)

    def test_opening_scan_compatibility_uses_the_same_candidates_and_ordering(self) -> None:
        old_interface_provider = provider_for_html(mixed_html())
        snapshot_provider = provider_for_html(mixed_html())

        compatibility_candidates = old_interface_provider.scan(INSTITUTIONAL_MOMENTUM)
        snapshot = discover(snapshot_provider)

        self.assertEqual(
            [candidate.__dict__ for candidate in compatibility_candidates],
            [candidate.__dict__ for candidate in snapshot.qualified_candidates()],
        )
        compatibility_diagnostics = old_interface_provider.last_scan_diagnostics
        snapshot_diagnostics = snapshot_provider.last_scan_diagnostics
        assert compatibility_diagnostics is not None
        assert snapshot_diagnostics is not None
        self.assertEqual(compatibility_diagnostics, snapshot_diagnostics)

    def test_pure_snapshot_module_has_no_transport_or_runtime_activation_imports(self) -> None:
        source_path = Path("momentum_hunter/broad_discovery.py")
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_modules.update(
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
            "momentum_hunter.execution",
            "momentum_hunter.trade_planning",
            "momentum_hunter.risk_governor",
        }
        self.assertFalse(imported_modules.intersection(forbidden))


if __name__ == "__main__":
    unittest.main()
