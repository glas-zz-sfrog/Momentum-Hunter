"""Current-epoch identity admission shared by Producer, Shadow and Paper.

This contract transports verified lineage, never permission to place an order.
Historical inspection has a separate projection and cannot return an admission.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from momentum_hunter.modern_operational import (
    OperationalEpoch, OperationalSnapshot, SnapshotPublication,
    canonical_bytes, deny, digest, exact_chain, instant, parse_bytes, require_hash,
    require_schema, snapshot_from_bytes,
)


def validate_composition_snapshot(snapshot: OperationalSnapshot, epoch: OperationalEpoch):
    """The same pre-publication semantic check is used by every consumer."""
    from momentum_hunter.continuous_tradeplan_producer import ContinuousTradePlanProducerStore
    from momentum_hunter import candidate_lifecycle as lifecycle
    from momentum_hunter import sequential_breakout_research as breakout

    manifest = snapshot.validate(epoch, kind="COMPOSITION")
    if {name for name, _ in snapshot.components} != {
        "candidateLifecycle", "sequentialBreakout", "producer", "originalState"}:
        deny("Joint decision snapshot is incomplete.")
    originals = parse_bytes(snapshot.component("originalState"))
    if set(originals) != {"candidateLifecycle", "sequentialBreakout", "producer"}:
        deny("Joint snapshot original generation is incomplete.")
    for value in originals.values():
        if value is not None:
            require_hash(value, "Original state")
    ledger = lifecycle.ledger_from_wire(parse_bytes(snapshot.component("candidateLifecycle")))
    lifecycle.validate_ledger(ledger)
    breakout_ledger = breakout.ledger_from_wire(parse_bytes(snapshot.component("sequentialBreakout")))
    breakout.validate_ledger(breakout_ledger)
    from momentum_hunter.continuous_natural_setup import SOURCE_IDENTITY, _transition_evidence_fingerprint
    for event in ledger.events:
        if event.source_identity == SOURCE_IDENTITY:
            if not any(item.symbol == event.symbol and item.session_date == event.session_date
                       and event.evidence_fingerprint in {
                           item.fingerprint, _transition_evidence_fingerprint(item.fingerprint, event.next_state)}
                       for item in breakout_ledger.events):
                deny("Lifecycle transition has no matching breakout event in the joint generation.")
    store = ContinuousTradePlanProducerStore(
        Path(epoch.root) / "state" / "continuous-tradeplan-producer.json", operational_epoch=epoch)
    records = store.validate_bytes(snapshot.component("producer"))
    for record in records:
        payload = parse_bytes(record.payload_json.encode("ascii"))
        prior = payload["authoritativeLifecycle"]
        prefix = []
        found = False
        for event in ledger.events:
            prefix.append(event)
            if event.event_id == prior["latest_event_id"]:
                found = True
                break
        state = lifecycle.lifecycle_snapshots(
            lifecycle.CandidateLifecycleLedger(events=tuple(prefix))).get(record.opportunity_id)
        if not found or state is None or asdict(state) != prior:
            deny("Producer lifecycle prefix is not in the joint snapshot.")
        if record.setup_id and not any(event.opportunity_id == record.opportunity_id
                                      and event.setup_id == record.setup_id for event in ledger.events):
            deny("Producer setup is absent from the joint lifecycle.")
        epoch.require_time(record.evidence_cutoff)
        if instant(record.evidence_cutoff) > instant(manifest["decisionCutoff"]):
            deny("Producer input exceeds the frozen decision cutoff.")
        for member in payload["compositionCycle"]["member_results"]:
            plan = member["intraday_plan"]
            if plan is not None and not any(
                item.event_id in plan["source_evidence_ids"]
                and item.source_evidence_fingerprint in plan["source_evidence_ids"]
                and item.symbol == plan["symbol"] and item.session_date == plan["session_date"]
                and item.setup_family == plan["setup_family"]
                for item in breakout_ledger.events
            ):
                deny("Producer plan is not bound to the exact joint breakout generation.")
    return records, ledger, breakout_ledger


@dataclass(frozen=True)
class ModernDecisionIdentity:
    snapshot: OperationalSnapshot
    opportunity_id: str
    setup_id: str
    trade_plan_id: str
    producer_record_id: str
    producer_record_fingerprint: str

    @property
    def snapshot_id(self) -> str:
        return self.snapshot.snapshot_id

    def wire(self) -> dict:
        return {"schemaVersion": 1, "snapshotId": self.snapshot_id,
            "snapshot": self.snapshot.to_bytes().decode("ascii"),
            "opportunity_id": self.opportunity_id, "setup_id": self.setup_id,
            "trade_plan_id": self.trade_plan_id, "producer_record_id": self.producer_record_id,
            "producer_record_fingerprint": self.producer_record_fingerprint}

    def validate(self, epoch: OperationalEpoch, *, current: bool = True):
        from momentum_hunter import candidate_lifecycle as lifecycle

        chain = exact_chain({"opportunity_id": self.opportunity_id, "setup_id": self.setup_id,
                             "trade_plan_id": self.trade_plan_id})
        publication = SnapshotPublication(epoch, "COMPOSITION")
        if current:
            publication.require_consumed(self.snapshot, expected_id=self.snapshot_id)
        else:
            publication.require_committed(self.snapshot, expected_id=self.snapshot_id)
        records, lifecycle_ledger, _ = validate_composition_snapshot(self.snapshot, epoch)
        matches = [record for record in records if record.record_id == self.producer_record_id]
        if len(matches) != 1:
            deny("Exact Producer record is missing or ambiguous.")
        record = matches[0]
        latest = next((item for item in reversed(records) if item.opportunity_id == self.opportunity_id
                       and item.lifecycle_state != "NO_LIFECYCLE_CHANGE"), None)
        if latest != record:
            deny("A superseded Producer decision cannot be selected for new authority.")
        if (exact_chain(asdict(record)) != chain
                or record.fingerprint != self.producer_record_fingerprint):
            deny("Producer and downstream authoritative identity contradict.")
        state = lifecycle.lifecycle_snapshots(lifecycle_ledger).get(self.opportunity_id)
        if state is None or state.current_setup_id != self.setup_id or state.symbol != record.symbol:
            deny("Selected setup is not the snapshot's current lifecycle setup.")
        return record


def decision_from_wire(value: object, epoch: OperationalEpoch, *, expected_snapshot_id: str,
                       current: bool = True) -> ModernDecisionIdentity:
    if type(value) is not dict or set(value) != {
        "schemaVersion", "snapshotId", "snapshot", "opportunity_id", "setup_id", "trade_plan_id",
        "producer_record_id", "producer_record_fingerprint"}:
        deny("Modern decision binding is absent, stripped, or malformed.")
    require_schema(value["schemaVersion"], 1)
    if value["snapshotId"] != expected_snapshot_id or type(value["snapshot"]) is not str:
        deny("Decision snapshot does not match the independent handoff identity.")
    snapshot = snapshot_from_bytes(value["snapshot"].encode("ascii"), epoch,
        kind="COMPOSITION", expected_id=expected_snapshot_id)
    decision = ModernDecisionIdentity(snapshot, *exact_chain(value),
                                     value["producer_record_id"], value["producer_record_fingerprint"])
    decision.validate(epoch, current=current)
    return decision


@dataclass(frozen=True)
class ModernPositionIdentity:
    decision: ModernDecisionIdentity
    position_id: str
    opened_at: str
    first_fill_id: str
    first_fill_sha256: str
    fingerprint: str

    def core(self) -> dict:
        return {"schemaVersion": 1, "decision": self.decision.wire(),
            "positionId": self.position_id, "openedAt": self.opened_at,
            "firstFillId": self.first_fill_id, "firstFillSha256": self.first_fill_sha256}

    def validate(self, epoch: OperationalEpoch, *, first_fill: bytes,
                 position_id: str, opened_at: str) -> None:
        self.decision.validate(epoch, current=False)
        fill = parse_bytes(first_fill)
        require_schema(fill.get("schemaVersion"), 1)
        epoch.validate_binding(fill)
        quantity = fill.get("filledQuantity")
        if type(quantity) not in (float, int) or quantity <= 0:
            deny("Position identity requires a positive confirmed first fill.")
        if (self.position_id != position_id or self.opened_at != opened_at
                or self.first_fill_sha256 != digest(first_fill)
                or self.first_fill_id != fill.get("fillId")
                or self.position_id != fill.get("positionId")
                or self.opened_at != fill.get("filledAt")
                or exact_chain(fill) != (self.decision.opportunity_id,
                    self.decision.setup_id, self.decision.trade_plan_id)
                or fill.get("snapshotId") != self.decision.snapshot_id
                or self.fingerprint != digest(canonical_bytes(self.core()))):
            deny("Position/first-fill identity was altered or rebound.")
        epoch.require_time(opened_at)
        if instant(opened_at) < instant(parse_bytes(self.decision.snapshot.manifest_bytes)["decisionCutoff"]):
            deny("Position was opened before its accepted decision.")


def bind_first_fill(decision: ModernDecisionIdentity, epoch: OperationalEpoch, *,
                    first_fill: bytes, prior: ModernPositionIdentity | None = None) -> ModernPositionIdentity:
    decision.validate(epoch, current=prior is None)
    fill = parse_bytes(first_fill)
    if prior is not None:
        # Later partial fills cannot replace the independently preserved first fill.
        if prior.decision != decision:
            deny("An existing position cannot be rebound to a successor decision.")
        prior.validate(epoch, first_fill=first_fill, position_id=fill.get("positionId"),
                       opened_at=fill.get("filledAt"))
        return prior
    if (type(fill.get("positionId")) is not str or not fill["positionId"]
            or type(fill.get("fillId")) is not str or not fill["fillId"]):
        deny("Exact position and first-fill identities are required.")
    identity = ModernPositionIdentity(decision, fill["positionId"], fill.get("filledAt"),
                                     fill["fillId"], digest(first_fill), "")
    from dataclasses import replace
    identity = replace(identity, fingerprint=digest(canonical_bytes(identity.core())))
    identity.validate(epoch, first_fill=first_fill, position_id=identity.position_id,
                      opened_at=identity.opened_at)
    return identity


def review_linkage(decision: ModernDecisionIdentity | None, epoch: OperationalEpoch | None, *,
                   position: ModernPositionIdentity | None = None, first_fill: bytes | None = None,
                   historical: bool = False) -> dict:
    if historical:
        return {"opportunityId": None, "setupId": None, "tradePlanId": None,
                "positionId": None, "openedAt": None, "linkageStatus": "LEGACY_UNBOUND"}
    if decision is None or epoch is None:
        return {"opportunityId": None, "setupId": None, "tradePlanId": None,
                "positionId": None, "openedAt": None, "linkageStatus": "UNKNOWN"}
    decision.validate(epoch, current=position is None)
    if position is not None:
        if position.decision != decision or first_fill is None:
            deny("Position review lacks exact upstream or first-fill provenance.")
        position.validate(epoch, first_fill=first_fill,
                          position_id=position.position_id, opened_at=position.opened_at)
    return {"opportunityId": decision.opportunity_id, "setupId": decision.setup_id,
            "tradePlanId": decision.trade_plan_id,
            "positionId": position.position_id if position else None,
            "openedAt": position.opened_at if position else None,
            "linkageStatus": "PROVEN" if position else "UNAVAILABLE"}
