from __future__ import annotations

"""Deterministic adjudication for the read-only midweek overnight replication."""

import hashlib
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo


SCHEMA_VERSION = "OVERNIGHT_MIDWEEK_REPLICATION_V1"
SYMBOLS = ("SPY", "QQQ", "NVDA")
EASTERN = ZoneInfo("America/New_York")
UTC = timezone.utc
FRESH_QUOTE_SECONDS = 120.0
FRESH_CANDLE_SECONDS = 600.0


class OvernightReplicationError(RuntimeError):
    pass


def require_midweek_overnight(observed_at: datetime) -> None:
    observed_at = _aware(observed_at)
    eastern = observed_at.astimezone(EASTERN)
    local_time = eastern.timetz().replace(tzinfo=None)
    session_date = eastern.date() if local_time >= time(20) else (eastern - timedelta(days=1)).date()
    if session_date.weekday() not in (0, 1, 2, 3) or not (
        local_time >= time(20) or local_time < time(4)
    ):
        raise OvernightReplicationError(
            "The replication must run Monday-through-Thursday between 20:00 and 04:00 Eastern."
        )


def adjudicate_schwab(proof: Mapping[str, object] | None) -> dict[str, object]:
    if not proof:
        return _schwab_result("REPLICATION_INCONCLUSIVE", reason="Schwab proof is absent.")
    if tuple(proof.get("symbols", ())) != SYMBOLS:
        return _schwab_result("REPLICATION_INCONCLUSIVE", reason="Schwab symbol identity differs.")
    quotes = _mapping(_mapping(proof.get("quotes")).get("records"))
    stream = _mapping(proof.get("stream"))
    summaries = _mapping(stream.get("summary"))
    history = _mapping(proof.get("priceHistory"))
    quote_ages = _symbol_numbers(quotes, "quoteAgeSeconds")
    stream_ages = _symbol_numbers(summaries, "latestAgeSeconds")
    history_counts = _symbol_ints(history, "barCount")
    stream_current = all(
        symbol in stream_ages and stream_ages[symbol] <= FRESH_CANDLE_SECONDS
        for symbol in SYMBOLS
    )
    quotes_current = all(
        symbol in quote_ages and quote_ages[symbol] <= FRESH_QUOTE_SECONDS
        for symbol in SYMBOLS
    )
    history_current = all(history_counts.get(symbol, 0) > 0 for symbol in SYMBOLS)
    ohlcv_useful = all(
        bool(_mapping(summaries.get(symbol)).get("ohlcvComplete"))
        and float(_mapping(summaries.get(symbol)).get("cumulativeVolume") or 0) > 0
        for symbol in SYMBOLS
    )
    subscription = bool(stream.get("subscriptionAcknowledged"))
    stream_old = bool(stream_ages) and all(
        value > FRESH_CANDLE_SECONDS for value in stream_ages.values()
    )
    quotes_old = bool(quote_ages) and all(
        value > FRESH_QUOTE_SECONDS for value in quote_ages.values()
    )
    history_empty = all(history_counts.get(symbol, 0) == 0 for symbol in SYMBOLS)
    if quotes_current and subscription and stream_current and history_current and ohlcv_useful:
        classification = "SCHWAB_MIDWEEK_OVERNIGHT_CONTEXT_PROVEN"
    elif subscription and quotes_old and stream_old and history_empty:
        classification = "SCHWAB_TRUE_OVERNIGHT_GAP_CONFIRMED"
    else:
        classification = "SCHWAB_MIDWEEK_OVERNIGHT_PARTIAL"
    return _schwab_result(
        classification,
        quote_ages=quote_ages,
        stream_ages=stream_ages,
        history_counts=history_counts,
        quotes_current=quotes_current,
        stream_subscription=subscription,
        stream_current=stream_current,
        history_current=history_current,
        ohlcv_useful=ohlcv_useful,
    )


