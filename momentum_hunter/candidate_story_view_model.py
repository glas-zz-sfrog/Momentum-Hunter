from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape

from momentum_hunter.replay import TimelineRow


@dataclass(frozen=True)
class CandidateStoryPoint:
    row: TimelineRow
    capture_label: str
    session_marker: str
    price: float | None
    score: float | None
    volume: int | None
    relative_volume: float | None
    price_change_previous_pct: float | None
    price_change_first_pct: float | None
    score_change_previous: float | None
    note: str
    later_annotation: str


@dataclass(frozen=True)
class CandidateStorySummary:
    ticker: str
    company: str
    sector: str
    industry: str
    first_seen_text: str
    latest_seen_text: str
    first_price: float | None
    latest_price: float | None
    move_since_first_pct: float | None
    first_score: float | None
    latest_score: float | None
    peak_score: float | None
    peak_score_text: str
    trusted_capture_count: int
    status: str
    status_detail: str
    points: list[CandidateStoryPoint]
    warnings: list[str]

    @property
    def chartable_price_points(self) -> list[CandidateStoryPoint]:
        return [point for point in self.points if point.price is not None]

    @property
    def chartable_score_points(self) -> list[CandidateStoryPoint]:
        return [point for point in self.points if point.score is not None]


def build_candidate_story_summary(rows: list[TimelineRow]) -> CandidateStorySummary:
    if not rows:
        return CandidateStorySummary(
            ticker="",
            company="",
            sector="",
            industry="",
            first_seen_text="No trusted captures found",
            latest_seen_text="No trusted captures found",
            first_price=None,
            latest_price=None,
            move_since_first_pct=None,
            first_score=None,
            latest_score=None,
            peak_score=None,
            peak_score_text="n/a",
            trusted_capture_count=0,
            status="Insufficient data",
            status_detail="No trusted captures found for this ticker.",
            points=[],
            warnings=["No trusted captures found for this ticker."],
        )

    ordered_rows = sorted(rows, key=lambda row: (row.capture_time or datetime.min, row.session, row.scanner, row.provider))
    first_row = ordered_rows[0]
    latest_row = ordered_rows[-1]
    ticker = first_row.ticker
    company = str(first_row.raw_candidate.get("company", ""))
    sector = str(_timeline_value(latest_row, "sector") or _timeline_value(first_row, "sector") or "")
    industry = str(_timeline_value(latest_row, "industry") or _timeline_value(first_row, "industry") or "")

    first_price = first_non_none(timeline_float(row, "price") for row in ordered_rows)
    latest_price = last_non_none(timeline_float(row, "price") for row in ordered_rows)
    first_score = first_non_none(timeline_float(row, "score") for row in ordered_rows)
    latest_score = last_non_none(timeline_float(row, "score") for row in ordered_rows)
    score_pairs = [(timeline_float(row, "score"), row) for row in ordered_rows]
    score_pairs = [(score, row) for score, row in score_pairs if score is not None]
    peak_score, peak_row = max(score_pairs, key=lambda pair: pair[0]) if score_pairs else (None, None)
    move_since_first = percent_change(first_price, latest_price)
    trusted_count = sum(1 for row in ordered_rows if not row.quarantined)

    points: list[CandidateStoryPoint] = []
    previous_price: float | None = None
    previous_score: float | None = None
    for row in ordered_rows:
        price = timeline_float(row, "price")
        score = timeline_float(row, "score")
        price_change_previous = percent_change(previous_price, price)
        price_change_first = percent_change(first_price, price)
        score_change_previous = None if previous_score is None or score is None else score - previous_score
        note_parts: list[str] = []
        if row is first_row:
            note_parts.append("First seen")
        if peak_row is row and peak_score is not None:
            note_parts.append("Peak score")
        if row is latest_row:
            note_parts.append("Latest capture")
        if timeline_float(row, "relative_volume") is None:
            note_parts.append("Rel Vol unavailable for legacy capture")
        later_parts: list[str] = []
        review_status = str(_timeline_value(row, "review_status") or "")
        outcome_status = str(_timeline_value(row, "outcome_status") or "")
        if review_status and review_status != "unreviewed":
            later_parts.append(f"Later review: {review_status}")
        if outcome_status and outcome_status != "missing":
            later_parts.append(f"Post-capture outcome: {outcome_status}")
        points.append(
            CandidateStoryPoint(
                row=row,
                capture_label=format_story_capture_label(row),
                session_marker=format_story_session_marker(row.session),
                price=price,
                score=score,
                volume=timeline_int(row, "volume"),
                relative_volume=timeline_float(row, "relative_volume"),
                price_change_previous_pct=price_change_previous,
                price_change_first_pct=price_change_first,
                score_change_previous=score_change_previous,
                note=", ".join(note_parts) or "Capture-only trail point",
                later_annotation="; ".join(later_parts) or "No later annotation available yet",
            )
        )
        if price is not None:
            previous_price = price
        if score is not None:
            previous_score = score

    status, status_detail = classify_candidate_story_status(
        point_count=len(points),
        first_price=first_price,
        latest_price=latest_price,
        first_score=first_score,
        latest_score=latest_score,
        peak_score=peak_score,
        peak_row=peak_row,
        latest_row=latest_row,
    )
    warnings: list[str] = []
    if len(points) < 2:
        warnings.append("Only one capture is available; trend status is limited.")
    if first_price is None or latest_price is None:
        warnings.append("Capture trail cannot be charted because stored prices are missing.")
    if any(point.relative_volume is None for point in points):
        warnings.append("Rel Vol unavailable for at least one legacy capture.")
    if any(point.later_annotation == "No later annotation available yet" for point in points):
        warnings.append("Some captures have no later-derived outcome/review annotation yet.")

    return CandidateStorySummary(
        ticker=ticker,
        company=company,
        sector=sector,
        industry=industry,
        first_seen_text=format_story_capture_time(first_row),
        latest_seen_text=format_story_capture_time(latest_row),
        first_price=first_price,
        latest_price=latest_price,
        move_since_first_pct=move_since_first,
        first_score=first_score,
        latest_score=latest_score,
        peak_score=peak_score,
        peak_score_text=format_story_capture_time(peak_row) if peak_row else "n/a",
        trusted_capture_count=trusted_count,
        status=status,
        status_detail=status_detail,
        points=points,
        warnings=warnings,
    )


