"""Identify one 020U request without treating unobserved events as proof of absence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


_HASH = re.compile(r"[0-9a-f]{64}")
_GENERATION = re.compile(r"[0-9a-f]{32}")
_EXPECTED = ("receipt_create_begin", "receipt_create_result",
             "completion_create_begin", "completion_create_result",
             "lookup_begin", "receipt_read", "completion_read")


def load_rows(path: Path, role: str) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        row = json.loads(line)
        if row.get("schema") != "ARGUS_020U_CUSTODY_TRACE_V1" or row.get("role") != role:
            raise ValueError("Trace schema/role mismatch.")
        if row.get("sequence") != number:
            raise ValueError("Trace has a missing or duplicated event sequence.")
        digest = row.get("identity_sha256")
        if (not isinstance(digest, str) or _HASH.fullmatch(digest) is None
                or not isinstance(row.get("request_sha256"), str)
                or _HASH.fullmatch(row["request_sha256"]) is None
                or not isinstance(row.get("generation"), str)
                or _GENERATION.fullmatch(row["generation"]) is None):
            raise ValueError("Trace event lacks its exact request binding.")
        if row.get("event") not in _EXPECTED:
            raise ValueError("Unknown custody trace event.")
        if ((row["event"].startswith("receipt_create") or
             row["event"].startswith("completion_create")) and role != "writer"):
            raise ValueError("Creation trace is not Writer-owned.")
        if row["event"] == "lookup_begin" and role != "science":
            raise ValueError("Lookup trace is not Science-owned.")
        suffix = ".commit.json" if row["event"].startswith("receipt") else ".complete.json"
        if row.get("relative_path") != f"{digest[:2]}/{digest}{suffix}":
            raise ValueError("Trace path differs from its request digest.")
        result = row.get("result")
        identity = row.get("file_identity")
        content_hash = row.get("sha256")
        if result == "PRESENT":
            if (not isinstance(identity, list) or len(identity) != 3
                    or any(not isinstance(part, str) or not part.isdecimal() for part in identity)
                    or not isinstance(content_hash, str) or _HASH.fullmatch(content_hash) is None):
                raise ValueError("Present object lacks exact native identity/hash evidence.")
        elif result in {"BEGIN", "MISSING", "ERROR"}:
            if identity is not None or content_hash is not None:
                raise ValueError("Non-present object claims native identity/hash evidence.")
        else:
            raise ValueError("Unknown trace operation result.")
        rows.append(row)
    return rows


def summarize(writer_rows: list[dict], science_rows: list[dict]) -> dict:
    groups = {}
    for row in (*writer_rows, *science_rows):
        key = (row["identity_sha256"], row["request_sha256"], row["generation"])
        groups.setdefault(key, []).append(row)
    failures = []
    for key, events in groups.items():
        science = sorted((row for row in events if row["role"] == "science"),
                         key=lambda row: row["sequence"])
        for index, row in enumerate(science):
            if row["event"] != "lookup_begin":
                continue
            pair = science[index + 1:index + 3]
            read_results = {item["event"]: item["result"] for item in pair}
            if (len(pair) == 2 and len(read_results) == 2
                    and read_results.get("receipt_read") == "MISSING"
                    and read_results.get("completion_read") == "PRESENT"):
                observed = {event: [item for item in events if item["event"] == event]
                            for event in _EXPECTED}
                failures.append({
                    "identity_sha256": key[0], "request_sha256": key[1], "generation": key[2],
                    "lookup_read_order": [item["event"] for item in pair],
                    "receipt_path": f"{key[0][:2]}/{key[0]}.commit.json",
                    "completion_path": f"{key[0][:2]}/{key[0]}.complete.json",
                    "events": observed,
                    "missing_events": [event for event, items in observed.items() if not items],
                })
                break
    return {"writer_event_count": len(writer_rows), "science_event_count": len(science_rows),
            "trace_completeness": "NO_EVENTS" if not writer_rows or not science_rows else "EVENTS_PRESENT_NOT_CAUSAL_PROOF",
            "request_group_count": len(groups), "failing_request_count": len(failures),
            "failing_requests": failures}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--writer", type=Path, required=True)
    parser.add_argument("--science", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(summarize(load_rows(args.writer, "writer"),
                               load_rows(args.science, "science")), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