def adjudicate_alpaca(
    start_proof: Mapping[str, object] | None,
    end_proof: Mapping[str, object] | None,
) -> dict[str, object]:
    if not start_proof or not end_proof:
        return {"classification": "REPLICATION_INCONCLUSIVE", "reason": "Alpaca endpoint proof is absent."}
    start = _alpaca_metrics(start_proof)
    end = _alpaca_metrics(end_proof)
    if not start["derivedQuoteAvailable"] or not end["derivedQuoteAvailable"]:
        classification = "ALPACA_MIDWEEK_FIDELITY_WORSE"
    elif (
        end["maxQuoteAgeSeconds"] is not None
        and end["maxQuoteAgeSeconds"] <= FRESH_QUOTE_SECONDS
        and end["historyBarCount"] > 0
        and (end["maxBarAgeSeconds"] or 0) > FRESH_QUOTE_SECONDS
    ):
        classification = "ALPACA_OVERNIGHT_BEHAVIOR_REPLICATED"
    elif (
        end["maxQuoteAgeSeconds"] is not None
        and end["maxQuoteAgeSeconds"] <= FRESH_QUOTE_SECONDS
        and end["historyBarCount"] > 0
    ):
        classification = "ALPACA_MIDWEEK_FIDELITY_IMPROVED"
    else:
        classification = "ALPACA_MIDWEEK_FIDELITY_WORSE"
    return {"classification": classification, "start": start, "end": end}


def build_comparison(
    *,
    schwab_sunday: Mapping[str, object],
    alpaca_sunday: Mapping[str, object],
    schwab_midweek: Mapping[str, object] | None,
    alpaca_midweek_start: Mapping[str, object] | None,
    alpaca_midweek_end: Mapping[str, object] | None,
    source_identity: Mapping[str, object],
    created_at: datetime,
) -> dict[str, object]:
    schwab = adjudicate_schwab(schwab_midweek)
    alpaca = adjudicate_alpaca(alpaca_midweek_start, alpaca_midweek_end)
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "createdAt": _aware(created_at).isoformat(),
        "symbols": list(SYMBOLS),
        "sourceIdentity": dict(source_identity),
        "sundayBaseline": {
            "schwab": _schwab_summary(schwab_sunday),
            "alpaca": _alpaca_metrics(alpaca_sunday),
        },
        "midweekObservation": {
            "schwab": schwab,
            "alpaca": alpaca,
        },
        "overallClassification": schwab["classification"],
        "providerRole": _provider_role(str(schwab["classification"]), str(alpaca["classification"])),
        "authority": {
            "overnightRanking": "NOT_GRANTED",
            "overnightBreakout": "NOT_GRANTED",
            "overnightTradePlan": "NOT_GRANTED",
            "overnightRiskGovernor": "NOT_GRANTED",
            "overnightOrders": "NOT_GRANTED",
        },
        "safety": {
            "readOnly": True,
            "ordersRequested": False,
            "positionsRequested": False,
            "previewsRequested": False,
            "cancelsRequested": False,
            "replacesRequested": False,
            "shadowInvoked": False,
            "productionPersistence": False,
            "providersBlended": False,
        },
    }
    result["evidenceFingerprint"] = fingerprint(result)
    return result