def classify_candidate_story_status(
    *,
    point_count: int,
    first_price: float | None,
    latest_price: float | None,
    first_score: float | None,
    latest_score: float | None,
    peak_score: float | None,
    peak_row: TimelineRow | None,
    latest_row: TimelineRow,
) -> tuple[str, str]:
    if point_count < 2 or first_price is None or latest_price is None or first_score is None or latest_score is None:
        return "Insufficient data", "More trusted captures are needed before the stock story can be classified."
    move = percent_change(first_price, latest_price)
    score_delta = latest_score - first_score
    cooling_from_peak = peak_score is not None and latest_score <= peak_score - 5
    peak_is_latest = peak_row is latest_row
    if move is not None and move > 3.0 and score_delta > 3.0 and peak_is_latest:
        return "Building", "Price and score are both improving into the latest capture."
    if cooling_from_peak and move is not None and move >= 0:
        return "Holding", "Price remains above first seen level, but score is cooling from its peak."
    if cooling_from_peak and move is not None and move < 0:
        return "Fading", "Score has cooled from peak and price is below the first seen level."
    if peak_score is not None and peak_row is not latest_row and latest_score < peak_score:
        return "Peaked", "The score peak occurred before the latest capture."
    if move is not None and abs(move) <= 2.0:
        return "Stale", "Price has not moved much across trusted captures."
    return "Holding", "The capture trail remains active without a clear acceleration or breakdown."


def first_non_none(values: object) -> object | None:
    for value in values:
        if value is not None:
            return value
    return None


def last_non_none(values: object) -> object | None:
    found = None
    for value in values:
        if value is not None:
            found = value
    return found


