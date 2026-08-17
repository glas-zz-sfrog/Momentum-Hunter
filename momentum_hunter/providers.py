from __future__ import annotations

import hashlib
import json
import math
import re
import socket
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

import requests

from momentum_hunter.broad_discovery import (
    DiscoveryPageInput,
    DiscoveryPaginationPolicy,
    DiscoveryQueryIdentity,
    DiscoverySnapshot,
    DiscoverySourceRow,
    TRUNCATION_MAX_ELAPSED_TIME,
    TRUNCATION_MAX_PAGES,
    TRUNCATION_MAX_ROWS,
    build_discovery_snapshot,
    build_paginated_discovery_snapshot,
    filter_discovery_candidates,
    pagination_page_bound,
)
from momentum_hunter.models import Candidate, NewsItem, ScannerCriteria
from momentum_hunter.provider_semantic_plausibility import (
    ProviderSemanticDiagnostics,
    evaluate_provider_semantics,
)
from momentum_hunter.time_utils import CENTRAL_TZ, now_central


FINVIZ_BACKOFF_SECONDS = (10, 30, 60)
FINVIZ_QUOTE_BACKOFF_SECONDS: tuple[int, ...] = ()
FINVIZ_CUSTOM_COLUMN_IDS = (0, 1, 2, 3, 4, 6, 25, 49, 64, 67, 65, 66)
FINVIZ_CANONICAL_SCREENER_COLUMNS = (
    "No.",
    "Ticker",
    "Company",
    "Sector",
    "Industry",
    "Market Cap",
    "Float",
    "ATR",
    "Rel Volume",
    "Volume",
    "Price",
    "Change %",
)
FINVIZ_SCREENER_COLUMN_ALIASES = {
    "Change": "Change %",
    "Change %": "Change %",
    "Shs Float": "Float",
    "Float": "Float",
}
FINVIZ_DISCOVERY_SOURCE_VERSION = "finviz-screener-v151-custom-columns-v1"
FINVIZ_DISCOVERY_PARSER_CONTRACT_VERSION = 1
FINVIZ_DISCOVERY_PAGE_SIZE = 20


class ProviderUnavailableError(RuntimeError):
    def __init__(self, provider: str, message: str, reason: str = "unavailable") -> None:
        super().__init__(message)
        self.provider = provider
        self.reason = reason
        self.user_message = message


class ProviderContractError(ProviderUnavailableError):
    def __init__(self, message: str) -> None:
        super().__init__(
            provider="finviz",
            message=message,
            reason="contract_drift",
        )