def render_markdown(comparison: Mapping[str, object]) -> str:
    overall = str(comparison["overallClassification"])
    practical = {
        "SCHWAB_MIDWEEK_OVERNIGHT_CONTEXT_PROVEN": "Schwab's overnight failure WAS just a Sunday-night issue.",
        "SCHWAB_TRUE_OVERNIGHT_GAP_CONFIRMED": "Schwab's overnight failure WAS NOT just a Sunday-night issue.",
        "SCHWAB_MIDWEEK_OVERNIGHT_PARTIAL": "Schwab's overnight behavior was mixed; only some components worked.",
        "REPLICATION_INCONCLUSIVE": "The replication did not produce enough valid evidence to decide.",
    }[overall]
    sunday_schwab = _mapping(_mapping(comparison["sundayBaseline"]).get("schwab"))
    midweek_schwab = _mapping(_mapping(comparison["midweekObservation"]).get("schwab"))
    alpaca = _mapping(_mapping(comparison["midweekObservation"]).get("alpaca"))
    end = _mapping(alpaca.get("end"))
    lines = [
        "# OVERNIGHT-002 Midweek Fidelity Replication",
        "",
        f"> {practical}",
        "",
        f"- Overall classification: `{overall}`",
        f"- Alpaca classification: `{alpaca.get('classification', 'REPLICATION_INCONCLUSIVE')}`",
        f"- Symbols: `{', '.join(comparison['symbols'])}`",
        f"- Provider role: `{comparison['providerRole']}`",
        "- Authority: `CONTEXT / RESEARCH ONLY`; no provider gained trading authority.",
        "",
        "## Sunday Versus Midweek Schwab",
        "",
        "| Evidence | Sunday | Midweek |",
        "| --- | --- | --- |",
        f"| Quote available | {sunday_schwab.get('quoteCount', 0)}/3 | {len(_mapping(midweek_schwab.get('quoteAgesSeconds')))}/3 |",
        f"| Maximum quote age (s) | {sunday_schwab.get('maxQuoteAgeSeconds')} | {_maximum(_mapping(midweek_schwab.get('quoteAgesSeconds')).values())} |",
        f"| Stream subscription | {sunday_schwab.get('streamSubscription')} | {midweek_schwab.get('streamSubscription')} |",
        f"| Current Stream bars | {sunday_schwab.get('currentStreamSymbolCount', 0)}/3 | {sum(1 for value in _mapping(midweek_schwab.get('streamAgesSeconds')).values() if float(value) <= FRESH_CANDLE_SECONDS)}/3 |",
        f"| Price-history bars | {sunday_schwab.get('historyBarCount', 0)} | {sum(int(value) for value in _mapping(midweek_schwab.get('historyBarCounts')).values())} |",
        f"| Useful current session | {sunday_schwab.get('usefulCurrentSession')} | {midweek_schwab.get('classification')} |",
        "",
        "## Alpaca Midweek Control",
        "",
        f"- Fresh derived quotes: `{end.get('derivedQuoteAvailable')}`; max age `{end.get('maxQuoteAgeSeconds')}` seconds.",
        f"- Bounded BOATS history bars: `{end.get('historyBarCount')}`; missing minutes `{end.get('missingMinuteCount')}`.",
        f"- Latest bar age: `{end.get('maxBarAgeSeconds')}` seconds; latest trade age: `{end.get('maxTradeAgeSeconds')}` seconds.",
        "- Direct latest BOATS endpoints were deliberately not requested.",
        "",
        "## Safety",
        "",
        "- Read-only market-data requests only.",
        "- No account, position, order, preview, cancel, replace, Shadow, service, scheduler, WPF, or production-store action.",
        "- Providers were compared, never blended.",
        "",
        f"Evidence fingerprint: `{comparison['evidenceFingerprint']}`",
    ]
    return "\n".join(lines) + "\n"


