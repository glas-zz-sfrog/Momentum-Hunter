"""Read original native custody for a bounded, interrupted V2 handoff.

No source production methods are called here. Missing/evicted/conflicting
native custody leaves publication incomplete rather than re-evaluating a trade.
"""
from __future__ import annotations

import json
from dataclasses import asdict

from momentum_hunter.broad_discovery import DiscoverySnapshot
from momentum_hunter.continuous_tradeplan_producer import ContinuousTradePlanProducerStore
from momentum_hunter.hot_universe import HotUniverseStore


def native_inventory(stage, source):
    if stage == "COMPOSITION" and isinstance(getattr(source, "producer_store", None), ContinuousTradePlanProducerStore):
        store = source.producer_store
        rows = store.load()
        return {"identity": str(store.path.resolve()), "exists": store.path.is_file(),
                "configuration": source.producer.configuration_fingerprint,
                "records": {r.record_id: r.fingerprint for r in rows}}
    if stage == "DISCOVERY" and isinstance(getattr(source, "store", None), HotUniverseStore):
        store = source.store
        receipts = store.load().snapshot_receipts
        return {"identity": str(store.path.resolve()), "exists": store.path.is_file(),
                "records": {r.snapshot_id: r.snapshot_fingerprint for r in receipts}}
    return {"identity": None, "records": {}}


def recovered_sources(stage, source, before):
    after = native_inventory(stage, source)
    if before["identity"] is None or before["identity"] != after["identity"]:
        raise ValueError("NATIVE_HANDOFF_CUSTODY_UNAVAILABLE_OR_CHANGED")
    if before.get("exists") and not after.get("exists"):
        raise ValueError("NATIVE_HANDOFF_STORE_DISAPPEARED")
    if before.get("configuration") != after.get("configuration"):
        raise ValueError("NATIVE_HANDOFF_CONFIGURATION_CHANGED")
    if any(after["records"].get(key) != value for key, value in before["records"].items()):
        raise ValueError("NATIVE_HANDOFF_CUSTODY_CHANGED_OR_EVICTED")
    added = set(after["records"]) - set(before["records"])
    result = []
    if stage == "COMPOSITION":
        for record in source.producer_store.load():
            if record.record_id in added:
                if record.fingerprint != after["records"][record.record_id]:
                    raise ValueError("NATIVE_HANDOFF_RECORD_CHANGED")
                if record.configuration_fingerprint != before["configuration"]:
                    raise ValueError("NATIVE_HANDOFF_RECORD_CONFIGURATION_CHANGED")
                result.append(("NATIVE_PRODUCER_RECORD", record.record_id, asdict(record)))
    else:
        for key in sorted(added):
            path = source.state.root / "source-evidence" / "finviz" / (key + ".json")
            payload = json.loads(path.read_bytes())
            snapshot = DiscoverySnapshot.from_dict(payload)
            if snapshot.snapshot_id != key or snapshot.fingerprint != after["records"][key]:
                raise ValueError("NATIVE_HANDOFF_SNAPSHOT_CHANGED")
            result.append(("DISCOVERY", "native-snapshot:" + key, {"sourceEvidence": {"snapshot": payload}}))
    if len(result) != len(added) or native_inventory(stage, source) != after:
        raise ValueError("NATIVE_HANDOFF_CUSTODY_CHANGED_DURING_READ")
    return result
