from __future__ import annotations

"""Fingerprint and run one bounded, read-only Schwab true-overnight probe."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, time as wall_time, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

PROJECT_IMPORT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_IMPORT_ROOT))

from momentum_hunter.schwab_candle_contract import (
    SCHWAB_CHART_EQUITY_SERVICE,
    SCHWAB_PRICE_HISTORY_URL,
    SCHWAB_USER_PREFERENCE_URL,
    build_chart_equity_subscription,
    build_price_history_parameters,
    parse_chart_equity_messages,
    parse_price_history_response,
)
from momentum_hunter.schwab_candle_observer import (
    WebSocketClientFactory,
    build_streamer_login,
    parse_streamer_bootstrap,
    require_streamer_acknowledgement,
)
from momentum_hunter.schwab_market_data import (
    SCHWAB_QUOTES_URL,
    SchwabReadOnlyAccessTokenProvider,
)
from momentum_hunter.schwab_onboarding import SchwabOAuthSecretRepository


TASK_ID = "ARGUS-SCHWAB-OVERNIGHT-API-PROBE-001"
SCHEMA_VERSION = 1
SYMBOLS = ("SPY", "QQQ", "NVDA", "AAPL", "MU")
STREAM_SYMBOLS = ("SPY", "QQQ", "NVDA")
EXPECTED_ACCOUNT_ENDING = "2573"
LEVELONE_SERVICE = "LEVELONE_EQUITIES"
LEVELONE_FIELDS = ",".join(str(index) for index in range(52))
EASTERN = ZoneInfo("America/New_York")
CENTRAL = ZoneInfo("America/Chicago")
UTC = timezone.utc
MIN_DURATION_SECONDS = 600
MAX_DURATION_SECONDS = 1_200
DEFAULT_DURATION_SECONDS = 900
DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_STREAM_SECONDS = 600
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
HTTP_TIMEOUT = (5.0, 30.0)
AUTH_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
ALLOWED_HTTP_ROUTES = (
    ("GET", SCHWAB_QUOTES_URL, "MARKET_DATA_QUOTES"),
    ("GET", SCHWAB_PRICE_HISTORY_URL, "MARKET_DATA_PRICE_HISTORY"),
    ("GET", SCHWAB_USER_PREFERENCE_URL, "STREAMER_BOOTSTRAP"),
    ("POST", AUTH_TOKEN_URL, "OAUTH_REFRESH_IF_REQUIRED"),
)
FORBIDDEN_ROUTE_FRAGMENTS = (
    "/accounts",
    "/positions",
    "/orders",
    "/preview",
    "alpaca",
)
QUOTE_FIELDS = (
    "askPrice",
    "askSize",
    "askTime",
    "bidPrice",
    "bidSize",
    "bidTime",
    "lastPrice",
    "lastSize",
    "mark",
    "netChange",
    "netPercentChange",
    "postMarketChange",
    "postMarketPercentChange",
    "quoteTime",
    "securityStatus",
    "totalVolume",
    "tradeTime",
)
EXTENDED_FIELDS = (
    "askPrice",
    "askSize",
    "bidPrice",
    "bidSize",
    "lastPrice",
    "mark",
    "quoteTime",
    "totalVolume",
    "tradeTime",
)
REGULAR_FIELDS = (
    "regularMarketLastPrice",
    "regularMarketLastSize",
    "regularMarketNetChange",
    "regularMarketPercentChange",
    "regularMarketTradeTime",
)
TIMESTAMP_FIELDS = frozenset(
    {"askTime", "bidTime", "quoteTime", "tradeTime", "regularMarketTradeTime"}
)


class ProbeError(RuntimeError):
    pass


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest().upper()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProbeError("Probe timestamps must include a UTC offset.")
    return value.astimezone(UTC)


def overnight_window(observed_at: datetime) -> tuple[datetime, datetime]:
    eastern = aware(observed_at).astimezone(EASTERN)
    local = eastern.time().replace(tzinfo=None)
    if local >= wall_time(20, 0):
        start = eastern.replace(hour=20, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=8)
    else:
        end = eastern.replace(hour=4, minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=8)
    return start.astimezone(UTC), end.astimezone(UTC)


def require_true_overnight(observed_at: datetime) -> tuple[datetime, datetime]:
    start, end = overnight_window(observed_at)
    if not start <= aware(observed_at) < end:
        raise ProbeError("Live execution requires the 20:00-04:00 ET overnight session.")
    return start, end


def epoch_timestamp(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
    try:
        return datetime.fromtimestamp(seconds, tz=UTC).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _safe_market_fields(value: object, allowed: Sequence[str]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {"available": False, "availableFields": []}
    evidence: dict[str, object] = {
        "available": True,
        "availableFields": sorted(str(key) for key in value),
    }
    for key in allowed:
        if key not in value:
            continue
        raw = value[key]
        evidence[key] = epoch_timestamp(raw) if key in TIMESTAMP_FIELDS else raw
    return evidence


def quote_record(
    payload: object,
    symbol: str,
    *,
    requested_at: datetime,
    received_at: datetime,
) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise ProbeError("Quote response was not an object.")
    row = payload.get(symbol)
    if not isinstance(row, Mapping):
        return {
            "symbol": symbol,
            "status": "NOT_RETURNED",
            "requestTime": aware(requested_at).isoformat(),
            "responseTime": aware(received_at).isoformat(),
        }
    if str(row.get("symbol", "")).strip().upper() != symbol:
        raise ProbeError(f"Quote response identity did not match {symbol}.")
    quote = _safe_market_fields(row.get("quote"), QUOTE_FIELDS)
    extended = _safe_market_fields(row.get("extended"), EXTENDED_FIELDS)
    regular = _safe_market_fields(row.get("regular"), REGULAR_FIELDS)
    timestamps = [
        datetime.fromisoformat(str(value))
        for container in (quote, extended, regular)
        for key, value in container.items()
        if key in TIMESTAMP_FIELDS and isinstance(value, str)
    ]
    newest = max(timestamps).astimezone(UTC).isoformat() if timestamps else None
    return {
        "symbol": symbol,
        "status": "RETURNED",
        "requestTime": aware(requested_at).isoformat(),
        "responseTime": aware(received_at).isoformat(),
        "realtime": row.get("realtime") is True,
        "assetMainType": str(row.get("assetMainType", "")),
        "quote": quote,
        "extended": extended,
        "regular": regular,
        "newestProviderTimestamp": newest,
    }


def classify_quote_timeline(
    rows: Sequence[Mapping[str, object]],
    *,
    overnight_start: datetime,
) -> dict[str, object]:
    timestamps = [
        datetime.fromisoformat(str(row["newestProviderTimestamp"])).astimezone(UTC)
        for row in rows
        if row.get("newestProviderTimestamp")
    ]
    changes = 0
    for previous, current in zip(rows, rows[1:]):
        before = (previous.get("quote"), previous.get("extended"), previous.get("regular"))
        after = (current.get("quote"), current.get("extended"), current.get("regular"))
        changes += before != after
    advances = sum(current > previous for previous, current in zip(timestamps, timestamps[1:]))
    newest = max(timestamps) if timestamps else None
    last_receipt = (
        datetime.fromisoformat(str(rows[-1]["responseTime"])).astimezone(UTC)
        if rows
        else datetime.now(UTC)
    )
    if newest is None:
        classification = "NO_OVERNIGHT_DATA"
    elif newest <= overnight_start:
        classification = "STALE_FROM_AFTER_HOURS"
    elif (last_receipt - newest).total_seconds() <= 300:
        classification = "TRUE_OVERNIGHT_FRESH"
    else:
        classification = "TRUE_OVERNIGHT_DELAYED"
    return {
        "firstProviderTimestamp": timestamps[0].isoformat() if timestamps else None,
        "lastProviderTimestamp": timestamps[-1].isoformat() if timestamps else None,
        "newestProviderTimestamp": newest.isoformat() if newest else None,
        "timestampAdvances": advances,
        "quoteFieldChanges": changes,
        "observationCount": len(rows),
        "classification": classification,
    }


def history_summary(
    candles: Sequence[object],
    *,
    overnight_start: datetime,
    observed_at: datetime,
) -> dict[str, object]:
    timestamps = sorted(aware(candle.timestamp) for candle in candles)
    start_et = overnight_start.astimezone(EASTERN)
    midnight_et = (start_et + timedelta(days=1)).replace(hour=0)
    one_am_et = start_et.replace(hour=21)
    observed_et = aware(observed_at).astimezone(EASTERN)
    counts = {
        "20:00-21:00_ET": sum(start_et < ts.astimezone(EASTERN) < one_am_et for ts in timestamps),
        "21:00-00:00_ET": sum(one_am_et <= ts.astimezone(EASTERN) < midnight_et for ts in timestamps),
        "00:00-current_ET": sum(midnight_et <= ts.astimezone(EASTERN) <= observed_et for ts in timestamps),
    }
    post_20 = [ts for ts in timestamps if ts > overnight_start]
    after_midnight = [ts for ts in timestamps if ts.astimezone(EASTERN) >= midnight_et]
    if after_midnight:
        classification = "OVERNIGHT_HISTORY_PRESENT"
    elif post_20:
        classification = "PARTIAL_OVERNIGHT_HISTORY"
    elif timestamps and timestamps[-1].astimezone(EASTERN).time() >= wall_time(19, 59):
        classification = "HISTORY_STOPS_AT_20_ET"
    elif timestamps:
        classification = "HISTORY_STOPS_BEFORE_20_ET"
    else:
        classification = "NO_MINUTE_HISTORY"
    return {
        "barCount": len(timestamps),
        "earliestReturnedMinute": timestamps[0].isoformat() if timestamps else None,
        "latestReturnedMinute": timestamps[-1].isoformat() if timestamps else None,
        "barsAfter20Et": len(post_20),
        "barsAfterMidnightEt": len(after_midnight),
        "windowCounts": counts,
        "classification": classification,
    }


class RecordingSession(requests.Session):
    def __init__(self, clock: Callable[[], datetime]) -> None:
        super().__init__()
        self.trust_env = False
        self.clock = clock
        self.inventory: list[dict[str, object]] = []

    def request(self, method: str, url: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        normalized_method = method.upper()
        clean_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}{urlparse(url).path}"
        allowed = any(
            normalized_method == expected_method and clean_url == expected_url
            for expected_method, expected_url, _ in ALLOWED_HTTP_ROUTES
        )
        if not allowed or any(fragment in clean_url.lower() for fragment in FORBIDDEN_ROUTE_FRAGMENTS):
            raise ProbeError("Probe refused a route outside the read-only allowlist.")
        started = aware(self.clock())
        response = super().request(method, url, *args, **kwargs)
        ended = aware(self.clock())
        route_class = next(
            name
            for expected_method, expected_url, name in ALLOWED_HTTP_ROUTES
            if normalized_method == expected_method and clean_url == expected_url
        )
        self.inventory.append(
            {
                "method": normalized_method,
                "host": urlparse(clean_url).hostname,
                "path": urlparse(clean_url).path,
                "requestClass": route_class,
                "startedAt": started.isoformat(),
                "completedAt": ended.isoformat(),
                "httpStatus": response.status_code,
            }
        )
        return response


class ProbeClient:
    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        self.clock = clock
        self.secrets = SchwabOAuthSecretRepository()
        self.token_provider = SchwabReadOnlyAccessTokenProvider(
            secrets_repository=self.secrets,
        )
        self.session = RecordingSession(clock)
        self.access_token = self.token_provider.access_token()

    def get_json(self, url: str, *, params: Mapping[str, object] | None = None) -> object:
        for attempt in range(2):
            response = self.session.get(
                url,
                params=params,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.access_token}",
                    "Cache-Control": "no-store",
                },
                timeout=HTTP_TIMEOUT,
                allow_redirects=False,
            )
            if response.status_code == 401 and attempt == 0:
                self.access_token = self.token_provider.refresh_after_rejection(
                    rejected_access_token=self.access_token,
                )
                continue
            if response.is_redirect or response.status_code != 200:
                raise ProbeError(f"Schwab GET failed safely with HTTP {response.status_code}.")
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise ProbeError("Schwab response exceeded the probe size limit.")
            try:
                return response.json()
            except ValueError as exc:
                raise ProbeError("Schwab response was not valid JSON.") from exc
        raise ProbeError("Schwab authorization retry was exhausted.")


def build_levelone_subscription(bootstrap: object) -> dict[str, object]:
    return {
        "requests": [
            {
                "service": LEVELONE_SERVICE,
                "command": "SUBS",
                "requestid": "1",
                "SchwabClientCustomerId": bootstrap.customer_id,
                "SchwabClientCorrelId": bootstrap.correlation_id,
                "parameters": {
                    "keys": ",".join(STREAM_SYMBOLS),
                    "fields": LEVELONE_FIELDS,
                },
            }
        ]
    }


def receive_ack(stream: object, *, service: str, request_id: str) -> list[object]:
    buffered: list[object] = []
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        payload = stream.receive_json(max(0.1, min(2.0, deadline - time.monotonic())))
        if payload is None:
            continue
        try:
            require_streamer_acknowledgement(
                payload,
                service=service,
                command="LOGIN" if service == "ADMIN" else "SUBS",
                request_id=request_id,
            )
            return buffered
        except Exception:
            if isinstance(payload, Mapping) and ("data" in payload or "notify" in payload):
                buffered.append(payload)
                continue
            raise
    raise ProbeError(f"Streamer acknowledgement timed out for {service}.")


def summarize_stream_frames(
    frames: Sequence[tuple[datetime, object]],
) -> dict[str, object]:
    service_counts = {LEVELONE_SERVICE: 0, SCHWAB_CHART_EQUITY_SERVICE: 0}
    latest_envelope: dict[str, datetime] = {}
    levelone_symbols: set[str] = set()
    chart_frames: list[object] = []
    chart_receipts: list[datetime] = []
    for receipt, payload in frames:
        if not isinstance(payload, Mapping):
            continue
        for row in payload.get("data", []) if isinstance(payload.get("data"), list) else []:
            if not isinstance(row, Mapping):
                continue
            service = str(row.get("service", ""))
            if service not in service_counts:
                continue
            service_counts[service] += 1
            envelope = epoch_timestamp(row.get("timestamp"))
            if envelope:
                parsed = datetime.fromisoformat(envelope).astimezone(UTC)
                latest_envelope[service] = max(latest_envelope.get(service, parsed), parsed)
            if service == LEVELONE_SERVICE:
                content = row.get("content")
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, Mapping):
                            symbol = str(item.get("key", item.get("0", ""))).upper()
                            if symbol in STREAM_SYMBOLS:
                                levelone_symbols.add(symbol)
            else:
                chart_frames.append({"data": [row]})
                chart_receipts.append(receipt)
    chart_rows: list[dict[str, object]] = []
    if chart_frames:
        observations = parse_chart_equity_messages(
            chart_frames,
            expected_symbols=STREAM_SYMBOLS,
            received_at_by_payload=chart_receipts,
        )
        chart_rows = [observation.to_evidence() for observation in observations]
    latest_chart = max(
        (
            datetime.fromisoformat(str(row["candle"]["timestamp"])).astimezone(UTC)
            for row in chart_rows
        ),
        default=None,
    )
    return {
        "levelOne": {
            "service": LEVELONE_SERVICE,
            "frameCount": service_counts[LEVELONE_SERVICE],
            "symbolsObserved": sorted(levelone_symbols),
            "latestEnvelopeTimestamp": latest_envelope.get(LEVELONE_SERVICE).isoformat()
            if LEVELONE_SERVICE in latest_envelope
            else None,
            "fieldSemantics": "UNPROVEN_NO_CANONICAL_LEVELONE_FIELD_MAP",
        },
        "chartEquity": {
            "service": SCHWAB_CHART_EQUITY_SERVICE,
            "frameCount": service_counts[SCHWAB_CHART_EQUITY_SERVICE],
            "observationCount": len(chart_rows),
            "latestEnvelopeTimestamp": latest_envelope.get(SCHWAB_CHART_EQUITY_SERVICE).isoformat()
            if SCHWAB_CHART_EQUITY_SERVICE in latest_envelope
            else None,
            "latestCandleTimestamp": latest_chart.isoformat() if latest_chart else None,
            "observations": chart_rows,
        },
    }


def auth_metadata(repository: SchwabOAuthSecretRepository) -> dict[str, object]:
    path = repository.store.path
    result: dict[str, object] = {
        "credentialSlotId": fingerprint(
            {"provider": "SCHWAB", "store": str(path.resolve()).lower()}
        ),
        "authStateExists": path.is_file(),
        "authStateFingerprint": sha256_file(path) if path.is_file() else None,
        "authStateLastModified": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
        if path.is_file()
        else None,
        "refreshLockState": "PRESENT" if path.with_name(f"{path.name}.refresh.lock").exists() else "ABSENT",
    }
    if path.is_file():
        tokens = repository.load_tokens()
        remaining = (tokens.expires_at - datetime.now(UTC)).total_seconds()
        result["accessTokenFreshnessCategory"] = (
            "EXPIRED" if remaining <= 0 else "LT_15_MIN" if remaining < 900 else "ACTIVE"
        )
        result["refreshStateAvailability"] = "AVAILABLE" if tokens.refresh_token else "MISSING"
    return result


def git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def source_identity(root: Path, script: Path) -> dict[str, object]:
    sources = (
        script,
        root / "momentum_hunter" / "schwab_market_data.py",
        root / "momentum_hunter" / "schwab_auth_lock.py",
        root / "momentum_hunter" / "schwab_onboarding.py",
        root / "momentum_hunter" / "schwab_candle_contract.py",
        root / "momentum_hunter" / "schwab_candle_observer.py",
    )
    manifest = [
        {"path": str(path.relative_to(root)).replace("\\", "/"), "sha256": sha256_file(path)}
        for path in sources
    ]
    return {
        "fullGitSha": git_output(root, "rev-parse", "HEAD"),
        "originMasterSha": git_output(root, "rev-parse", "origin/master"),
        "probeSourceSha256": sha256_file(script),
        "sourceManifest": manifest,
        "sourceManifestSha256": fingerprint(manifest),
    }


def runtime_identity() -> dict[str, object]:
    import websocket

    executable = Path(sys.executable).resolve()
    return {
        "pythonExecutable": str(executable),
        "pythonExecutableSha256": sha256_file(executable),
        "pythonVersion": platform.python_version(),
        "requestsVersion": requests.__version__,
        "websocketClientVersion": str(websocket.__version__),
    }


def write_json_once(path: Path, value: Mapping[str, object]) -> str:
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()


def run_probe(
    *,
    project_root: Path,
    output_root: Path,
    duration_seconds: int,
    interval_seconds: int,
    stream_seconds: int,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    if not MIN_DURATION_SECONDS <= duration_seconds <= MAX_DURATION_SECONDS:
        raise ProbeError("Probe duration is outside the bounded range.")
    if interval_seconds < 55 or interval_seconds > 90:
        raise ProbeError("Quote interval must remain approximately 60 seconds.")
    if stream_seconds < 0 or stream_seconds > duration_seconds:
        raise ProbeError("Streamer duration is outside the quote window.")
    if output_root.exists():
        raise ProbeError("Immutable probe root already exists.")

    started = aware(clock())
    overnight_start, overnight_end = require_true_overnight(started)
    script = Path(__file__).resolve()
    sources = source_identity(project_root, script)
    if sources["fullGitSha"] != sources["originMasterSha"]:
        # The probe source may be one clean task commit ahead of origin/master only.
        parents = git_output(project_root, "rev-list", "--parents", "-n", "1", "HEAD").split()
        if len(parents) != 2 or parents[1] != sources["originMasterSha"]:
            raise ProbeError("Probe Git identity is not one clean task commit above origin/master.")
    if git_output(project_root, "status", "--porcelain"):
        raise ProbeError("Probe worktree must be clean before provider contact.")

    route_manifest = [
        {"method": method, "host": urlparse(url).hostname, "path": urlparse(url).path, "requestClass": name}
        for method, url, name in ALLOWED_HTTP_ROUTES
    ] + [
        {"method": "WSS", "host": "streamer-api.schwab.com", "path": "/ws", "requestClass": "READ_ONLY_STREAMER"}
    ]
    configuration = {
        "taskId": TASK_ID,
        "symbols": list(SYMBOLS),
        "streamSymbols": list(STREAM_SYMBOLS),
        "durationSeconds": duration_seconds,
        "intervalSeconds": interval_seconds,
        "streamSeconds": stream_seconds,
        "routeAllowlistSha256": fingerprint(route_manifest),
        "evidenceRoot": str(output_root.resolve()),
    }
    client = ProbeClient(clock=clock)
    auth_before = auth_metadata(client.secrets)
    baseline = {
        "schemaVersion": SCHEMA_VERSION,
        "taskId": TASK_ID,
        "probeStartTimestamp": started.isoformat(),
        "probeStartCentral": started.astimezone(CENTRAL).isoformat(),
        "probeStartEastern": started.astimezone(EASTERN).isoformat(),
        "trueOvernightSession": True,
        "overnightStart": overnight_start.isoformat(),
        "overnightEnd": overnight_end.isoformat(),
        "sourceIdentity": sources,
        "configuration": configuration,
        "configurationFingerprint": fingerprint(configuration),
        "pythonIdentity": runtime_identity(),
        "routeAllowlist": route_manifest,
        "authState": auth_before,
        "campaignNonmutationBaseline": {
            "canonicalGitSha": sources["originMasterSha"],
            "installedProductGitSha": json.loads(
                Path("C:/ProgramData/MomentumHunter/Automation/continuous-deployment-manifest.json").read_text(encoding="utf-8")
            )["canonicalHead"],
            "automationManifestSha256": sha256_file(Path("C:/ProgramData/MomentumHunter/Automation/automation-manifest.json")),
            "continuousConfigSha256": sha256_file(Path("C:/ProgramData/MomentumHunter/Automation/continuous-deployment.json")),
            "continuousDeploymentManifestSha256": sha256_file(Path("C:/ProgramData/MomentumHunter/Automation/continuous-deployment-manifest.json")),
        },
    }
    baseline["baselineFingerprint"] = fingerprint(baseline)
    write_json_once(output_root / "provenance-baseline.json", baseline)

    quote_observations: list[dict[str, object]] = []
    stream_frames: list[tuple[datetime, object]] = []
    stream_result: dict[str, object] = {"attempted": stream_seconds > 0}
    stream = None
    stream_started_monotonic: float | None = None
    if stream_seconds > 0:
        try:
            bootstrap_payload = client.get_json(SCHWAB_USER_PREFERENCE_URL)
            bootstrap = parse_streamer_bootstrap(
                bootstrap_payload,
                expected_account_ending=EXPECTED_ACCOUNT_ENDING,
            )
            stream = WebSocketClientFactory().connect(bootstrap.socket_url)
            stream.send_json(build_streamer_login(client.access_token, bootstrap))
            for payload in receive_ack(stream, service="ADMIN", request_id="0"):
                stream_frames.append((aware(clock()), payload))
            stream.send_json(build_levelone_subscription(bootstrap))
            for payload in receive_ack(stream, service=LEVELONE_SERVICE, request_id="1"):
                stream_frames.append((aware(clock()), payload))
            chart = build_chart_equity_subscription(
                STREAM_SYMBOLS,
                customer_id=bootstrap.customer_id,
                correlation_id=bootstrap.correlation_id,
                request_id="2",
            )
            stream.send_json(chart)
            for payload in receive_ack(stream, service=SCHWAB_CHART_EQUITY_SERVICE, request_id="2"):
                stream_frames.append((aware(clock()), payload))
            stream_started_monotonic = time.monotonic()
            stream_result.update(
                {
                    "connection": "PASS",
                    "authentication": "PASS",
                    "levelOneSubscription": "ACKNOWLEDGED",
                    "chartEquitySubscription": "ACKNOWLEDGED",
                    "bootstrapAccountEnding": EXPECTED_ACCOUNT_ENDING,
                    "rawAccountIdentityIncluded": False,
                }
            )
        except Exception as exc:
            stream_result.update(
                {
                    "connection": "FAIL",
                    "failure": f"{type(exc).__name__}: {exc}",
                }
            )
            if stream is not None:
                stream.close()
                stream = None

    started_monotonic = time.monotonic()
    next_quote = started_monotonic
    while True:
        elapsed = time.monotonic() - started_monotonic
        if elapsed >= duration_seconds:
            break
        if time.monotonic() >= next_quote:
            requested = aware(clock())
            payload = client.get_json(
                SCHWAB_QUOTES_URL,
                params={"symbols": ",".join(SYMBOLS), "fields": "quote"},
            )
            received = aware(clock())
            quote_observations.append(
                {
                    "sequence": len(quote_observations) + 1,
                    "requestedAt": requested.isoformat(),
                    "receivedAt": received.isoformat(),
                    "records": {
                        symbol: quote_record(
                            payload,
                            symbol,
                            requested_at=requested,
                            received_at=received,
                        )
                        for symbol in SYMBOLS
                    },
                }
            )
            next_quote = started_monotonic + len(quote_observations) * interval_seconds
        stream_active = (
            stream is not None
            and stream_started_monotonic is not None
            and time.monotonic() - stream_started_monotonic < stream_seconds
        )
        if stream_active:
            payload = stream.receive_json(
                max(0.1, min(5.0, next_quote - time.monotonic(), duration_seconds - elapsed))
            )
            if payload is not None:
                stream_frames.append((aware(clock()), payload))
        else:
            if stream is not None:
                stream.close()
                stream = None
            time.sleep(max(0.05, min(1.0, next_quote - time.monotonic(), duration_seconds - elapsed)))
    if stream is not None:
        stream.close()

    completed = aware(clock())
    histories: dict[str, object] = {}
    for symbol in SYMBOLS:
        requested = aware(clock())
        payload = client.get_json(
            SCHWAB_PRICE_HISTORY_URL,
            params=build_price_history_parameters(
                symbol,
                start_at=overnight_start - timedelta(minutes=5),
                end_at=completed + timedelta(minutes=1),
                extended_hours=True,
            ),
        )
        received = aware(clock())
        candles = parse_price_history_response(payload, expected_symbol=symbol)
        histories[symbol] = {
            "requestTime": requested.isoformat(),
            "responseTime": received.isoformat(),
            **history_summary(
                candles,
                overnight_start=overnight_start,
                observed_at=completed,
            ),
        }

    quote_timeline = {
        symbol: classify_quote_timeline(
            [observation["records"][symbol] for observation in quote_observations],
            overnight_start=overnight_start,
        )
        for symbol in SYMBOLS
    }
    stream_result.update(summarize_stream_frames(stream_frames))
    auth_after = auth_metadata(client.secrets)
    auth_metrics = client.token_provider.metrics_snapshot()
    result: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "taskId": TASK_ID,
        "mode": "READ_ONLY_TRUE_OVERNIGHT_CAPABILITY_PROBE",
        "observationWindow": {
            "startedAt": started.isoformat(),
            "completedAt": completed.isoformat(),
            "startedCentral": started.astimezone(CENTRAL).isoformat(),
            "completedCentral": completed.astimezone(CENTRAL).isoformat(),
            "startedEastern": started.astimezone(EASTERN).isoformat(),
            "completedEastern": completed.astimezone(EASTERN).isoformat(),
            "trueOvernightSession": True,
        },
        "provenanceBaselineFingerprint": baseline["baselineFingerprint"],
        "sourceIdentity": sources,
        "configurationFingerprint": baseline["configurationFingerprint"],
        "routeAllowlistSha256": configuration["routeAllowlistSha256"],
        "auth": {
            "before": auth_before,
            "after": auth_after,
            "refreshRequired": int(auth_metrics["refreshNeededCount"]) > 0,
            "refreshAttempted": int(auth_metrics["refreshAttemptCount"]) > 0,
            "refreshSucceeded": int(auth_metrics["refreshSuccessCount"]) > 0,
            "metrics": auth_metrics,
            "raceResult": "CANONICAL_MULTIPROCESS_LOCK_USED_IF_REFRESH_REQUIRED",
        },
        "quotes": {
            "observations": quote_observations,
            "timeline": quote_timeline,
        },
        "priceHistory": histories,
        "streamer": stream_result,
        "providerCallInventory": client.session.inventory,
        "safety": {
            "readOnly": True,
            "schwabMarketDataCalls": sum(
                row["requestClass"] in {"MARKET_DATA_QUOTES", "MARKET_DATA_PRICE_HISTORY"}
                for row in client.session.inventory
            ),
            "streamerBootstrapCalls": sum(
                row["requestClass"] == "STREAMER_BOOTSTRAP" for row in client.session.inventory
            ),
            "accountCalls": 0,
            "positionCalls": 0,
            "orderCalls": 0,
            "alpacaCalls": 0,
            "paperCalls": 0,
            "liveOrders": 0,
            "productionEvidenceWritten": False,
            "strategyStateWritten": False,
            "providerRolesChanged": False,
        },
    }
    result["evidenceFingerprint"] = fingerprint(result)
    write_json_once(output_root / "probe-result.json", result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the bounded Schwab overnight API probe.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, default=DEFAULT_DURATION_SECONDS)
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--stream-seconds", type=int, default=DEFAULT_STREAM_SECONDS)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({"taskId": TASK_ID, "status": "PLAN_ONLY", "symbols": list(SYMBOLS)}, indent=2))
        return 0
    try:
        result = run_probe(
            project_root=args.project_root.resolve(),
            output_root=args.output_root.resolve(),
            duration_seconds=args.duration_seconds,
            interval_seconds=args.interval_seconds,
            stream_seconds=args.stream_seconds,
        )
    except Exception as exc:
        print(json.dumps({"taskId": TASK_ID, "status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 2
    print(
        json.dumps(
            {
                "taskId": TASK_ID,
                "status": "COMPLETED",
                "outputRoot": str(args.output_root.resolve()),
                "evidenceFingerprint": result["evidenceFingerprint"],
                "accountCalls": 0,
                "positionCalls": 0,
                "orderCalls": 0,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