def percent_change(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start == 0:
        return None
    return ((end - start) / start) * 100.0


def timeline_float(row: TimelineRow, key: str) -> float | None:
    value = _timeline_value(row, key)
    if value in ("", None, "n/a", "N/A"):
        return None
    try:
        if isinstance(value, str):
            value = value.replace("$", "").replace(",", "").replace("%", "").replace("x", "").strip()
        return float(value)
    except (TypeError, ValueError):
        return None


def timeline_int(row: TimelineRow, key: str) -> int | None:
    value = _timeline_value(row, key)
    if value in ("", None, "n/a", "N/A"):
        return None
    try:
        if isinstance(value, str):
            value = value.replace(",", "").strip()
        return int(float(value))
    except (TypeError, ValueError):
        return None


def format_story_capture_label(row: TimelineRow) -> str:
    if row.capture_time is None:
        return row.capture_date or row.capture_time_text
    return f"{row.capture_time.strftime('%b')} {row.capture_time.day}"


def format_story_capture_time(row: TimelineRow | None) -> str:
    if row is None:
        return "n/a"
    if row.capture_time is None:
        return row.capture_time_text or row.capture_date or "n/a"
    time_text = row.capture_time.strftime("%I:%M %p").lstrip("0")
    return f"{row.capture_time.strftime('%b')} {row.capture_time.day}, {row.capture_time.year} {time_text} CT"


def format_story_session_marker(session: str) -> str:
    mapping = {
        "morning": "AM",
        "evening": "PM",
        "preopen": "PRE",
        "manual": "MAN",
    }
    return mapping.get(str(session).lower(), str(session).upper()[:4] or "CAP")


def format_story_price(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.2f}"


def format_story_score(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}"


def format_story_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


def format_story_score_delta(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.0f}"


def format_compact_volume(value: int | None) -> str:
    if value is None:
        return "n/a"
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs_value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def format_story_rel_vol(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}x"


def format_candidate_story_header_html(summary: CandidateStorySummary) -> str:
    style = "font-family: Segoe UI, Arial; color:#e7edf4; background:#0b1118; font-size:10pt;"
    title_bits = [summary.ticker]
    if summary.company:
        title_bits.append(summary.company)
    subtitle_bits = [bit for bit in [summary.sector, summary.industry] if bit]
    warnings = "".join(f"<li>{escape(warning)}</li>" for warning in summary.warnings)
    warning_block = f"<ul style='margin:4px 0 0 18px; color:#fcd34d;'>{warnings}</ul>" if warnings else ""
    return f"""
    <body style="{style}">
      <h2 style="margin:0 0 4px 0;">{escape(' · '.join(title_bits) or 'Candidate Story')}</h2>
      <p style="margin:0 0 8px 0; color:#9fb0c2;">{escape(' · '.join(subtitle_bits) or 'Sector/industry unavailable')}</p>
      <table cellspacing="0" cellpadding="6" style="width:100%; border-collapse:collapse;">
        <tr>
          <td><b>First seen</b><br>{escape(summary.first_seen_text)}<br>{escape(format_story_price(summary.first_price))}</td>
          <td><b>Latest</b><br>{escape(summary.latest_seen_text)}<br>{escape(format_story_price(summary.latest_price))}</td>
          <td><b>Move since first seen</b><br>{escape(format_story_percent(summary.move_since_first_pct))}</td>
          <td><b>Score</b><br>{escape(format_story_score(summary.first_score))} -> {escape(format_story_score(summary.latest_score))}<br>Peak {escape(format_story_score(summary.peak_score))} on {escape(summary.peak_score_text)}</td>
          <td><b>Trusted captures</b><br>{summary.trusted_capture_count}</td>
          <td><b>Status</b><br>{escape(summary.status)}<br><span style="color:#9fb0c2;">{escape(summary.status_detail)}</span></td>
        </tr>
      </table>
      {warning_block}
      <p style="margin-top:8px; color:#9fb0c2;">Capture-time facts are shown first. Later review/outcome annotations are labeled separately.</p>
    </body>
    """


def format_story_marker_detail(summary: CandidateStorySummary, label: str, index: int) -> str:
    point = summary.points[index]
    if label.startswith("First"):
        return f"{point.capture_label} {point.session_marker} {format_story_price(point.price)}"
    if label.startswith("Peak"):
        return f"{point.capture_label} {point.session_marker} score {format_story_score(point.score)}"
    if label.startswith("Latest"):
        return f"{point.capture_label} {point.session_marker} {format_story_price(point.price)}"
    return f"{point.capture_label} {point.session_marker}"


def story_marker_specs(summary: CandidateStorySummary) -> list[tuple[str, int]]:
    specs: list[tuple[str, int]] = []
    price_indices = [index for index, point in enumerate(summary.points) if point.price is not None]
    if not price_indices:
        return specs
    first_index = price_indices[0]
    latest_index = price_indices[-1]
    specs.append(("First seen", first_index))
    score_indices = [index for index, point in enumerate(summary.points) if point.score is not None and point.price is not None]
    if score_indices:
        peak_index = max(score_indices, key=lambda index: summary.points[index].score or 0)
        if peak_index not in {first_index, latest_index}:
            specs.append(("Peak score", peak_index))
        elif peak_index == latest_index:
            specs.append(("Peak score / latest", peak_index))
    if latest_index != first_index:
        specs.append(("Latest capture", latest_index))
    return specs


def _timeline_value(row: TimelineRow, key: str) -> object:
    value = row.fields.get(key)
    return value.value if value else ""
