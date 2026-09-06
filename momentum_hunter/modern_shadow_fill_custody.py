"""Immutable native Shadow fill receipts; aggregate fields are consistency caches."""
from dataclasses import asdict

from momentum_hunter.modern_recovery_integrity import complete_publication_history
from momentum_hunter.modern_operational import (
    OperationalSnapshot, SnapshotPublication, canonical_bytes, deny, digest,
    freeze_snapshot, instant, parse_bytes,
)


def receipt_history(epoch, order_id):
    """Return the exact committed per-order prefix, never infer missing receipts."""
    publication = SnapshotPublication(epoch, "SHADOW_FILL")
    records = []
    seen = set()
    cumulative = 0
    history = complete_publication_history(publication)
    receipt_ids = {snapshot.snapshot_id for snapshot in history}
    positions = complete_publication_history(SnapshotPublication(epoch, "POSITION"))
    for snapshot in positions:
        for row in parse_bytes(snapshot.component("positions"))["positions"]:
            if row.get("fillSnapshotId") not in receipt_ids:
                deny("Preserved position evidence references missing immutable fill custody.")
    for snapshot in reversed(history):
        if {name for name, _ in snapshot.components} != {"fill"}:
            deny("Incomplete Shadow fill custody.")
        body = parse_bytes(snapshot.component("fill"))
        if set(body) != {"schemaVersion", "admissionId", "orderId", "fillId", "quoteFingerprint",
                         "priorFillSnapshotId", "incrementalFilledQuantity", "cumulativeFilledQuantity",
                         "authorizedQuantity", "firstFill", "order", "position", "admission", "positionIdentity"}:
            deny("Malformed Shadow fill receipt.")
        if body["schemaVersion"] != 1 or type(body["schemaVersion"]) is not int:
            deny("Unknown Shadow fill receipt schema.")
        order, position = body["order"], body["position"]
        if type(order) is not dict or type(position) is not dict or order.get("order_id") != body["orderId"]:
            deny("Shadow receipt order binding is contradictory.")
        if body["orderId"] != order_id:
            continue
        if type(body["firstFill"]) is not str:
            deny("First Shadow fill receipt bytes are missing.")
        first = parse_bytes(body["firstFill"].encode("ascii"))
        quantity, authorized = body["incrementalFilledQuantity"], body["authorizedQuantity"]
        if (type(quantity) is not int or quantity <= 0 or type(authorized) is not int or authorized <= 0
                or body["fillId"] != digest(canonical_bytes({"orderId": order_id,
                    "quoteFingerprint": body["quoteFingerprint"]})) or body["fillId"] in seen):
            deny("Duplicate, changed, or invalid Shadow fill receipt.")
        seen.add(body["fillId"])
        cumulative += quantity
        previous = records[-1] if records else None
        if (body["priorFillSnapshotId"] != (previous[0].snapshot_id if previous else None)
                or type(body["cumulativeFilledQuantity"]) is not int
                or type(order.get("filled_quantity")) is not int
                or cumulative > authorized or body["cumulativeFilledQuantity"] != cumulative
                or order.get("quantity") != authorized or order.get("filled_quantity") != cumulative
                or position.get("quantity") != cumulative
                or order.get("remaining_quantity") != authorized - cumulative
                or position.get("position_id") != first.get("positionId")
                or position.get("opened_at") != first.get("filledAt")):
            deny("Shadow fill history contradicts authorization, ancestry, or cumulative quantity.")
        if instant(order["last_update_at"]) != instant(parse_bytes(snapshot.manifest_bytes)["createdAt"]):
            deny("Shadow fill receipt chronology differs from its snapshot.")
        if previous is None:
            if first.get("filledQuantity") != quantity:
                deny("First Shadow receipt differs from immutable first-fill quantity.")
        elif (body["firstFill"] != previous[1]["firstFill"]
                or body["admissionId"] != previous[1]["admissionId"]
                or body["admission"] != previous[1]["admission"]
                or body["positionIdentity"] != previous[1]["positionIdentity"]
                or authorized != previous[1]["authorizedQuantity"]
                or instant(order["last_update_at"]) <= instant(previous[1]["order"]["last_update_at"])):
            deny("Follow-on fill changed its first fill, authorization, or chronology.")
        records.append((snapshot, body))
    return tuple(records)


