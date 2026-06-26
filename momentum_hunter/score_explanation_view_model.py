from __future__ import annotations

import re
from datetime import datetime
from html import escape

from momentum_hunter.models import Candidate
from momentum_hunter.news_age import filter_news_known_at_capture, format_news_age


def format_score_breakdown_html(record: dict, candidate: Candidate | None = None) -> str:
    status = record.get("status", "complete")
    warning = ""
    if status != "complete":
        warning = (
            "<p style='color:#fcd34d;font-weight:700;'>"
            f"{escape(str(status).upper())}: this explanation is marked {escape(str(status))}. "
            "Use it as historical context, not a clean current-engine reconciliation."
            "</p>"
        )
    identity = record.get("identity", {})
    compact_rows = []
    compact_summary = record.get("compact_summary") or compact_score_summary_from_components(record.get("components", []))
    for item in compact_summary:
        contribution = int(item.get("contribution", 0))
        compact_rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('label', '')))}</td>"
            f"<td style='text-align:right;font-weight:700;color:{'#a7f3d0' if contribution >= 0 else '#fecaca'};'>"
            f"{format_signed_points(contribution)}</td>"
            f"<td>{escape(format_raw_inputs(item.get('raw_inputs', {})))}</td>"
            "</tr>"
        )
    component_rows = []
    for component in record.get("components", []):
        contribution = int(component.get("points_after_adjustment", 0))
        explanation = score_component_explanation(component)
        component_rows.append(
            "<tr>"
            f"<td>{escape(str(component.get('label', '')))}</td>"
            f"<td>{escape(str(component.get('category', '')))}</td>"
            f"<td>{escape(format_score_rule(str(component.get('rule', '')), str(component.get('key', ''))))}</td>"
            f"<td>{escape(format_raw_inputs(component.get('raw_inputs', {})))}</td>"
            f"<td style='text-align:right;'>{escape(str(component.get('points_before_adjustment', '')))}</td>"
            f"<td style='text-align:right;font-weight:700;color:{'#a7f3d0' if contribution >= 0 else '#fecaca'};'>"
            f"{escape(format_signed_points(contribution))}</td>"
            f"<td>{escape(explanation)}</td>"
            "</tr>"
        )
    reconciliation = record.get("reconciliation", {})
    caps = record.get("caps", [])
    floors = record.get("floors", [])
    cap = caps[0] if caps else {}
    floor = floors[0] if floors else {}
    return f"""
    <html>
    <head>
      <style>
        body {{ font-family: Segoe UI, Arial; color: #e7edf4; background: #0b1118; }}
        h2 {{ margin-bottom: 4px; }}
        h3 {{ margin-top: 18px; margin-bottom: 8px; color: #bfdbfe; }}
        .meta {{ background: #111b26; border: 1px solid #2f4054; padding: 10px; line-height: 1.45; }}
        pre {{ white-space: pre-wrap; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th {{ background: #182536; color: #dbeafe; border-bottom: 1px solid #3b5168; }}
        td {{ border-bottom: 1px solid #223247; vertical-align: top; }}
        th, td {{ padding: 7px; }}
        tr:nth-child(even) td {{ background: #0f1823; }}
        .points {{ text-align: right; font-weight: 700; white-space: nowrap; }}
      </style>
    </head>
    <body>
      <h2>Why {escape(str(record.get('final_score', '')))}? {escape(str(record.get('ticker', '')))}</h2>
      {warning}
      <p class="meta">
        <b>Captured:</b> {escape(str(identity.get('capture_time', record.get('capture_time', ''))))}<br>
        <b>Session:</b> {escape(str(identity.get('session', '')))} |
        <b>Provider:</b> {escape(str(identity.get('provider', '')))} |
        <b>Scanner:</b> {escape(str(identity.get('scanner', '')))} |
        <b>Mode:</b> {escape(str(identity.get('mode', '')))} |
        <b>Profile:</b> {escape(str(record.get('score_profile', '')))} |
        <b>Regime:</b> {escape(str(record.get('score_regime', '')))}<br>
        <b>Scoring Version:</b> {escape(str(record.get('score_engine_version', '')))} |
        <b>Schema:</b> {escape(str(record.get('explanation_schema_version', '')))}
      </p>
      <h3>Reconciliation</h3>
      <pre style="background:#111b26;padding:10px;border:1px solid #2f4054;">
Base component subtotal: {escape(str(record.get('subtotal_before_global_adjustments', '')))}
Floor applied: {escape(str(floor.get('applied', False)))} | Floor output: {escape(str(floor.get('output', '')))}
Pre-cap total: {escape(str(record.get('pre_cap_total', '')))}
Global cap applied: {escape(str(cap.get('applied', False)))} | Cap output: {escape(str(cap.get('output', '')))}
Computed final score: {escape(str(record.get('computed_final_score', '')))}
Displayed final score: {escape(str(record.get('final_score', '')))}
Reconciliation status: {escape(str(reconciliation.get('status', record.get('reconciliation_status', ''))))}
      </pre>
      <h3>Compact Summary</h3>
      <p class="meta">
        Contributions are the points actually counted by <b>momentum_score_v1</b>. Context rows can show important
        information, such as HOT freshness, while still contributing 0 points when the current scoring engine is
        measurement-only for that signal.
      </p>
      {latest_article_context_html(candidate, identity.get('capture_time', record.get('capture_time', '')))}
      <table cellspacing="0" cellpadding="6">
        <tr>
          <th align="left">Component</th>
          <th align="right">Contribution</th>
          <th align="left">Raw Value</th>
        </tr>
        {''.join(compact_rows)}
      </table>
      <h3>Detailed Components</h3>
      <p class="meta">
        <b>Base Points</b> are the rule result before local/regime adjustments. <b>Applied Impact</b> is what actually
        contributes to the subtotal before global floor/cap handling.
      </p>
      <table cellspacing="0" cellpadding="6">
        <tr>
          <th align="left">Component</th>
          <th align="left">Type</th>
          <th align="left">Rule</th>
          <th align="left">Raw Inputs</th>
          <th align="right">Base Points</th>
          <th align="right">Applied Impact</th>
          <th align="left">Explanation</th>
        </tr>
        {''.join(component_rows)}
      </table>
    </body>
    </html>
    """


