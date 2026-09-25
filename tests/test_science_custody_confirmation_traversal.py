"""Bounded fresh proof traversal; structural doubles are not native authority."""
from collections import Counter
from dataclasses import replace
import json
import unittest

from momentum_hunter.science_custody_commit import (
    CustodyCommitError, CustodyCommitIntegrityError, CustodyCommitPending,
    ScienceCustodyFinalizer, canonical_protocol_bytes, claim_path, completion_path, receipt_path, sha256,
)
from momentum_hunter.strategy_science_recorder.canonical import canonical_json_bytes
from tests.test_science_custody_commit_007 import MemoryBackend, artifact_request, request_for


def committed_pair(backend):
    finalizer = ScienceCustodyFinalizer(backend)
    session = "sessions/2026-09-15/s-" + sha256(b"logical-session")
    record = {"recorder_id": "logical-record"}
    key = sha256(b"logical-record")
    raw = canonical_json_bytes({"session_id": {"recorder_id": "logical-session"},
                                "record_id": record, "channel": "discovery"})
    payload = artifact_request(backend, "custody", f"{session}/payloads/discovery/{key}.payload.json", raw)
    finalizer.finalize(payload)
    receipt_raw = canonical_json_bytes({"record_id": record, "channel": "discovery",
        "record_key_sha256": key, "payload_sha256": sha256(raw)})
    receipt = artifact_request(backend, "custody", f"{session}/receipts/discovery/{key}.receipt.json", receipt_raw)
    finalizer.finalize(receipt)
    return finalizer, payload, receipt


