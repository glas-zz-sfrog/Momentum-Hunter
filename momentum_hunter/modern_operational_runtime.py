"""Dormant modern startup owner; no service entrypoint or execution adapter.

The activation owner supplies approved running-source identity, market-only
provider transports and a freshly completed obligation preflight. No default
credential lookup, account inspection or authority provisioning occurs here.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import threading
from typing import Callable, Iterator
from zoneinfo import ZoneInfo

from momentum_hunter.continuous_live_qualification import (
    LiveCompositionSource, LiveDenominatorSource, LiveDiscoverySource,
    LiveMarketDataSource, LiveMaterialEvents, QualificationState,
)
from momentum_hunter.continuous_runtime import (
    ContinuousOpportunityRuntime, ContinuousRuntimeConfig, EvidenceIntentWriter,
    LogicalRuntimeLeaseRegistry, RuntimeCheckpointStore,
)
from momentum_hunter.continuous_tradeplan_producer import ContinuousTradePlanProducerStore
from momentum_hunter.modern_operational import (
    ObligationAssessment, OperationalEpoch, deny, initialize_epoch, instant,
    load_current_epoch, require_epoch_started,
)
from momentum_hunter.path_transaction import PathTransactionLease


_OWNERS_LOCK = threading.Lock()
_OWNED_ROOTS: set[Path] = set()


@dataclass(frozen=True)
class ModernRuntimeSession:
    epoch: OperationalEpoch
    state: QualificationState
    runtime: ContinuousOpportunityRuntime
    composition: LiveCompositionSource


@contextmanager
def open_modern_runtime(
    *,
    source_identity: str,
    config: ContinuousRuntimeConfig,
    runtime_instance_id: str,
    fresh: bool,
    clock: Callable[[], datetime],
    obligation_preflight: Callable[[OperationalEpoch, datetime], ObligationAssessment],
    discovery_provider: object,
    market_data_boundary: object,
    writer: EvidenceIntentWriter,
) -> Iterator[ModernRuntimeSession]:
    """Select, preflight, start/restore and own one native modern runtime.

    Explicit provider transports have the same interfaces used by the canonical
    live sources. Tests supply synthetic transports, not synthesized lifecycle,
    setup or composition sources. This function is not called by an installed
    service and does not connect Shadow or Paper.
    """
    if type(config) is not ContinuousRuntimeConfig or type(fresh) is not bool:
        deny("Modern startup requires exact configuration and startup mode.")
    if discovery_provider is None or market_data_boundary is None or writer is None:
        deny("Explicit market-only transports and evidence writer are required.")
    epoch = load_current_epoch(source_identity=source_identity,
                               configuration_identity=config.fingerprint)
    now = clock()
    epoch.require_time(now.isoformat())
    if now.astimezone(ZoneInfo("America/New_York")).date().isoformat() != config.session_date:
        deny("Runtime session differs from the current prospective startup session.")
    root = Path(epoch.root)
    with _OWNERS_LOCK:
        if root in _OWNED_ROOTS:
            deny("Another modern runtime owns this epoch root.", "MODERN_RUNTIME_ALREADY_OWNED")
        _OWNED_ROOTS.add(root)
    try:
        # The lifetime lease is outside the selected empty namespace. A second
        # process cannot preflight/start the same root while its owner is alive.
        with PathTransactionLease(root.with_name(root.name + ".runtime-owner")).transaction():
            epoch.require_current()
            assessment = obligation_preflight(epoch, now)
            if type(assessment) is not ObligationAssessment:
                deny("Missing native obligation assessment.", "BLOCK_RECONCILIATION_REQUIRED")
            if instant(assessment.observed_at) != instant(now.isoformat()):
                deny("Obligation preflight must bind this startup observation.",
                     "BLOCK_RECONCILIATION_REQUIRED")
            assessment.require_clear(epoch, fresh=fresh)
            with epoch.transaction():
                if fresh:
                    initialize_epoch(epoch, assessment)
                    ContinuousTradePlanProducerStore(
                        root / "state" / "continuous-tradeplan-producer.json",
                        operational_epoch=epoch,
                    ).initialize_modern()
                else:
                    require_epoch_started(epoch)
                checkpoints = RuntimeCheckpointStore(
                    root / "runtime", allow_persistent=True, operational_epoch=epoch,
                    runtime_config=config)
                if fresh:
                    launch_at = now
                else:
                    checkpoint = checkpoints.load(config.runtime_identity)
                    launch_at = instant(checkpoint["started_at"])
                    if launch_at > instant(now.isoformat()):
                        deny("Runtime checkpoint start is in the future.")
                state = QualificationState(
                    root=root / "session", launch_at=launch_at,
                    now_provider=clock, allow_persistent=True,
                    configuration_fingerprint=config.fingerprint)
                composition = LiveCompositionSource(
                    state, configuration_fingerprint=config.fingerprint,
                    operational_epoch=epoch)
                # Natural interrupted-composition recovery occurs in the native
                # coordinator constructor, then reload validates the exact view.
                composition.producer_store.load()
                discovery = LiveDiscoverySource(state, provider=discovery_provider)
                market = LiveMarketDataSource(
                    state, expected_account_ending="",
                    provider_boundary=market_data_boundary)
                events = LiveMaterialEvents(
                    state, market.backfill, natural_setup=composition.natural_setup)
                dependencies = dict(
                    config=config, runtime_instance_id=runtime_instance_id,
                    discovery_source=discovery, market_data_source=market,
                    event_source=events, composition_source=composition,
                    denominator_source=LiveDenominatorSource(state), writer=writer,
                    lease_registry=LogicalRuntimeLeaseRegistry(), checkpoint_store=checkpoints)
                if fresh:
                    runtime = ContinuousOpportunityRuntime(**dependencies)
                    runtime.start(now)
                else:
                    runtime = ContinuousOpportunityRuntime.restore(now=now, **dependencies)
            try:
                yield ModernRuntimeSession(epoch, state, runtime, composition)
            finally:
                # Preserve queued work for exact recovery; context exit must
                # never initiate provider work by draining a decision queue.
                runtime.shutdown(clock(), work_budget=0)
    finally:
        with _OWNERS_LOCK:
            _OWNED_ROOTS.remove(root)