def validate_fill_custody(fill, epoch, *, require_latest=True):
    if type(fill.fill_snapshot) is not OperationalSnapshot:
        deny("Modern Shadow recovery requires immutable cumulative fill custody.")
    fill.fill_snapshot.validate(epoch, kind="SHADOW_FILL")
    history = receipt_history(epoch, fill.order.order_id)
    selected = next((item for item in history if item[0] == fill.fill_snapshot), None)
    if selected is None or (require_latest and history[-1] != selected):
        deny("Shadow recovery does not own the latest committed fill history.")
    body = selected[1]
    if (body["admissionId"] != fill.admission.admission_id
            or body["admission"] != fill.admission.wire()
            or body["positionIdentity"] != {**fill.identity.core(), "fingerprint": fill.identity.fingerprint}
            or body["order"] != asdict(fill.order) or body["position"] != asdict(fill.position)
            or body["firstFill"].encode("ascii") != fill.first_fill):
        deny("Persisted Shadow aggregates differ from authoritative fill receipts.")
    return body["cumulativeFilledQuantity"]


def record_fill(epoch, *, admission, order, position, identity, first_fill, quote, prior):
    """Seal native fill output before any mutable aggregate can be persisted."""
    publication = SnapshotPublication(epoch, "SHADOW_FILL")
    history = receipt_history(epoch, order.order_id)
    previous_fill = history[-1] if history else None
    if (prior is None) != (previous_fill is None) or (prior is not None and prior.fill_snapshot != previous_fill[0]):
        deny("Shadow fill predecessor changed before receipt publication.")
    cumulative = previous_fill[1]["cumulativeFilledQuantity"] if previous_fill else 0
    proposed = order.filled_quantity - cumulative
    authorized = admission.validate(epoch, new_entry=False)[4].final_authorized_quantity
    if (type(proposed) is not int or proposed <= 0 or cumulative + proposed > authorized
            or order.quantity != authorized or position.quantity != cumulative + proposed
            or order.remaining_quantity != authorized - cumulative - proposed):
        deny("Proposed cumulative Shadow fill exceeds or contradicts its exact authorization.")
    quote_fingerprint = digest(canonical_bytes(asdict(quote)))
    if any(item[1]["quoteFingerprint"] == quote_fingerprint for item in history):
        deny("A confirmed quote/fill receipt cannot be counted twice.")
    body = {"schemaVersion": 1, "admissionId": admission.admission_id, "orderId": order.order_id,
        "fillId": digest(canonical_bytes({"orderId": order.order_id, "quoteFingerprint": quote_fingerprint})),
        "quoteFingerprint": quote_fingerprint,
        "priorFillSnapshotId": previous_fill[0].snapshot_id if previous_fill else None,
        "incrementalFilledQuantity": proposed, "cumulativeFilledQuantity": cumulative + proposed,
        "authorizedQuantity": order.quantity, "firstFill": first_fill.decode("ascii"),
        "order": asdict(order), "position": asdict(position), "admission": admission.wire(),
        "positionIdentity": {**identity.core(), "fingerprint": identity.fingerprint}}
    current = publication.current()
    snapshot = freeze_snapshot(epoch, kind="SHADOW_FILL", components=(("fill", canonical_bytes(body)),),
        sequence=parse_bytes(current.manifest_bytes)["sequence"] + 1 if current else 1,
        predecessor=current.snapshot_id if current else None, created_at=quote.timestamp,
        known_at=quote.timestamp, decision_cutoff=quote.timestamp)
    publication.publish(snapshot, expected_previous=current.snapshot_id if current else None)
    return snapshot