class ConfirmationTraversalTests(unittest.TestCase):
    def test_fresh_simple_confirmation_reads_one_claim_and_compares_two_finals(self):
        backend = MemoryBackend()
        request = request_for(backend)
        finalizer = ScienceCustodyFinalizer(backend)
        finalizer.finalize(request)
        backend.reads.clear()
        result = finalizer.read_confirmed(request.final_root, request.final_relative_path)
        self.assertEqual(request.content_sha256, sha256(result.raw))
        self.assertEqual(Counter({("claims", claim_path(request.identity.digest())): 1,
            (request.final_root, request.final_relative_path): 2,
            ("receipts", receipt_path(request.identity.digest())): 1,
            ("receipts", completion_path(request.identity.digest())): 1}), Counter(backend.reads))

    def test_dependency_uses_exact_confirmed_payload_without_duplicate_claim_walk(self):
        backend = MemoryBackend()
        finalizer, payload, receipt = committed_pair(backend)
        backend.reads.clear()
        result = finalizer.read_confirmed(receipt.final_root, receipt.final_relative_path)
        self.assertEqual(receipt.content_sha256, sha256(result.raw))
        self.assertEqual(9, len(backend.reads))
        for request in (payload, receipt):
            self.assertEqual(1, backend.reads.count(("claims", claim_path(request.identity.digest()))))

    def test_no_confirmed_result_is_cached_between_reads(self):
        for changed in ("identity", "owner", "descriptor", "bytes"):
            with self.subTest(changed=changed):
                backend = MemoryBackend()
                request = request_for(backend)
                finalizer = ScienceCustodyFinalizer(backend)
                finalizer.finalize(request)
                finalizer.read_confirmed(request.final_root, request.final_relative_path)
                key = request.final_root, request.final_relative_path
                old = backend.objects[key]
                overrides = {"identity": {"file_identity": (9, 9, 9)},
                             "owner": {"owner_sid": "S-1-5-18"},
                             "descriptor": {"descriptor_sha256": "d" * 64},
                             "bytes": {"raw": old.raw.replace(b"original", b"modified")}}[changed]
                backend.objects[key] = replace(old, **overrides)
                with self.assertRaises(CustodyCommitError):
                    finalizer.read_confirmed(request.final_root, request.final_relative_path)

    def test_same_bytes_object_substitution_between_final_reads_fails(self):
        backend = MemoryBackend()
        request = request_for(backend)
        finalizer = ScienceCustodyFinalizer(backend)
        finalizer.finalize(request)
        read = backend.read_trusted
        key = request.final_root, request.final_relative_path
        calls = 0

        def substitute(namespace, relative, *, maximum):
            nonlocal calls
            if (namespace, relative) == key:
                calls += 1
                if calls == 2:
                    backend.objects[key] = replace(backend.objects[key], file_identity=(1, 0, 999))
            return read(namespace, relative, maximum=maximum)

        backend.read_trusted = substitute
        with self.assertRaises(CustodyCommitIntegrityError):
            finalizer.read_confirmed(*key)

    def test_dependency_missing_completion_is_pending_not_confirmed(self):
        backend = MemoryBackend()
        finalizer, payload, receipt = committed_pair(backend)
        del backend.objects["receipts", completion_path(payload.identity.digest())]
        before = dict(backend.objects)
        with self.assertRaises(CustodyCommitPending):
            finalizer.read_confirmed(receipt.final_root, receipt.final_relative_path)
        self.assertEqual(before, backend.objects)

    def test_missing_dependency_claim_receipt_or_final_never_passes(self):
        for target in ("claim", "receipt", "final"):
            with self.subTest(target=target):
                backend = MemoryBackend()
                finalizer, payload, receipt = committed_pair(backend)
                key = {"claim": ("claims", claim_path(payload.identity.digest())),
                       "receipt": ("receipts", receipt_path(payload.identity.digest())),
                       "final": (payload.final_root, payload.final_relative_path)}[target]
                del backend.objects[key]
                before = dict(backend.objects)
                with self.assertRaises(CustodyCommitError):
                    finalizer.read_confirmed(receipt.final_root, receipt.final_relative_path)
                self.assertEqual(before, backend.objects)

    def test_complete_dependency_claim_schema_stays_blocking(self):
        for field in ("version", "request_sha256", "staging_file_identity",
                      "staging_owner_sid", "staging_descriptor_sha256", "generation", "policy"):
            with self.subTest(field=field):
                backend = MemoryBackend()
                finalizer, payload, receipt = committed_pair(backend)
                key = "claims", claim_path(payload.identity.digest())
                value = json.loads(backend.objects[key].raw)
                if field == "generation":
                    value["request"]["generation"] = "f" * 32
                    value["request"]["staging_name"] = "f" * 32 + ".stage"
                    value["request_sha256"] = sha256(canonical_protocol_bytes(value["request"]))
                elif field == "policy":
                    value["request"]["policy_sha256"] = "f" * 64
                    value["request_sha256"] = sha256(canonical_protocol_bytes(value["request"]))
                else:
                    value[field] = {"version": "unbound", "request_sha256": "f" * 64,
                        "staging_file_identity": [1, True, 3], "staging_owner_sid": "",
                        "staging_descriptor_sha256": "invalid"}[field]
                backend.objects[key] = replace(backend.objects[key], raw=canonical_protocol_bytes(value))
                with self.assertRaises(CustodyCommitError):
                    finalizer.read_confirmed(receipt.final_root, receipt.final_relative_path)

    def test_dependency_replaced_with_same_bytes_still_fails_receipt_binding(self):
        backend = MemoryBackend()
        finalizer, payload, receipt = committed_pair(backend)
        read = backend.read_trusted
        target = payload.final_root, payload.final_relative_path

        def replace_at_read(namespace, relative, *, maximum):
            if (namespace, relative) == target:
                backend.objects[target] = replace(backend.objects[target], file_identity=(1, 0, 999))
            return read(namespace, relative, maximum=maximum)

        backend.read_trusted = replace_at_read
        with self.assertRaises(CustodyCommitIntegrityError):
            finalizer.read_confirmed(receipt.final_root, receipt.final_relative_path)

    def test_dependency_recovery_still_requires_new_fresh_proof(self):
        backend = MemoryBackend()
        finalizer, payload, receipt = committed_pair(backend)
        target = "receipts", completion_path(payload.identity.digest())
        del backend.objects[target]
        original_finalize = finalizer.finalize
        recoveries = []

        def recover_then_remove(request):
            result = original_finalize(request)
            recoveries.append(request)
            del backend.objects[target]
            return result

        finalizer.finalize = recover_then_remove
        with self.assertRaises(CustodyCommitPending):
            finalizer._verify_scientific_receipt(receipt,
                backend.objects[receipt.final_root, receipt.final_relative_path].raw, recover=True)
        self.assertEqual([payload], recoveries)

    def test_dependency_crash_recovery_remains_idempotent(self):
        backend = MemoryBackend()
        finalizer, payload, receipt = committed_pair(backend)
        target = "receipts", completion_path(payload.identity.digest())
        old = backend.objects[target].raw
        del backend.objects[target]
        raw = backend.objects[receipt.final_root, receipt.final_relative_path].raw
        finalizer._verify_scientific_receipt(receipt, raw, recover=True)
        self.assertEqual(old, backend.objects[target].raw)
        before = dict(backend.objects)
        finalizer._verify_scientific_receipt(receipt, raw, recover=True)
        self.assertEqual(before, backend.objects)


if __name__ == "__main__":
    unittest.main()
