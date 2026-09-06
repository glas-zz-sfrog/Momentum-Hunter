"""Native Continuous identity handoff, not an execution or risk engine.

The strategy/risk owner records its native results using publish_strategy_result.
Admission only carries those exact results. This module never calls an allocator,
risk evaluator, broker or provider and has no installed application entrypoint.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from decimal import Decimal
from enum import Enum

from momentum_hunter.lifecycle_position_identity import ModernDecisionIdentity, decision_from_wire
from momentum_hunter.modern_operational import (
    OperationalEpoch, OperationalSnapshot, SnapshotPublication, canonical_bytes,
    deny, digest, freeze_snapshot, instant, parse_bytes, require_schema, snapshot_from_bytes,
)
from momentum_hunter.paper_risk_governor import PaperRiskDecision, PAPER_RISK_MODE, PAPER_RISK_PROFILE
from momentum_hunter.provider_neutral_allocation import (
    AllocationRequest, AllocationStatus, ProviderNeutralAllocationDecision, QuantityMode,
    PROVIDER_NEUTRAL_ALLOCATION_PROFILE,
)


ADMISSION_PROFILE = "ARGUS_CONTINUOUS_OPERATIONAL_ADMISSION_V1"
_NATIVE_TYPES = (PaperRiskDecision, AllocationRequest, ProviderNeutralAllocationDecision)
_DECIMALS = {
    PaperRiskDecision: {"execution_price", "spread_percent", "reward_risk_at_execution"},
    AllocationRequest: {"entry_price", "stop_price", "target_price"},
    ProviderNeutralAllocationDecision: {
        "quantity_increment", "ideal_risk_quantity", "provider_executable_quantity",
        "final_authorized_quantity", "risk_per_share", "effective_cash_available",
        "effective_open_risk_available", "position_notional", "total_risk", "target_reward"},
}


def _wire_native(value):
    def convert(item):
        if isinstance(item, Decimal):
            if not item.is_finite():
                deny("Nonfinite native economic result.")
            return str(item)
        if isinstance(item, Enum):
            return item.value
        if isinstance(item, dict):
            return {key: convert(part) for key, part in item.items()}
        if isinstance(item, tuple):
            return [convert(part) for part in item]
        return item
    if type(value) not in _NATIVE_TYPES:
        deny("Only native strategy/risk result types may be transported.")
    return convert(asdict(value))


def _read_native(value, cls):
    if type(value) is not dict or set(value) != {item.name for item in fields(cls)}:
        deny("Stripped or unsupported native risk/allocation result.")
    body = dict(value)
    for name in _DECIMALS[cls]:
        raw = body[name]
        if raw is not None:
            if type(raw) is not str:
                deny("Native Decimal representation changed.")
            number = Decimal(raw)
            if not number.is_finite():
                deny("Nonfinite native economic result.")
            body[name] = number
    for name in ("blockers", "warnings"):
        if name in body:
            if type(body[name]) is not list or any(type(item) is not str for item in body[name]):
                deny("Invalid native result findings.")
            body[name] = tuple(body[name])
    if "schema_version" in body:
        require_schema(body["schema_version"], 1)
    if type(body["canonical_rank"]) is not int or body["canonical_rank"] <= 0:
        deny("Missing exact strategy-selected rank.")
    if cls is ProviderNeutralAllocationDecision:
        if body["profile"] != PROVIDER_NEUTRAL_ALLOCATION_PROFILE:
            deny("Unrecognized allocation result profile.")
        body["status"] = AllocationStatus(body["status"])
        body["quantity_mode"] = QuantityMode(body["quantity_mode"])
    if cls is PaperRiskDecision and (body["profile"] != PAPER_RISK_PROFILE or body["mode"] != PAPER_RISK_MODE):
        deny("Unrecognized native risk result profile/mode.")
    result = cls(**body)
    if _wire_native(result) != value:
        deny("Native result did not round-trip exactly.")
    return result


def _history(publication):
    current = publication.current()
    for _ in range(4096):
        if current is None:
            return
        yield current
        manifest = parse_bytes(current.manifest_bytes)
        previous = manifest["predecessorSnapshotId"]
        if previous is None:
            return
        from momentum_hunter.modern_operational import require_hash
        raw = (publication.root / (require_hash(previous, "Predecessor") + ".json")).read_bytes()
        current = snapshot_from_bytes(raw, publication.epoch, kind=publication.kind, expected_id=previous)
        if parse_bytes(current.manifest_bytes)["sequence"] != manifest["sequence"] - 1:
            deny("Native admission history is not contiguous.")
    deny("Native admission history exceeds its bounded recovery limit.")


def _publish(epoch, kind, components, when):
    publication = SnapshotPublication(epoch, kind)
    with epoch.transaction(), publication.lease.transaction():
        previous = publication.current()
        if kind in {"STRATEGY_DECISION", "CONTINUOUS_ADMISSION", "CONTINUOUS_INTENT", "CONTINUOUS_FILL"}:
            for committed in _history(publication):
                if committed.components == components:
                    return committed
        snapshot = freeze_snapshot(epoch, kind=kind, components=components,
            sequence=parse_bytes(previous.manifest_bytes)["sequence"] + 1 if previous else 1,
            predecessor=previous.snapshot_id if previous else None,
            created_at=when, known_at=when, decision_cutoff=when)
        publication.publish(snapshot, expected_previous=previous.snapshot_id if previous else None)
        return snapshot


def _strategy_parts(snapshot, epoch, *, current_decision):
    if type(snapshot) is not OperationalSnapshot:
        deny("Strategy handoff requires exact frozen snapshot bytes.")
    manifest = snapshot.validate(epoch, kind="STRATEGY_DECISION")
    if {name for name, _ in snapshot.components} != {"strategyResult"}:
        deny("Unsupported strategy-result components.")
    body = parse_bytes(snapshot.component("strategyResult"))
    if set(body) != {"profile", "decision", "risk", "request", "allocation",
                     "riskFingerprint", "allocationFingerprint", "requestFingerprint"}:
        deny("Incomplete strategy-result custody.")
    if body["profile"] != ADMISSION_PROFILE:
        deny("Opening admission is not native Continuous admission.")
    decision = decision_from_wire(body["decision"], epoch,
        expected_snapshot_id=body["decision"]["snapshotId"], current=current_decision)
    record = decision.validate(epoch, current=current_decision)
    risk = _read_native(body["risk"], PaperRiskDecision)
    request = _read_native(body["request"], AllocationRequest)
    allocation = _read_native(body["allocation"], ProviderNeutralAllocationDecision)
    if (body["riskFingerprint"] != risk.fingerprint
            or body["requestFingerprint"] != request.fingerprint
            or body["allocationFingerprint"] != allocation.fingerprint):
        deny("Native economic result bytes were changed.")
    for value in (risk, request, allocation):
        if (value.trade_plan_id != decision.trade_plan_id or value.symbol != record.symbol
                or value.candidate_id != record.record_id
                or value.canonical_rank != request.canonical_rank):
            deny("Strategy/risk identity differs from the exact Producer selection.")
    if (risk.setup_id != decision.setup_id or risk.risk_decision_id != request.risk_decision_id
            or allocation.risk_decision_id != risk.risk_decision_id
            or allocation.decision_cycle_id != request.decision_cycle_id
            or allocation.request_fingerprint != request.fingerprint
            or risk.decision_at != request.decision_at):
        deny("Risk/allocation source linkage is contradictory.")
    payload = parse_bytes(record.payload_json.encode("ascii"))
    members = [item for item in payload["compositionCycle"]["member_results"]
               if item["universe_member_id"] == record.member_id]
    if len(members) != 1 or members[0]["intraday_plan"] is None:
        deny("Exact Producer plan is absent or ambiguous.")
    plan = members[0]["intraday_plan"]
    if (request.stop_price != Decimal(str(plan["stop_price"]))
            or request.target_price != Decimal(str(plan["target_prices"][0]))
            or request.entry_price != risk.execution_price
            or request.entry_order_type not in {"market", "limit"}
            or (request.entry_order_type == "limit"
                and request.entry_price != Decimal(str(plan["planned_entry"])) )
            or instant(risk.decision_at) < instant(record.evidence_cutoff)
            or instant(risk.decision_at) > instant(manifest["decisionCutoff"])):
        deny("Frozen strategy economics or chronology differ from their plan.")
    return decision, record, risk, request, allocation, plan


def _require_latest_strategy(snapshot, epoch):
    selected = parse_bytes(snapshot.component("strategyResult"))["decision"]["producer_record_id"]
    for current in _history(SnapshotPublication(epoch, "STRATEGY_DECISION")):
        body = parse_bytes(current.component("strategyResult"))
        if body["decision"]["producer_record_id"] == selected:
            if current != snapshot:
                deny("A later strategy/risk result superseded this approval.")
            return
    deny("Strategy result is not committed.")


def publish_strategy_result(*, decision, epoch, risk, request, allocation, recorded_at):
    """Strategy-owner persistence of already-evaluated results, not risk approval.

    Requires the independently approved source/epoch namespace. No public file
    import or legacy result adapter exists. Native evaluators remain upstream;
    this API cannot turn a rejection into an approval or supply missing results.
    """
    if type(decision) is not ModernDecisionIdentity:
        deny("Missing exact Continuous Producer selection.")
    body = {"profile": ADMISSION_PROFILE, "decision": decision.wire(),
        "risk": _wire_native(risk), "request": _wire_native(request),
        "allocation": _wire_native(allocation), "riskFingerprint": risk.fingerprint,
        "requestFingerprint": request.fingerprint, "allocationFingerprint": allocation.fingerprint}
    components = (("strategyResult", canonical_bytes(body)),)
    composition = SnapshotPublication(epoch, "COMPOSITION")
    with epoch.transaction(), composition.lease.transaction():
        # Semantic validation consumes the exact same immutable component bytes
        # later published; the strategy result never reopens an input path.
        preview = freeze_snapshot(epoch, kind="STRATEGY_DECISION", components=components,
            sequence=1, predecessor=None, created_at=recorded_at, known_at=recorded_at,
            decision_cutoff=recorded_at)
        _strategy_parts(preview, epoch, current_decision=True)
        return _publish(epoch, "STRATEGY_DECISION", components, recorded_at)


@dataclass(frozen=True)
class ContinuousOperationalAdmission:
    snapshot: OperationalSnapshot

    @property
    def admission_id(self):
        return self.snapshot.snapshot_id

    def wire(self):
        return {"profile": ADMISSION_PROFILE, "admissionId": self.admission_id,
                "snapshot": self.snapshot.to_bytes().decode("ascii")}

    def validate(self, epoch, *, new_entry=True):
        self.snapshot.validate(epoch, kind="CONTINUOUS_ADMISSION")
        SnapshotPublication(epoch, "CONTINUOUS_ADMISSION").require_committed(
            self.snapshot, expected_id=self.admission_id)
        if {name for name, _ in self.snapshot.components} != {"strategySnapshot", "disposition"}:
            deny("Admission contains unsupported components.")
        if self.snapshot.component("disposition") != b'"ADMITTED"':
            deny("Only an admitted native strategy decision may reach consumers.")
        raw = self.snapshot.component("strategySnapshot")
        strategy = snapshot_from_bytes(raw, epoch, kind="STRATEGY_DECISION",
            expected_id=digest(parse_bytes(raw)["manifest"].encode("ascii")))
        SnapshotPublication(epoch, "STRATEGY_DECISION").require_committed(
            strategy, expected_id=strategy.snapshot_id)
        parts = _strategy_parts(strategy, epoch, current_decision=new_entry)
        if new_entry:
            _require_latest_strategy(strategy, epoch)
        _, record, risk, _, allocation, _ = parts
        if not record.execution_eligible or not risk.authorized or not allocation.authorized:
            deny("Identity cannot override a readiness, instrument, risk or sizing rejection.",
                 "CONTINUOUS_ADMISSION_RISK_BLOCKED")
        return parts


def admit_continuous(*, epoch, strategy_snapshot, admitted_at):
    if type(strategy_snapshot) is not OperationalSnapshot:
        deny("Native Continuous admission requires a frozen strategy snapshot.")
    composition = SnapshotPublication(epoch, "COMPOSITION")
    with epoch.transaction(), composition.lease.transaction():
        SnapshotPublication(epoch, "STRATEGY_DECISION").require_committed(
            strategy_snapshot, expected_id=strategy_snapshot.snapshot_id)
        _, record, risk, _, allocation, _ = _strategy_parts(
            strategy_snapshot, epoch, current_decision=True)
        _require_latest_strategy(strategy_snapshot, epoch)
        if (not record.execution_eligible or not risk.authorized or not allocation.authorized
                or instant(admitted_at) < instant(risk.decision_at)):
            deny("Strategy/risk did not authorize this exact selection.",
                 "CONTINUOUS_ADMISSION_RISK_BLOCKED")
        snapshot = _publish(epoch, "CONTINUOUS_ADMISSION",
            (("strategySnapshot", strategy_snapshot.to_bytes()), ("disposition", b'"ADMITTED"')), admitted_at)
        return ContinuousOperationalAdmission(snapshot)


def admission_from_wire(value, epoch):
    if type(value) is not dict or set(value) != {"profile", "admissionId", "snapshot"}:
        deny("Missing or legacy Continuous admission.")
    if value["profile"] != ADMISSION_PROFILE or type(value["snapshot"]) is not str:
        deny("Wrong admission contract.")
    return ContinuousOperationalAdmission(snapshot_from_bytes(value["snapshot"].encode("ascii"),
        epoch, kind="CONTINUOUS_ADMISSION", expected_id=value["admissionId"]))


@dataclass(frozen=True)
class ContinuousEntryIntent:
    snapshot: OperationalSnapshot

    def validate(self, epoch, *, consumer):
        self.snapshot.validate(epoch, kind="CONTINUOUS_INTENT")
        SnapshotPublication(epoch, "CONTINUOUS_INTENT").require_committed(
            self.snapshot, expected_id=self.snapshot.snapshot_id)
        if {name for name, _ in self.snapshot.components} != {"intent"}:
            deny("Unexpected intent components.")
        body = parse_bytes(self.snapshot.component("intent"))
        if set(body) != {"profile", "consumer", "localOrderId", "admission",
                         "executionAuthority", "orderCapability"}:
            deny("Legacy or altered Continuous intent.")
        if (body["profile"] != ADMISSION_PROFILE or body["consumer"] != consumer
                or body["executionAuthority"] != "NONE" or body["orderCapability"] != "UNAVAILABLE"):
            deny("Continuous intent crossed its consumer/authority boundary.")
        admission = admission_from_wire(body["admission"], epoch)
        parts = admission.validate(epoch, new_entry=False)
        expected_order_id = digest(canonical_bytes({"consumer": consumer,
                                                   "admissionId": admission.admission_id}))
        if body["localOrderId"] != expected_order_id:
            deny("Local order lineage was rebound.")
        return admission, parts


def prepare_continuous_intent(admission, epoch, *, consumer, recorded_at):
    if type(admission) is not ContinuousOperationalAdmission or consumer not in {"SHADOW", "PAPER"}:
        deny("Opening/raw decision cannot authorize a Continuous intent.")
    composition = SnapshotPublication(epoch, "COMPOSITION")
    with epoch.transaction(), composition.lease.transaction():
        parts = admission.validate(epoch)
        plan = parts[-1]
        if (instant(recorded_at) < instant(parts[2].decision_at)
                or not instant(plan["entry_valid_from"]) <= instant(recorded_at)
                <= instant(plan["entry_expires_at"])):
            deny("Frozen plan is outside its entry lifetime.")
        body = {"profile": ADMISSION_PROFILE, "consumer": consumer,
            "localOrderId": digest(canonical_bytes({"consumer": consumer,
                                                   "admissionId": admission.admission_id})),
            "admission": admission.wire(), "executionAuthority": "NONE", "orderCapability": "UNAVAILABLE"}
        return ContinuousEntryIntent(_publish(epoch, "CONTINUOUS_INTENT",
            (("intent", canonical_bytes(body)),), recorded_at))


@dataclass(frozen=True)
class ContinuousFillLineage:
    """Dormant first-fill custody only; never a provider receipt producer."""
    snapshot: OperationalSnapshot

    def validate(self, epoch, *, consumer):
        from momentum_hunter.lifecycle_position_identity import ModernPositionIdentity
        self.snapshot.validate(epoch, kind="CONTINUOUS_FILL")
        SnapshotPublication(epoch, "CONTINUOUS_FILL").require_committed(
            self.snapshot, expected_id=self.snapshot.snapshot_id)
        if {name for name, _ in self.snapshot.components} != {"intent", "firstFill", "position"}:
            deny("Incomplete first-fill custody.")
        raw = self.snapshot.component("intent")
        intent = ContinuousEntryIntent(snapshot_from_bytes(raw, epoch, kind="CONTINUOUS_INTENT",
            expected_id=digest(parse_bytes(raw)["manifest"].encode("ascii"))))
        _, parts = intent.validate(epoch, consumer=consumer)
        position = parse_bytes(self.snapshot.component("position"))
        if set(position) != {"positionId", "openedAt", "firstFillId", "firstFillSha256", "fingerprint"}:
            deny("Invalid native position linkage.")
        bound = ModernPositionIdentity(parts[0], position["positionId"], position["openedAt"],
            position["firstFillId"], position["firstFillSha256"], position["fingerprint"])
        first = self.snapshot.component("firstFill")
        bound.validate(epoch, first_fill=first, position_id=bound.position_id, opened_at=bound.opened_at)
        if (parse_bytes(first).get("localOrderId") != parse_bytes(intent.snapshot.component("intent"))["localOrderId"]
                or instant(bound.opened_at) < instant(parse_bytes(intent.snapshot.manifest_bytes)["createdAt"])
                or instant(bound.opened_at) > instant(parse_bytes(self.snapshot.manifest_bytes)["createdAt"])):
            deny("First fill contradicts the exact local order chronology/identity.")
        return intent, bound, first

    def review(self, epoch, *, consumer):
        from momentum_hunter.lifecycle_position_identity import review_linkage
        intent, bound, first = self.validate(epoch, consumer=consumer)
        return {**review_linkage(bound.decision, epoch, position=bound, first_fill=first),
            "operationalEpoch": epoch.epoch_id, "snapshotId": bound.decision.snapshot_id,
            "localOrderId": parse_bytes(intent.snapshot.component("intent"))["localOrderId"],
            "executionAuthority": "NONE", "orderCapability": "UNAVAILABLE"}


def bind_continuous_first_fill(intent, epoch, *, consumer, first_fill, recorded_at):
    from momentum_hunter.lifecycle_position_identity import bind_first_fill
    if type(intent) is not ContinuousEntryIntent or type(first_fill) is not bytes:
        deny("First-fill handoff requires exact native intent and immutable receipt bytes.")
    publication = SnapshotPublication(epoch, "CONTINUOUS_FILL")
    composition = SnapshotPublication(epoch, "COMPOSITION")
    with epoch.transaction(), composition.lease.transaction(), publication.lease.transaction():
        _, parts = intent.validate(epoch, consumer=consumer)
        # Only the first confirmed receipt creates identity. Subsequent partial
        # fills must retain it, never relabel an earlier position or obligation.
        for previous in _history(publication):
            lineage = ContinuousFillLineage(previous)
            previous_intent, _, previous_fill = lineage.validate(epoch, consumer=consumer)
            if previous_intent == intent:
                if first_fill != previous_fill:
                    deny("First-fill identity cannot be replaced during partial-fill recovery.")
                return lineage
        bound = bind_first_fill(parts[0], epoch, first_fill=first_fill)
        if (parse_bytes(first_fill).get("localOrderId") != parse_bytes(intent.snapshot.component("intent"))["localOrderId"]
                or instant(bound.opened_at) < instant(parse_bytes(intent.snapshot.manifest_bytes)["createdAt"])
                or instant(bound.opened_at) > instant(recorded_at)):
            deny("First-fill receipt does not belong to the admitted order chronology.")
        position = {"positionId": bound.position_id, "openedAt": bound.opened_at,
            "firstFillId": bound.first_fill_id, "firstFillSha256": bound.first_fill_sha256,
            "fingerprint": bound.fingerprint}
        return ContinuousFillLineage(_publish(epoch, "CONTINUOUS_FILL",
            (("intent", intent.snapshot.to_bytes()), ("firstFill", first_fill),
             ("position", canonical_bytes(position))), recorded_at))