class ProviderSemanticPlausibilityError(ProviderUnavailableError):
    def __init__(self, diagnostics: ProviderSemanticDiagnostics) -> None:
        self.diagnostics = diagnostics
        super().__init__(
            provider=diagnostics.provider,
            message=(
                "Provider semantic plausibility failed closed: diagnostics="
                + json.dumps(
                    diagnostics.to_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ),
            reason="semantic_implausibility",
        )


@dataclass(frozen=True)
class ProviderScanDiagnostics:
    provider: str
    schema_fingerprint: str
    observed_headers: tuple[str, ...]
    canonical_headers: tuple[str, ...]
    data_row_count: int
    parsed_row_count: int
    qualifying_candidate_count: int
    semantic_status: str = "UNAVAILABLE"
    semantic_fingerprint: str = ""
    semantic_issue_codes: tuple[str, ...] = ()
    semantic_rejection_reason_counts: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class _ParsedFinvizDiscoveryPage:
    candidates: tuple[Candidate, ...]
    source_rows: tuple[DiscoverySourceRow, ...]
    observed_headers: tuple[str, ...]
    canonical_headers: tuple[str, ...]
    schema_fingerprint: str
    semantic_diagnostics: ProviderSemanticDiagnostics
    provider_total_results: int | None
    page_size: int


class MarketDataProvider(ABC):
    name: str

    @abstractmethod
    def scan(self, criteria: ScannerCriteria) -> list[Candidate]:
        raise NotImplementedError

    @abstractmethod
    def fetch_news(self, ticker: str, as_of: datetime | None = None) -> list[NewsItem]:
        raise NotImplementedError


class SampleProvider(MarketDataProvider):
    name = "sample"

    def scan(self, criteria: ScannerCriteria) -> list[Candidate]:
        current = now_central()
        candidates = [
            Candidate(
                ticker="MU",
                company="Micron Technology",
                price=128.45,
                percent_change=6.8,
                volume=35_200_000,
                relative_volume=2.3,
                market_cap=142_000_000_000,
                sector="Technology",
                industry="Semiconductors",
                news=[
                    NewsItem(
                        headline="Micron rallies after stronger AI memory demand commentary",
                        source="Sample",
                        published_at=current - timedelta(hours=6),
                        summary="AI infrastructure demand and analyst follow-through are supporting momentum.",
                    ),
                    NewsItem(
                        headline="Analysts lift targets following upbeat earnings outlook",
                        source="Sample",
                        published_at=current - timedelta(hours=11),
                        summary="Upgrade and target activity suggests institutional attention.",
                    ),
                ],
            ),
            Candidate(
                ticker="DELL",
                company="Dell Technologies",
                price=151.20,
                percent_change=4.9,
                volume=12_850_000,
                relative_volume=1.7,
                market_cap=105_000_000_000,
                sector="Technology",
                industry="Computer Hardware",
                news=[
                    NewsItem(
                        headline="Dell gains as AI server backlog expands",
                        source="Sample",
                        published_at=current - timedelta(hours=31),
                        summary="AI server demand is the primary catalyst.",
                    )
                ],
            ),
            Candidate(
                ticker="PLTR",
                company="Palantir Technologies",
                price=72.30,
                percent_change=5.4,
                volume=55_000_000,
                relative_volume=1.6,
                market_cap=166_000_000_000,
                sector="Technology",
                industry="Software - Infrastructure",
                news=[
                    NewsItem(
                        headline="Palantir extends move on enterprise AI platform demand",
                        source="Sample",
                        published_at=current - timedelta(days=3),
                        summary="Large-cap momentum and AI theme alignment remain strong.",
                    )
                ],
            ),
            Candidate(
                ticker="XYZP",
                company="Example Microcap",
                price=2.10,
                percent_change=42.0,
                volume=900_000,
                relative_volume=6.8,
                market_cap=85_000_000,
                sector="Healthcare",
                industry="Biotechnology",
                news=[
                    NewsItem(
                        headline="Thinly traded microcap spikes on vague promotion",
                        source="Sample",
                        published_at=current - timedelta(days=28),
                    )
                ],
            ),
        ]
        return filter_candidates(candidates, criteria)

    def fetch_news(self, ticker: str, as_of: datetime | None = None) -> list[NewsItem]:
        for candidate in self.scan(criteria=_loose_criteria()):
            if candidate.ticker == ticker:
                return candidate.news
        return []


class FinvizProvider(MarketDataProvider):
    name = "finviz"
    base_url = "https://finviz.com"

    def __init__(
        self,
        *,
        sleeper=time.sleep,
        backoff_seconds: tuple[int, ...] = FINVIZ_BACKOFF_SECONDS,
        quote_backoff_seconds: tuple[int, ...] = FINVIZ_QUOTE_BACKOFF_SECONDS,
    ) -> None:
        self.sleeper = sleeper
        self.backoff_seconds = backoff_seconds
        self.quote_backoff_seconds = quote_backoff_seconds
        self._quote_html_cache: dict[str, str] = {}
        self.last_scan_diagnostics: ProviderScanDiagnostics | None = None
        self.last_semantic_diagnostics: ProviderSemanticDiagnostics | None = None
        self.last_discovery_snapshot: DiscoverySnapshot | None = None
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
                )
            }
        )

    def scan(self, criteria: ScannerCriteria) -> list[Candidate]:
        """Return the legacy opening-scan result from the bounded snapshot path."""

        return list(self.discover(criteria).qualified_candidates())

    def discover(
        self,
        criteria: ScannerCriteria,
        *,
        requested_at: datetime | None = None,
        received_at: datetime | None = None,
        evaluated_at: datetime | None = None,
    ) -> DiscoverySnapshot:
        """Acquire one Finviz response and return its complete bounded snapshot."""

        from bs4 import BeautifulSoup

        self.last_scan_diagnostics = None
        self.last_semantic_diagnostics = None
        self.last_discovery_snapshot = None
        observed_requested_at = requested_at or now_central()
        url = self._screener_url(criteria)
        response = self._get_with_retries(url, action="scan")
        observed_received_at = received_at or now_central()
        observed_evaluated_at = evaluated_at or now_central()
        soup = BeautifulSoup(response.text, "lxml")
        table = soup.find("table", class_="screener_table")
        if table is None:
            raise RuntimeError("Finviz screener table was not found. Try Sample provider or update parser.")

        rows = table.find_all("tr")
        if not rows:
            raise ProviderContractError(
                "Finviz screener schema drift detected: the table has no header row."
            )
        headers = finviz_screener_headers(rows[0])
        canonical_headers = validate_finviz_screener_headers(headers)
        schema_fingerprint = finviz_screener_schema_fingerprint(canonical_headers)
        data_rows = [row for row in rows[1:] if row.find_all(["th", "td"])]
        candidates: list[Candidate] = []
        discovery_source_rows: list[DiscoverySourceRow] = []
        for row_number, row in enumerate(data_rows, start=1):
            values = finviz_screener_row(row, headers, row_number=row_number)
            ticker = required_finviz_text(values, "Ticker", row_number=row_number)
            candidate = Candidate(
                ticker=ticker,
                company=required_finviz_text(
                    values,
                    "Company",
                    row_number=row_number,
                ),
                sector=required_finviz_text(
                    values,
                    "Sector",
                    row_number=row_number,
                ),
                industry=required_finviz_text(
                    values,
                    "Industry",
                    row_number=row_number,
                ),
                market_cap=parse_required_market_cap(
                    values.get("Market Cap", ""),
                    field="Market Cap",
                    row_number=row_number,
                ),
                price=parse_required_finviz_float(
                    values.get("Price", ""),
                    field="Price",
                    row_number=row_number,
                    positive=True,
                ),
                percent_change=parse_required_finviz_float(
                    finviz_screener_value(values, "Change", "Change %").replace("%", ""),
                    field="Change %",
                    row_number=row_number,
                ),
                volume=parse_required_finviz_int(
                    values.get("Volume", ""),
                    field="Volume",
                    row_number=row_number,
                    positive=True,
                ),
                relative_volume=parse_optional_finviz_float(
                    values.get("Rel Volume", ""),
                    field="Rel Volume",
                    row_number=row_number,
                ) or 0.0,
                float_shares=(
                    parse_optional_finviz_market_cap(
                        finviz_screener_value(values, "Shs Float", "Float"),
                        field="Float",
                        row_number=row_number,
                    )
                ),
                atr=parse_optional_finviz_float(
                    values.get("ATR", ""),
                    field="ATR",
                    row_number=row_number,
                ),
            )
            candidates.append(candidate)
            normalized_values = canonicalize_finviz_screener_values(values)
            discovery_source_rows.append(
                DiscoverySourceRow.from_mapping(
                    source_row_ordinal=row_number,
                    source_row_identity=normalized_values.get("No.", str(row_number)),
                    source_values=normalized_values,
                    candidate=candidate,
                )
            )

        semantic_diagnostics = evaluate_provider_semantics(
            candidates,
            criteria,
            provider=self.name,
            input_row_count=len(data_rows),
        )
        self.last_semantic_diagnostics = semantic_diagnostics
        if semantic_diagnostics.status != "PASS":
            raise ProviderSemanticPlausibilityError(semantic_diagnostics)

        qualifying = filter_discovery_candidates(candidates, criteria)
        if len(qualifying) != semantic_diagnostics.qualifying_candidate_count:
            raise ProviderUnavailableError(
                provider=self.name,
                reason="semantic_implausibility",
                message=(
                    "Provider semantic plausibility failed closed: qualification "
                    "accounting disagrees with candidate filtering; "
                    f"fingerprint={semantic_diagnostics.fingerprint}; "
                    f"semanticQualifying={semantic_diagnostics.qualifying_candidate_count}; "
                    f"filterQualifying={len(qualifying)}."
                ),
            )
        query_identity = DiscoveryQueryIdentity.from_criteria(
            criteria,
            source_query=url,
            sort_order="-volume",
        )
        snapshot = build_discovery_snapshot(
            source=self.name,
            source_version=FINVIZ_DISCOVERY_SOURCE_VERSION,
            requested_at=observed_requested_at,
            received_at=observed_received_at,
            evaluated_at=observed_evaluated_at,
            query_identity=query_identity,
            source_contract_fingerprint=finviz_discovery_contract_fingerprint(
                schema_fingerprint
            ),
            semantic_plausibility_fingerprint=semantic_diagnostics.fingerprint,
            source_rows=discovery_source_rows,
            raw_row_count=len(data_rows),
        )
        if list(snapshot.qualified_candidates()) != qualifying:
            raise ProviderUnavailableError(
                provider=self.name,
                reason="semantic_implausibility",
                message=(
                    "Provider semantic plausibility failed closed: discovery snapshot "
                    "qualification ordering disagrees with candidate filtering; "
                    f"fingerprint={semantic_diagnostics.fingerprint}."
                ),
            )
        self.last_scan_diagnostics = ProviderScanDiagnostics(
            provider=self.name,
            schema_fingerprint=schema_fingerprint,
            observed_headers=tuple(headers),
            canonical_headers=canonical_headers,
            data_row_count=len(data_rows),
            parsed_row_count=len(candidates),
            qualifying_candidate_count=len(qualifying),
            semantic_status=semantic_diagnostics.status,
            semantic_fingerprint=semantic_diagnostics.fingerprint,
            semantic_issue_codes=semantic_diagnostics.issue_codes,
            semantic_rejection_reason_counts=(
                semantic_diagnostics.rejection_reason_counts
            ),
        )
        self.last_discovery_snapshot = snapshot
        return snapshot

    def discover_paginated(
        self,
        criteria: ScannerCriteria,
        *,
        pagination_policy: DiscoveryPaginationPolicy,
        requested_at: datetime | None = None,
        evaluated_at: datetime | None = None,
    ) -> DiscoverySnapshot:
        """Explicitly acquire one bounded multi-page Finviz discovery pulse.

        This method is intentionally separate from ``discover`` and ``scan``.
        Nothing in the opening runtime calls it: a future owner must opt in with
        a versioned page policy and consume the resulting coverage truth.
        """

        self.last_scan_diagnostics = None
        self.last_semantic_diagnostics = None
        self.last_discovery_snapshot = None
        if pagination_policy.max_rows < FINVIZ_DISCOVERY_PAGE_SIZE:
            raise ValueError(
                "Finviz paginated discovery max_rows must accommodate one complete page."
            )
        del requested_at
        pulse_started_monotonic = time.monotonic()
        observed_evaluated_at = evaluated_at or now_central()
        source_query = self._screener_url(criteria)
        query_identity = DiscoveryQueryIdentity.from_criteria(
            criteria,
            source_query=source_query,
            sort_order="-volume",
            page_bound=pagination_page_bound(pagination_policy),
        )
        pages: list[DiscoveryPageInput] = []
        collected_rows = 0
        known_page_size = FINVIZ_DISCOVERY_PAGE_SIZE
        termination_reason: str | None = None

        for page_number in range(1, pagination_policy.max_pages + 1):
            if pages and (time.monotonic() - pulse_started_monotonic) >= (
                pagination_policy.maximum_elapsed_time_seconds
            ):
                termination_reason = TRUNCATION_MAX_ELAPSED_TIME
                break
            if pages and collected_rows + known_page_size > pagination_policy.max_rows:
                termination_reason = TRUNCATION_MAX_ROWS
                break
            page_offset = 1 + ((page_number - 1) * known_page_size)
            page_requested_at = now_central()
            started_monotonic = time.monotonic()
            try:
                response = self._get_with_retries(
                    self._screener_page_url(criteria, page_offset=page_offset),
                    action=f"paginated scan page {page_number}",
                    timeout_seconds=pagination_policy.per_page_timeout_seconds,
                )
                page_received_at = now_central()
                parsed = self._parse_discovery_page(response.text, criteria)
            except ProviderUnavailableError as exc:
                page_received_at = now_central()
                pages.append(
                    DiscoveryPageInput(
                        page_number=page_number,
                        page_offset=page_offset,
                        requested_at=page_requested_at,
                        received_at=page_received_at,
                        request_duration_milliseconds=int(
                            (time.monotonic() - started_monotonic) * 1000
                        ),
                        failure_reason=f"{exc.reason}:{type(exc).__name__}",
                    )
                )
                break
            except Exception as exc:
                page_received_at = now_central()
                pages.append(
                    DiscoveryPageInput(
                        page_number=page_number,
                        page_offset=page_offset,
                        requested_at=page_requested_at,
                        received_at=page_received_at,
                        request_duration_milliseconds=int(
                            (time.monotonic() - started_monotonic) * 1000
                        ),
                        failure_reason=f"unclassified:{type(exc).__name__}",
                    )
                )
                break

            known_page_size = parsed.page_size
            last_row_ordinal = page_offset + len(parsed.source_rows) - 1
            terminal_page = (
                parsed.provider_total_results is not None
                and last_row_ordinal >= parsed.provider_total_results
            ) or len(parsed.source_rows) < parsed.page_size
            pages.append(
                DiscoveryPageInput(
                    page_number=page_number,
                    page_offset=page_offset,
                    requested_at=page_requested_at,
                    received_at=page_received_at,
                    request_duration_milliseconds=int(
                        (time.monotonic() - started_monotonic) * 1000
                    ),
                    source_rows=parsed.source_rows,
                    raw_row_count=len(parsed.source_rows),
                    source_contract_fingerprint=finviz_discovery_contract_fingerprint(
                        parsed.schema_fingerprint
                    ),
                    semantic_plausibility_fingerprint=parsed.semantic_diagnostics.fingerprint,
                    provider_total_results=parsed.provider_total_results,
                    provider_page_size=parsed.page_size,
                    terminal_page=terminal_page,
                )
            )
            collected_rows += len(parsed.source_rows)
            self.last_scan_diagnostics = ProviderScanDiagnostics(
                provider=self.name,
                schema_fingerprint=parsed.schema_fingerprint,
                observed_headers=parsed.observed_headers,
                canonical_headers=parsed.canonical_headers,
                data_row_count=len(parsed.source_rows),
                parsed_row_count=len(parsed.candidates),
                qualifying_candidate_count=len(
                    filter_discovery_candidates(parsed.candidates, criteria)
                ),
                semantic_status=parsed.semantic_diagnostics.status,
                semantic_fingerprint=parsed.semantic_diagnostics.fingerprint,
                semantic_issue_codes=parsed.semantic_diagnostics.issue_codes,
                semantic_rejection_reason_counts=(
                    parsed.semantic_diagnostics.rejection_reason_counts
                ),
            )
            self.last_semantic_diagnostics = parsed.semantic_diagnostics
            if terminal_page:
                break
            if collected_rows >= pagination_policy.max_rows:
                termination_reason = TRUNCATION_MAX_ROWS
                break
            if page_number == pagination_policy.max_pages:
                termination_reason = TRUNCATION_MAX_PAGES
                break
            if pagination_policy.inter_request_delay_seconds:
                self.sleeper(pagination_policy.inter_request_delay_seconds)

        if not pages:
            raise RuntimeError("Paginated discovery did not issue a bounded page request.")
        snapshot = build_paginated_discovery_snapshot(
            source=self.name,
            source_version=FINVIZ_DISCOVERY_SOURCE_VERSION,
            evaluated_at=observed_evaluated_at,
            query_identity=query_identity,
            pagination_policy=pagination_policy,
            page_inputs=pages,
            termination_reason=termination_reason,
        )
        self.last_discovery_snapshot = snapshot
        return snapshot

    def fetch_news(self, ticker: str, as_of: datetime | None = None) -> list[NewsItem]:
        from bs4 import BeautifulSoup

        cutoff = as_of or now_central()
        soup = BeautifulSoup(self._quote_html(ticker), "lxml")
        news_table = soup.find(id="news-table")
        if news_table is None:
            return []

        items: list[NewsItem] = []
        for row in news_table.find_all("tr")[:8]:
            link = row.find("a")
            if link is None:
                continue
            timestamp_text = row.find("td").get_text(" ", strip=True) if row.find("td") else ""
            published_at = parse_finviz_news_time(timestamp_text, now=cutoff)
            if published_at is not None and published_at > cutoff:
                continue
            items.append(
                NewsItem(
                    headline=link.get_text(" ", strip=True),
                    source="Finviz",
                    published_at=published_at,
                    url=link.get("href", ""),
                    summary=summarize_catalyst(link.get_text(" ", strip=True)),
                )
            )
        return items

    def _apply_quote_snapshot_fields(self, candidate: Candidate) -> None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(self._quote_html(candidate.ticker), "lxml")
        snapshot_table = soup.find("table", class_=lambda value: value and "snapshot-table" in value)
        if snapshot_table is None:
            return
        cells = [cell.get_text(" ", strip=True) for cell in snapshot_table.find_all("td")]
        values = parse_finviz_snapshot_values(cells)
        relative_volume = parse_float(values.get("rel volume", "").replace("x", ""))
        if relative_volume > 0:
            candidate.relative_volume = relative_volume

    def _quote_html(self, ticker: str) -> str:
        normalized = ticker.upper().strip()
        if normalized not in self._quote_html_cache:
            url = f"{self.base_url}/quote.ashx?t={normalized}"
            response = self._get_with_retries(
                url,
                action=f"quote snapshot for {normalized}",
                backoff_seconds=self.quote_backoff_seconds,
            )
            self._quote_html_cache[normalized] = response.text
        return self._quote_html_cache[normalized]

    def _screener_url(self, criteria: ScannerCriteria) -> str:
        cap_filter = "cap_midover" if criteria.min_market_cap >= 2_000_000_000 else "cap_smallover"
        price_filter = "sh_price_o10" if criteria.min_price >= 10 else "sh_price_o5"
        volume_filter = "sh_avgvol_o3000" if criteria.min_volume >= 3_000_000 else "sh_avgvol_o1000"
        change_filter = "ta_change_u3" if criteria.min_percent_change <= 3 else "ta_change_u5"
        filters = ",".join([cap_filter, price_filter, volume_filter, change_filter])
        columns = ",".join(str(item) for item in FINVIZ_CUSTOM_COLUMN_IDS)
        return f"{self.base_url}/screener.ashx?v=151&f={filters}&o=-volume&c={columns}"

    def _screener_page_url(
        self,
        criteria: ScannerCriteria,
        *,
        page_offset: int,
    ) -> str:
        if page_offset < 1:
            raise ValueError("Finviz screener page offsets must be positive.")
        base = self._screener_url(criteria)
        return base if page_offset == 1 else f"{base}&r={page_offset}"

    def _parse_discovery_page(
        self,
        html: str,
        criteria: ScannerCriteria,
    ) -> _ParsedFinvizDiscoveryPage:
        """Parse and validate one already-fetched Finviz screener page."""

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table", class_="screener_table")
        if table is None:
            raise RuntimeError(
                "Finviz screener table was not found. Try Sample provider or update parser."
            )
        rows = table.find_all("tr")
        if not rows:
            raise ProviderContractError(
                "Finviz screener schema drift detected: the table has no header row."
            )
        headers = finviz_screener_headers(rows[0])
        canonical_headers = validate_finviz_screener_headers(headers)
        schema_fingerprint = finviz_screener_schema_fingerprint(canonical_headers)
        data_rows = [row for row in rows[1:] if row.find_all(["th", "td"])]
        if len(data_rows) > FINVIZ_DISCOVERY_PAGE_SIZE:
            raise ProviderContractError(
                "Finviz screener page exceeded the proven page-size contract."
            )
        candidates: list[Candidate] = []
        discovery_source_rows: list[DiscoverySourceRow] = []
        for row_number, row in enumerate(data_rows, start=1):
            values = finviz_screener_row(row, headers, row_number=row_number)
            ticker = required_finviz_text(values, "Ticker", row_number=row_number)
            candidate = Candidate(
                ticker=ticker,
                company=required_finviz_text(values, "Company", row_number=row_number),
                sector=required_finviz_text(values, "Sector", row_number=row_number),
                industry=required_finviz_text(values, "Industry", row_number=row_number),
                market_cap=parse_required_market_cap(
                    values.get("Market Cap", ""),
                    field="Market Cap",
                    row_number=row_number,
                ),
                price=parse_required_finviz_float(
                    values.get("Price", ""),
                    field="Price",
                    row_number=row_number,
                    positive=True,
                ),
                percent_change=parse_required_finviz_float(
                    finviz_screener_value(values, "Change", "Change %").replace("%", ""),
                    field="Change %",
                    row_number=row_number,
                ),
                volume=parse_required_finviz_int(
                    values.get("Volume", ""),
                    field="Volume",
                    row_number=row_number,
                    positive=True,
                ),
                relative_volume=parse_optional_finviz_float(
                    values.get("Rel Volume", ""),
                    field="Rel Volume",
                    row_number=row_number,
                )
                or 0.0,
                float_shares=parse_optional_finviz_market_cap(
                    finviz_screener_value(values, "Shs Float", "Float"),
                    field="Float",
                    row_number=row_number,
                ),
                atr=parse_optional_finviz_float(
                    values.get("ATR", ""),
                    field="ATR",
                    row_number=row_number,
                ),
            )
            candidates.append(candidate)
            normalized_values = canonicalize_finviz_screener_values(values)
            discovery_source_rows.append(
                DiscoverySourceRow.from_mapping(
                    source_row_ordinal=row_number,
                    source_row_identity=normalized_values.get("No.", str(row_number)),
                    source_values=normalized_values,
                    candidate=candidate,
                )
            )
        semantic_diagnostics = evaluate_provider_semantics(
            candidates,
            criteria,
            provider=self.name,
            input_row_count=len(data_rows),
        )
        if semantic_diagnostics.status != "PASS":
            raise ProviderSemanticPlausibilityError(semantic_diagnostics)
        qualifying = filter_discovery_candidates(candidates, criteria)
        if len(qualifying) != semantic_diagnostics.qualifying_candidate_count:
            raise ProviderUnavailableError(
                provider=self.name,
                reason="semantic_implausibility",
                message=(
                    "Provider semantic plausibility failed closed: qualification "
                    "accounting disagrees with candidate filtering; "
                    f"fingerprint={semantic_diagnostics.fingerprint}; "
                    f"semanticQualifying={semantic_diagnostics.qualifying_candidate_count}; "
                    f"filterQualifying={len(qualifying)}."
                ),
            )
        return _ParsedFinvizDiscoveryPage(
            candidates=tuple(candidates),
            source_rows=tuple(discovery_source_rows),
            observed_headers=tuple(headers),
            canonical_headers=canonical_headers,
            schema_fingerprint=schema_fingerprint,
            semantic_diagnostics=semantic_diagnostics,
            provider_total_results=finviz_screener_total_results(soup),
            page_size=FINVIZ_DISCOVERY_PAGE_SIZE,
        )

    def _get_with_retries(
        self,
        url: str,
        *,
        action: str,
        backoff_seconds: tuple[int, ...] | None = None,
        timeout_seconds: float = 20,
    ) -> requests.Response:
        last_error: Exception | None = None
        retry_delays = self.backoff_seconds if backoff_seconds is None else backoff_seconds
        attempts = len(retry_delays) + 1
        for attempt in range(attempts):
            try:
                response = self.session.get(url, timeout=timeout_seconds)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt < len(retry_delays):
                    self.sleeper(retry_delays[attempt])
                    continue
                raise provider_error_from_exception(self.name, action, exc) from exc
        raise provider_error_from_exception(self.name, action, last_error or RuntimeError("unknown provider failure"))