def compact_score_summary_from_components(components: list[dict]) -> list[dict]:
    groups = [
        ("base_score", "Base"),
        ("volume", "Volume"),
        ("relative_volume", "Relative Volume"),
        ("market_cap", "Market Cap"),
        ("price_momentum", "Price Move"),
        ("positive_catalyst.", "Catalyst"),
        ("freshness_context", "Freshness"),
        ("risk_term.", "Risk Penalty"),
        ("low_price", "Price Risk"),
    ]
    summary: list[dict] = []
    for key_prefix, label in groups:
        matching = [
            component
            for component in components
            if str(component.get("key", "")) == key_prefix or str(component.get("key", "")).startswith(key_prefix)
        ]
        if matching:
            summary.append(
                {
                    "label": label,
                    "contribution": sum(int(component.get("points_after_adjustment", 0)) for component in matching),
                    "raw_inputs": {
                        key: value
                        for component in matching
                        for key, value in (component.get("raw_inputs", {}) if isinstance(component.get("raw_inputs"), dict) else {}).items()
                    },
                }
            )
    return summary


def format_signed_points(value: int) -> str:
    if value > 0:
        return f"+{value}"
    return str(value)


def format_raw_inputs(raw_inputs: dict) -> str:
    if not isinstance(raw_inputs, dict):
        return str(raw_inputs)
    return "; ".join(f"{humanize_score_key(key)}={format_score_value(key, value)}" for key, value in raw_inputs.items())


def humanize_score_key(key: object) -> str:
    return str(key).replace("_", " ").title()


def format_score_value(key: object, value: object) -> str:
    key_text = str(key).lower()
    if value is None:
        return "unknown"
    if key_text == "market_cap":
        return _format_market_cap(_int_or_zero(value))
    if "volume" in key_text and "relative" not in key_text:
        return format_compact_number(value)
    if "relative_volume" in key_text:
        try:
            return f"{float(value):.2f}x"
        except (TypeError, ValueError):
            return str(value)
    if "percent" in key_text or key_text in {"change", "percent_change"}:
        try:
            return f"{float(value):.1f}%"
        except (TypeError, ValueError):
            return str(value)
    if key_text == "freshness_score":
        return str(value)
    return str(value)


def format_compact_number(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    absolute = abs(number)
    if absolute >= 1_000_000_000:
        return f"{number / 1_000_000_000:.1f}B"
    if absolute >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"{number / 1_000:.1f}K"
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}"


def format_score_rule(rule: str, component_key: str) -> str:
    if not rule:
        return ""

    def replace_number(match: re.Match[str]) -> str:
        raw = match.group(0)
        value = int(raw.replace(",", ""))
        if component_key == "market_cap":
            return _format_market_cap(value)
        if component_key == "volume":
            return format_compact_number(value)
        return raw

    return re.sub(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?![\w.])", replace_number, rule)


def score_component_explanation(component: dict) -> str:
    explanation = str(component.get("explanation", ""))
    if component.get("key") == "freshness_context":
        context_note = (
            "Freshness is recorded for research/explainability only in momentum_score_v1, "
            "so HOT/high freshness can still have Applied Impact 0."
        )
        return f"{explanation} {context_note}".strip()
    return explanation


def latest_article_context_html(candidate: Candidate | None, capture_time_text: object) -> str:
    if candidate is None:
        return ""
    capture_time = parse_iso_datetime(str(capture_time_text))
    known_news = filter_news_known_at_capture(candidate.news, capture_time)
    valid_news = [item for item in known_news if item.published_at is not None]
    if not valid_news:
        return "<p class='meta'><b>Latest valid article:</b> unavailable in the stored candidate context.</p>"
    latest = max(valid_news, key=lambda item: article_time_for_display(item.published_at, capture_time) or datetime.min)
    age = "unknown"
    latest_published_at = article_time_for_display(latest.published_at, capture_time)
    if capture_time and latest_published_at:
        age_hours = max(0.0, (capture_time - latest_published_at).total_seconds() / 3600)
        age = format_news_age(age_hours)
    source = latest.source or "unknown source"
    return (
        "<p class='meta'>"
        f"<b>Latest valid article:</b> {escape(latest.headline)}<br>"
        f"<b>Source:</b> {escape(source)} | <b>Age at capture:</b> {escape(age)}"
        "</p>"
    )


def article_time_for_display(value: datetime | None, capture_time: datetime | None) -> datetime | None:
    if value is None:
        return None
    if capture_time is None or capture_time.tzinfo is None:
        return value.replace(tzinfo=None)
    if value.tzinfo is None:
        return value.replace(tzinfo=capture_time.tzinfo)
    return value.astimezone(capture_time.tzinfo)


def parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _format_market_cap(value: int) -> str:
    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.1f}T"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    return f"${value:,}"


def _int_or_zero(value: object) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
