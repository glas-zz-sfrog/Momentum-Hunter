from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from momentum_hunter.config import DATA_DIR
from momentum_hunter.schwab_market_data import (
    INJECTED_QUOTE_PROOF_ORIGIN,
    LIVE_SCHWAB_QUOTE_PROOF_ORIGIN,
    SchwabMarketDataQuoteSource,
    build_regular_market_quote_proof,
    write_proof,
)
from momentum_hunter.shadow_proof_bundle import (
    CAPTURES_DIR,
    PROJECT_ROOT,
    REPORTS_DIR,
    STATIC_PROOF_NAMES,
    finalize_selector_proof_bundle,
    load_proof_context,
    read_and_validate_candidate_report,
    run_command,
    validate_static_artifact,
    verify_canonical_git_still_matches,
)
from momentum_hunter.shadow_trading import (
    SHADOW_SELECTOR_ARM_CONFIRMATION,
    SHADOW_STATE_PATH,
    ShadowStateError,
    ShadowStateStore,
    ShadowTradingService,
    selector_proof_bundle_paths,
)


DEFAULT_QUOTE_ATTEMPTS = 3
DEFAULT_QUOTE_RETRY_SECONDS = 2.0


class ShadowArmCeremonyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ShadowArmCeremonyResult:
    state: str
    candidate: str
    bundle: str
    quote_proof: str
    arm_id: str
    verified_at: str
    transmitting: bool = False
    order_transmission: str = "UNAVAILABLE"


Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]


def complete_shadow_selector_arm(
    bundle: Path,
    report_path: Path,
    *,
    state_path: Path = SHADOW_STATE_PATH,
    reports_dir: Path = REPORTS_DIR,
    captures_dir: Path = CAPTURES_DIR,
    quote_proof_path: Path | None = None,
    quote_source: object | None = None,
    quote_attempts: int = DEFAULT_QUOTE_ATTEMPTS,
    quote_retry_seconds: float = DEFAULT_QUOTE_RETRY_SECONDS,
    clock: Clock | None = None,
    sleeper: Sleeper = time.sleep,
    service: ShadowTradingService | None = None,
) -> ShadowArmCeremonyResult:
    active_clock = clock or (lambda: datetime.now(timezone.utc))
    active_service = service or ShadowTradingService(
        store=ShadowStateStore(state_path)
    )
    if active_service.selector_is_armed():
        arm = active_service.selector_arm_record()
        assert arm is not None
        return ShadowArmCeremonyResult(
            state="ALREADY_ARMED",
            candidate="",
            bundle=str(bundle.resolve()),
            quote_proof="",
            arm_id=arm.arm_id,
            verified_at=arm.armed_at,
        )

    proof_paths = selector_proof_bundle_paths(bundle)
    fresh_proof_path = proof_paths["fresh_quote_boundary"]
    try:
        _proofs, verified_at = (
            active_service.verify_automatic_selector_prerequisites(
                proof_paths
            )
        )
    except ShadowStateError:
        if fresh_proof_path.exists():
            raise
    else:
        arm = active_service.arm_automatic_selector(
            confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
            prerequisite_proof_paths=proof_paths,
        )
        return ShadowArmCeremonyResult(
            state="ARMED_FROM_COMPLETE_BUNDLE",
            candidate="",
            bundle=str(bundle.resolve()),
            quote_proof="",
            arm_id=arm.arm_id,
            verified_at=verified_at.isoformat(),
        )

    checked_at = require_offset_aware(clock_value=active_clock())
    context = load_proof_context(state_path)
    canonical_root = PROJECT_ROOT.resolve()
    verify_canonical_git_still_matches(
        bundle,
        canonical_root,
        command_runner=run_command,
    )
    for proof_name in STATIC_PROOF_NAMES:
        validate_static_artifact(
            bundle / f"{proof_name}.json",
            proof_name=proof_name,
            context=context,
            verified_at=checked_at,
        )
    report_evidence = read_and_validate_candidate_report(
        report_path,
        reports_dir=reports_dir,
        captures_dir=captures_dir,
        context=context,
        finalized_at=checked_at,
    )
    candidate = report_evidence.candidate
    if quote_proof_path is not None and quote_proof_path.exists():
        raise ShadowArmCeremonyError(
            "The regular-market quote proof output already exists."
        )
    active_source = quote_source or SchwabMarketDataQuoteSource()
    proof: dict[str, object] | None = None
    for attempt in range(max(1, quote_attempts)):
        checked_at = require_offset_aware(clock_value=active_clock())
        proof = build_regular_market_quote_proof(
            active_source,
            (candidate, "SPY", "IWM"),
            checked_at=checked_at,
        )
        proof["evidenceOrigin"] = (
            LIVE_SCHWAB_QUOTE_PROOF_ORIGIN
            if quote_source is None
            else INJECTED_QUOTE_PROOF_ORIGIN
        )
        proof["productionSource"] = quote_source is None
        if proof.get("proofStatus") == "PASS":
            break
        if attempt + 1 < max(1, quote_attempts):
            sleeper(max(0.0, quote_retry_seconds))
    assert proof is not None

    output_path = quote_proof_path or default_quote_proof_path(
        checked_at=checked_at
    )
    if output_path.exists():
        raise ShadowArmCeremonyError(
            "The regular-market quote proof output already exists."
        )
    write_proof(output_path, proof)
    if proof.get("proofStatus") != "PASS":
        raise ShadowArmCeremonyError(
            "The live Schwab regular-market quote proof did not pass."
        )

    finalize_selector_proof_bundle(
        bundle,
        quote_proof_path=output_path,
        report_path=report_path,
        state_path=state_path,
        reports_dir=reports_dir,
        captures_dir=captures_dir,
        finalized_at=require_offset_aware(clock_value=active_clock()),
    )
    _proofs, verified_at = (
        active_service.verify_automatic_selector_prerequisites(
            proof_paths
        )
    )
    arm = active_service.arm_automatic_selector(
        confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
        prerequisite_proof_paths=proof_paths,
    )
    return ShadowArmCeremonyResult(
        state="ARMED",
        candidate=candidate,
        bundle=str(bundle.resolve()),
        quote_proof=str(output_path.resolve()),
        arm_id=arm.arm_id,
        verified_at=verified_at.isoformat(),
    )


def default_quote_proof_path(*, checked_at: datetime) -> Path:
    stamp = checked_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return (
        DATA_DIR
        / "reports"
        / f"official-shadow-v1-live-quote-proof-{stamp}.json"
    )


def require_offset_aware(*, clock_value: datetime) -> datetime:
    if clock_value.tzinfo is None or clock_value.utcoffset() is None:
        raise ShadowArmCeremonyError(
            "Shadow arm ceremony clock must include a UTC offset."
        )
    return clock_value