def finviz_screener_headers(row: object) -> list[str]:
    cells = row.find_all(["th", "td"])
    return [cell.get_text(" ", strip=True) for cell in cells]


def finviz_screener_total_results(soup: object) -> int | None:
    """Return Finviz's visible filtered-result total when the page exposes one."""

    text = soup.get_text(" ", strip=True)
    matches = {
        int(item.replace(",", ""))
        for item in re.findall(r"\b([\d,]+)\s+Total\b", text, flags=re.IGNORECASE)
    }
    if not matches:
        return None
    if len(matches) != 1:
        raise ProviderContractError(
            "Finviz screener exposed contradictory filtered-result totals."
        )
    return next(iter(matches))


def finviz_screener_row(
    row: object,
    headers: list[str],
    *,
    row_number: int = 0,
) -> dict[str, str]:
    cells = row.find_all("td")
    if len(cells) != len(headers):
        raise ProviderContractError(
            "Finviz screener row shape changed: "
            f"row {row_number or 'unknown'} has {len(cells)} cells; "
            f"the schema has {len(headers)} columns."
        )
    values: dict[str, str] = {}
    for header, cell in zip(headers, cells):
        value = cell.get_text(" ", strip=True)
        if header == "Ticker":
            ticker_attribute = cell.get("data-boxover-ticker")
            value = str(ticker_attribute or (value.split()[0] if value else ""))
        values[header] = value
    return values