def write_once(path: Path, payload: bytes) -> str:
    if path.exists():
        raise OvernightReplicationError(f"Write-once output already exists: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest().upper()


def canonical_json(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def fingerprint(value: Mapping[str, object]) -> str:
    payload = dict(value)
    payload.pop("evidenceFingerprint", None)
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest().upper()


def ensure_sanitized(paths: Sequence[Path]) -> None:
    forbidden = (
        b"APCA-API-KEY-ID",
        b"APCA-API-SECRET-KEY",
        b'"access_token"',
        b'"refresh_token"',
        b'"accountHash"',
        b'"customerId"',
        b'"correlationId"',
    )
    for path in paths:
        payload = path.read_bytes()
        if any(marker.lower() in payload.lower() for marker in forbidden):
            raise OvernightReplicationError(f"Sanitization failed for {path.name}.")


def _schwab_result(classification: str, **values: object) -> dict[str, object]:
    return {"classification": classification, **values}


def _schwab_summary(proof: Mapping[str, object]) -> dict[str, object]:
    quotes = _mapping(_mapping(proof.get("quotes")).get("records"))
    stream = _mapping(proof.get("stream"))
    summaries = _mapping(stream.get("summary"))
    history = _mapping(proof.get("priceHistory"))
    quote_ages = _symbol_numbers(quotes, "quoteAgeSeconds")
    stream_ages = _symbol_numbers(summaries, "latestAgeSeconds")
    return {
        "quoteCount": len(quotes),
        "maxQuoteAgeSeconds": _maximum(quote_ages.values()),
        "streamSubscription": bool(stream.get("subscriptionAcknowledged")),
        "currentStreamSymbolCount": sum(value <= FRESH_CANDLE_SECONDS for value in stream_ages.values()),
        "newestStreamBarAgeSeconds": _minimum(stream_ages.values()),
        "historyBarCount": sum(_symbol_ints(history, "barCount").values()),
        "usefulCurrentSession": bool(
            quote_ages and max(quote_ages.values()) <= FRESH_QUOTE_SECONDS
            and stream_ages and max(stream_ages.values()) <= FRESH_CANDLE_SECONDS
            and sum(_symbol_ints(history, "barCount").values()) > 0
        ),
    }


def _alpaca_metrics(proof: Mapping[str, object]) -> dict[str, object]:
    quote_ages: list[float] = []
    bar_ages: list[float] = []
    trade_ages: list[float] = []
    direct_boats_latest = 0
    for request in proof.get("requests", []):
        item = _mapping(request)
        data_type = str(item.get("dataType", ""))
        feed = str(item.get("feed", ""))
        if feed == "boats" and data_type != "historicalBars":
            direct_boats_latest += 1
        if feed != "overnight":
            continue
        records = _mapping(item.get("records"))
        for record in records.values():
            observed = _mapping(record)
            age = observed.get("observedAgeSeconds")
            if not isinstance(age, (int, float)):
                continue
            if "Quote" in data_type or data_type == "latestQuote":
                quote_ages.append(float(age))
            elif "Trade" in data_type or data_type == "latestTrade":
                trade_ages.append(float(age))
            elif "Bar" in data_type or data_type in ("latestBar", "latestBarRepeat"):
                bar_ages.append(float(age))
    histories = _mapping(proof.get("historicalBars"))
    return {
        "derivedQuoteAvailable": bool(quote_ages),
        "maxQuoteAgeSeconds": _maximum(quote_ages),
        "maxBarAgeSeconds": _maximum(bar_ages),
        "maxTradeAgeSeconds": _maximum(trade_ages),
        "historyBarCount": sum(_symbol_ints(histories, "barCount").values()),
        "missingMinuteCount": sum(_symbol_ints(histories, "missingMinuteCount").values()),
        "directLatestBoatsRequestCount": direct_boats_latest,
    }


def _provider_role(schwab: str, alpaca: str) -> str:
    if schwab == "SCHWAB_MIDWEEK_OVERNIGHT_CONTEXT_PROVEN":
        return "SCHWAB_MIDWEEK_OVERNIGHT_CONTEXT_PROVEN; ALPACA_REMAINS_CONTROL_ONLY"
    if schwab == "SCHWAB_TRUE_OVERNIGHT_GAP_CONFIRMED" and alpaca != "ALPACA_MIDWEEK_FIDELITY_WORSE":
        return "TRUE_OVERNIGHT_CONTEXT_ALPACA_DERIVED_RESEARCH_ONLY"
    return "NO_ROLE_CHANGE_PENDING_CLEARER_EVIDENCE"


def _symbol_numbers(values: Mapping[str, object], key: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for symbol in SYMBOLS:
        value = _mapping(values.get(symbol)).get(key)
        if isinstance(value, (int, float)):
            result[symbol] = float(value)
    return result


def _symbol_ints(values: Mapping[str, object], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for symbol in SYMBOLS:
        value = _mapping(values.get(symbol)).get(key)
        if isinstance(value, (int, float)):
            result[symbol] = int(value)
    return result


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _maximum(values: Sequence[float] | object) -> float | None:
    materialized = list(values)  # type: ignore[arg-type]
    return max(materialized) if materialized else None


def _minimum(values: Sequence[float] | object) -> float | None:
    materialized = list(values)  # type: ignore[arg-type]
    return min(materialized) if materialized else None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise OvernightReplicationError("An aware timestamp is required.")
    return value.astimezone(UTC)