def finviz_screener_value(values: dict[str, str], *names: str) -> str:
    for name in names:
        if name in values:
            return values[name]
    return ""


def canonicalize_finviz_screener_headers(headers: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        FINVIZ_SCREENER_COLUMN_ALIASES.get(header.strip(), header.strip())
        for header in headers
    )


def canonicalize_finviz_screener_values(values: dict[str, str]) -> dict[str, str]:
    """Normalize known Finviz header aliases before snapshot fingerprinting."""

    normalized: dict[str, str] = {}
    for header, value in values.items():
        canonical_header = FINVIZ_SCREENER_COLUMN_ALIASES.get(
            header.strip(),
            header.strip(),
        )
        if canonical_header in normalized:
            raise ProviderContractError(
                "Finviz screener schema drift detected: duplicate canonical columns."
            )
        normalized[canonical_header] = value
    return normalized


def finviz_screener_schema_fingerprint(headers: Iterable[str]) -> str:
    canonical = canonicalize_finviz_screener_headers(headers)
    serialized = json.dumps(canonical, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def finviz_discovery_contract_fingerprint(schema_fingerprint: str) -> str:
    payload = {
        "sourceVersion": FINVIZ_DISCOVERY_SOURCE_VERSION,
        "parserContractVersion": FINVIZ_DISCOVERY_PARSER_CONTRACT_VERSION,
        "schemaFingerprint": schema_fingerprint,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def validate_finviz_screener_headers(headers: list[str]) -> tuple[str, ...]:
    canonical = canonicalize_finviz_screener_headers(headers)
    if canonical != FINVIZ_CANONICAL_SCREENER_COLUMNS:
        missing = [
            name for name in FINVIZ_CANONICAL_SCREENER_COLUMNS if name not in canonical
        ]
        unexpected = [
            name for name in canonical if name not in FINVIZ_CANONICAL_SCREENER_COLUMNS
        ]
        detail = []
        if missing:
            detail.append(f"missing={','.join(missing)}")
        if unexpected:
            detail.append(f"unexpected={','.join(unexpected)}")
        if not missing and not unexpected:
            detail.append("column-order-changed")
        raise ProviderContractError(
            "Finviz screener schema drift detected: "
            f"{'; '.join(detail)}. Observed columns: {', '.join(headers)}."
        )
    if len(set(canonical)) != len(canonical):
        raise ProviderContractError(
            "Finviz screener schema drift detected: duplicate canonical columns."
        )
    return canonical


def required_finviz_text(
    values: dict[str, str],
    field: str,
    *,
    row_number: int,
) -> str:
    value = values.get(field, "").strip()
    if not value:
        raise ProviderContractError(
            f"Finviz screener row {row_number} is missing required field {field}."
        )
    return value


def parse_required_finviz_float(
    value: str,
    *,
    field: str,
    row_number: int,
    positive: bool = False,
) -> float:
    normalized = value.strip().replace(",", "")
    try:
        parsed = float(normalized)
    except ValueError as exc:
        raise ProviderContractError(
            f"Finviz screener row {row_number} has invalid {field}."
        ) from exc
    if not math.isfinite(parsed) or (positive and parsed <= 0):
        raise ProviderContractError(
            f"Finviz screener row {row_number} has invalid {field}."
        )
    return parsed


def parse_required_finviz_int(
    value: str,
    *,
    field: str,
    row_number: int,
    positive: bool = False,
) -> int:
    parsed = parse_required_finviz_float(
        value,
        field=field,
        row_number=row_number,
        positive=positive,
    )
    if not parsed.is_integer():
        raise ProviderContractError(
            f"Finviz screener row {row_number} has invalid {field}."
        )
    return int(parsed)


def parse_required_market_cap(
    value: str,
    *,
    field: str,
    row_number: int,
) -> int:
    parsed = parse_optional_finviz_market_cap(
        value,
        field=field,
        row_number=row_number,
    )
    if parsed is None or parsed <= 0:
        raise ProviderContractError(
            f"Finviz screener row {row_number} has invalid {field}."
        )
    return parsed


def parse_optional_finviz_float(
    value: str,
    *,
    field: str,
    row_number: int,
) -> float | None:
    normalized = value.strip()
    if normalized in {"", "-", "N/A"}:
        return None
    parsed = parse_required_finviz_float(
        normalized,
        field=field,
        row_number=row_number,
    )
    if parsed < 0:
        raise ProviderContractError(
            f"Finviz screener row {row_number} has invalid {field}."
        )
    return parsed


def parse_optional_finviz_market_cap(
    value: str,
    *,
    field: str,
    row_number: int,
) -> int | None:
    normalized = value.strip().replace(",", "").upper()
    if normalized in {"", "-", "N/A"}:
        return None
    match = re.fullmatch(r"([\d.]+)([MBT])", normalized)
    if not match:
        raise ProviderContractError(
            f"Finviz screener row {row_number} has invalid {field}."
        )
    number = float(match.group(1))
    if not math.isfinite(number) or number <= 0:
        raise ProviderContractError(
            f"Finviz screener row {row_number} has invalid {field}."
        )
    multiplier = {
        "M": 1_000_000,
        "B": 1_000_000_000,
        "T": 1_000_000_000_000,
    }[match.group(2)]
    return int(number * multiplier)


def provider_from_name(name: str) -> MarketDataProvider:
    if name == FinvizProvider.name:
        return FinvizProvider()
    return SampleProvider()


def provider_error_from_exception(provider: str, action: str, exc: BaseException) -> ProviderUnavailableError:
    if is_dns_failure(exc):
        return ProviderUnavailableError(
            provider=provider,
            reason="dns_failure",
            message=f"Provider unavailable / DNS failure while running {provider} {action}.",
        )
    return ProviderUnavailableError(
        provider=provider,
        reason="request_failure",
        message=f"Provider unavailable while running {provider} {action}.",
    )


def is_dns_failure(exc: BaseException | None) -> bool:
    current = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, socket.gaierror):
            return True
        message = str(current).lower()
        if "getaddrinfo failed" in message or "failed to resolve" in message or "name resolution" in message:
            return True
        current = current.__cause__ or current.__context__
    return False


def parse_finviz_news_time(value: str, now: datetime | None = None) -> datetime | None:
    value = " ".join(value.split())
    if not value:
        return None
    current = now or now_central()
    parts = value.split()
    try:
        if len(parts) == 1:
            parsed_time = datetime.strptime(parts[0], "%I:%M%p").time()
            return datetime.combine(current.date(), parsed_time, tzinfo=CENTRAL_TZ)
        date_text, time_text = parts[0], parts[1]
        parsed_time = datetime.strptime(time_text, "%I:%M%p").time()
        if date_text.lower() == "today":
            return datetime.combine(current.date(), parsed_time, tzinfo=CENTRAL_TZ)
        if date_text.lower() == "yesterday":
            return datetime.combine((current - timedelta(days=1)).date(), parsed_time, tzinfo=CENTRAL_TZ)
        parsed_date = datetime.strptime(date_text, "%b-%d-%y").date()
        return datetime.combine(parsed_date, parsed_time, tzinfo=CENTRAL_TZ)
    except ValueError:
        return None


def filter_candidates(candidates: Iterable[Candidate], criteria: ScannerCriteria) -> list[Candidate]:
    """Backward-compatible public name for the shared discovery filter path."""

    return filter_discovery_candidates(candidates, criteria)


def summarize_catalyst(headline: str) -> str:
    headline_lower = headline.lower()
    catalyst_map = {
        "earnings": "Potential earnings catalyst.",
        "guidance": "Potential guidance catalyst.",
        "upgrade": "Potential analyst upgrade catalyst.",
        "price target": "Potential analyst target catalyst.",
        "ai": "Potential AI infrastructure or automation theme.",
        "partnership": "Potential partnership catalyst.",
        "fda": "Potential FDA catalyst.",
    }
    for keyword, summary in catalyst_map.items():
        if keyword in headline_lower:
            return summary
    return "Review headline for catalyst quality."


def parse_market_cap(value: str) -> int:
    match = re.match(r"([\d.]+)([MBT])", value.replace(",", "").upper())
    if not match:
        return 0
    number = float(match.group(1))
    multiplier = {"M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}[match.group(2)]
    return int(number * multiplier)


def parse_percent(value: str) -> float:
    return parse_float(value.replace("%", ""))


def parse_float(value: str) -> float:
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return 0.0


def parse_int(value: str) -> int:
    try:
        return int(float(value.replace(",", "")))
    except ValueError:
        return 0


def parse_finviz_snapshot_values(cells: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for index in range(0, len(cells) - 1, 2):
        label = " ".join(cells[index].lower().split())
        values[label] = cells[index + 1]
    return values


def _loose_criteria() -> ScannerCriteria:
    return ScannerCriteria("Loose", 0, 0, 0, 0, 0)
