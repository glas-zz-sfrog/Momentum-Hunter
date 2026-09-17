"""Pure protocol tests. Memory evidence is NOT a Windows security proof."""

from contextlib import contextmanager
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest

from momentum_hunter.science_custody_commit import (
    CustodyCommitConflict, CustodyCommitError, CustodyCommitIntegrityError,
    CustodyCommitPending, CustodyCommitRequest, CustodyCommitReceipt,
    CustodyObjectEvidence, ScienceCustodyFinalizer, canonical_protocol_bytes,
    claim_path, identity_for_artifact, receipt_path, sha256, validate_relative_path,
)
from momentum_hunter.strategy_science_recorder.canonical import canonical_json_bytes


class MemoryBackend:
    """No native authority: fake byte/object storage for deterministic protocol tests."""
    policy_sha256 = "a" * 64
    source_root_identity = "b" * 64
    max_artifact_bytes = 1024 * 1024
    max_request_bytes = 64 * 1024

    def __init__(self):
        self.objects = {}
        self.next_id = 1
        self.lock = threading.RLock()
        self.reads = []
        self.enumeration_limits = []
        self.closed = False
        self.deleted = []

    @contextmanager
    def transaction(self):
        with self.lock:
            yield

    def _new(self, namespace, name, raw):
        evidence = CustodyObjectEvidence(raw, (1, 0, self.next_id),
            "S-1-5-7" if namespace in {"requests", "staging"} else "S-1-5-19", "c" * 64)
        self.next_id += 1
        self.objects[namespace, name] = evidence
        return evidence

    def create_trusted(self, namespace, relative, raw):
        prior = self.objects.get((namespace, relative))
        if prior is not None:
            if prior.raw != raw:
                raise CustodyCommitConflict("Memory write-once conflict.")
            return False, prior
        return True, self._new(namespace, relative, raw)

    def read_trusted(self, namespace, relative, *, maximum):
        self.reads.append((namespace, relative))
        result = self.objects.get((namespace, relative))
        if result is not None and len(result.raw) > maximum:
            raise CustodyCommitError("Memory bounded read.")
        return result

    def ensure_durable(self, namespace, relative, expected):
        if self.objects.get((namespace, relative)) != expected:
            raise CustodyCommitIntegrityError("Memory durability target changed.")

    def publish_completion(self, relative, raw):
        return self.create_trusted("receipts", relative, raw)

    def _read_transport(self, namespace, name, maximum):
        result = self.objects.get((namespace, name))
        if result is None:
            raise FileNotFoundError(name)
        if len(result.raw) > maximum:
            raise CustodyCommitError("Memory bounded transport read.")
        return result

    def read_staged(self, name, *, maximum):
        return self._read_transport("staging", name, maximum)

    def read_request(self, name, *, maximum):
        return self._read_transport("requests", name, maximum)

    def bounded_names(self, namespace, limit):
        self.enumeration_limits.append((namespace, limit))
        names = []
        for current_namespace, name in self.objects:
            if current_namespace == namespace:
                names.append(name)
                if len(names) == limit:
                    break
        return tuple(names)

    def create_transport(self, namespace, name, raw):
        if (namespace, name) in self.objects:
            raise CustodyCommitConflict("Transport create-new conflict.")
        return self._new(namespace, name, raw)

    def delete_transport(self, namespace, name, *, expected_identity, expected_sha256):
        with self.lock:
            result = self.objects.get((namespace, name))
            if result is None:
                return False
            if result.file_identity != expected_identity or sha256(result.raw) != expected_sha256:
                raise CustodyCommitConflict("Atomic exact-object cleanup refused.")
            del self.objects[namespace, name]
            self.deleted.append((namespace, name, expected_identity))
            return True

    def close(self):
        self.closed = True


def arrival(sequence=1, text="original"):
    raw = canonical_json_bytes({"sequence": sequence, "type": "FIXTURE", "data": {"text": text}})
    return f"ledger/{sequence:020d}-{sha256(raw)}.event.json", raw


def request_for(backend, *, sequence=1, text="original", generation="1" * 32):
    path, raw = arrival(sequence, text)
    request = CustodyCommitRequest(backend.policy_sha256,
        identity_for_artifact(source_root_identity=backend.source_root_identity,
                              final_root="arrivals", relative_path=path, raw=raw),
        "arrivals", path, sha256(raw), sha256(raw), len(raw), generation + ".stage", generation)
    backend.create_transport("staging", request.staging_name, raw)
    return request


def artifact_request(backend, root, path, raw):
    generation = f"{backend.next_id:032x}"
    request = CustodyCommitRequest(backend.policy_sha256,
        identity_for_artifact(source_root_identity=backend.source_root_identity,
                              final_root=root, relative_path=path, raw=raw),
        root, path, sha256(raw), sha256(raw), len(raw), generation + ".stage", generation)
    backend.create_transport("staging", request.staging_name, raw)
    return request


class CommitProtocolTests(unittest.TestCase):
    def test_same_identity_same_bytes_returns_exact_original_receipt(self):
        backend = MemoryBackend()
        request = request_for(backend)
        finalizer = ScienceCustodyFinalizer(backend)
        first = finalizer.finalize(request)
        duplicate = finalizer.finalize(request)
        self.assertTrue(first.created)
        self.assertFalse(duplicate.created)
        self.assertEqual(first.receipt.to_bytes(), duplicate.receipt.to_bytes())
        self.assertEqual(first.receipt, CustodyCommitReceipt.from_bytes(first.receipt.to_bytes()))
        self.assertEqual(1, sum(key[0] == "arrivals" for key in backend.objects))

    def test_content_hash_and_filename_do_not_change_logical_identity(self):
        backend = MemoryBackend()
        first = request_for(backend)
        other = request_for(backend, text="conflict", generation="2" * 32)
        self.assertEqual(first.identity, other.identity)
        self.assertNotEqual(first.final_relative_path, other.final_relative_path)
        finalizer = ScienceCustodyFinalizer(backend)
        finalizer.finalize(first)
        with self.assertRaises(CustodyCommitConflict):
            finalizer.finalize(other)
        self.assertNotIn(("arrivals", other.final_relative_path), backend.objects)

    def test_restage_duplicate_preserves_original_claim_provenance(self):
        backend = MemoryBackend()
        first = request_for(backend)
        finalizer = ScienceCustodyFinalizer(backend)
        receipt = finalizer.finalize(first).receipt
        duplicate = request_for(backend, generation="2" * 32)
        self.assertEqual(receipt, finalizer.finalize(duplicate).receipt)
        self.assertEqual(first.request_digest(), receipt.original_request_sha256)

    def test_claim_reserves_identity_even_before_final(self):
        backend = MemoryBackend()
        first = request_for(backend)
        def fault(phase):
            if phase == "after_claim":
                raise RuntimeError("crash")
        with self.assertRaises(RuntimeError):
            ScienceCustodyFinalizer(backend, fault_hook=fault).finalize(first)
        other = request_for(backend, text="different", generation="2" * 32)
        with self.assertRaises(CustodyCommitConflict):
            ScienceCustodyFinalizer(backend).finalize(other)
        self.assertFalse(any(key[0] == "arrivals" for key in backend.objects))

    def test_each_protocol_crash_converges_on_one_exact_final(self):
        for stop in ("after_staging_read", "after_claim", "before_final", "after_final", "before_receipt", "after_receipt"):
            with self.subTest(stop=stop):
                backend = MemoryBackend()
                request = request_for(backend)
                def fault(phase):
                    if phase == stop:
                        raise RuntimeError(stop)
                with self.assertRaises(RuntimeError):
                    ScienceCustodyFinalizer(backend, fault_hook=fault).finalize(request)
                finalizer = ScienceCustodyFinalizer(backend)
                result = finalizer.finalize(request)
                self.assertEqual(result.receipt, finalizer.finalize(request).receipt)
                self.assertEqual(1, sum(key[0] == "arrivals" for key in backend.objects))
                self.assertEqual(stop in {"after_final", "before_receipt"}, result.recovered_receipt)

    def test_final_before_receipt_can_recover_without_staging(self):
        backend = MemoryBackend()
        request = request_for(backend)
        def fault(phase):
            if phase == "after_final":
                raise RuntimeError("crash")
        with self.assertRaises(RuntimeError):
            ScienceCustodyFinalizer(backend, fault_hook=fault).finalize(request)
        del backend.objects["staging", request.staging_name]
        self.assertTrue(ScienceCustodyFinalizer(backend).finalize(request).recovered_receipt)

    def test_missing_source_before_commit_is_pending_not_success(self):
        backend = MemoryBackend()
        request = request_for(backend)
        del backend.objects["staging", request.staging_name]
        with self.assertRaises(CustodyCommitPending):
            ScienceCustodyFinalizer(backend).finalize(request)
        self.assertEqual({}, backend.objects)

    def test_unclaimed_final_is_never_adopted(self):
        backend = MemoryBackend()
        request = request_for(backend)
        backend.create_trusted(request.final_root, request.final_relative_path,
                               backend.objects["staging", request.staging_name].raw)
        with self.assertRaises(CustodyCommitIntegrityError):
            ScienceCustodyFinalizer(backend).finalize(request)

    def test_missing_or_replaced_receipted_final_fails_without_recreation(self):
        for replacement in (None, "same_bytes_new_inode", "changed_bytes", "changed_owner", "changed_descriptor"):
            with self.subTest(replacement=replacement):
                backend = MemoryBackend()
                request = request_for(backend)
                finalizer = ScienceCustodyFinalizer(backend)
                finalizer.finalize(request)
                key = request.final_root, request.final_relative_path
                final = backend.objects[key]
                if replacement is None:
                    del backend.objects[key]
                elif replacement == "same_bytes_new_inode":
                    backend._new(*key, final.raw)
                elif replacement == "changed_bytes":
                    backend.objects[key] = replace(final, raw=b"broken")
                elif replacement == "changed_owner":
                    backend.objects[key] = replace(final, owner_sid="S-1-5-7")
                else:
                    backend.objects[key] = replace(final, descriptor_sha256="d" * 64)
                with self.assertRaises(CustodyCommitIntegrityError):
                    finalizer.finalize(request)

    def test_receipt_or_claim_mutation_fails(self):
        for namespace in ("claims", "receipts"):
            with self.subTest(namespace=namespace):
                backend = MemoryBackend()
                request = request_for(backend)
                finalizer = ScienceCustodyFinalizer(backend)
                finalizer.finalize(request)
                path = claim_path(request.identity.digest()) if namespace == "claims" else receipt_path(request.identity.digest())
                backend.objects[namespace, path] = replace(backend.objects[namespace, path], raw=b"{}\n")
                with self.assertRaises(CustodyCommitError):
                    finalizer.finalize(request)

    def test_missing_claim_with_receipt_fails(self):
        backend = MemoryBackend()
        request = request_for(backend)
        finalizer = ScienceCustodyFinalizer(backend)
        finalizer.finalize(request)
        del backend.objects["claims", claim_path(request.identity.digest())]
        with self.assertRaises(CustodyCommitIntegrityError):
            finalizer.lookup(request)

    def test_actual_pinned_bytes_must_match_before_claim(self):
        backend = MemoryBackend()
        request = request_for(backend)
        stage_key = "staging", request.staging_name
        backend.objects[stage_key] = replace(backend.objects[stage_key], raw=b"different")
        with self.assertRaises(CustodyCommitConflict):
            ScienceCustodyFinalizer(backend).finalize(request)
        self.assertFalse(any(k[0] == "claims" for k in backend.objects))

    def test_concurrent_duplicates_and_conflicts_are_serialized(self):
        backend = MemoryBackend()
        original = request_for(backend)
        conflict = request_for(backend, text="conflict", generation="2" * 32)
        def work(request):
            try:
                return ScienceCustodyFinalizer(backend).finalize(request).receipt
            except CustodyCommitConflict:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = tuple(pool.map(work, [original, conflict] * 15))
        receipts = [r.to_bytes() for r in results if r is not None]
        self.assertEqual(1, len(set(receipts)))
        self.assertIn(None, results)
        self.assertEqual(1, sum(k[0] == "arrivals" for k in backend.objects))

    def test_retry_and_new_commit_use_constant_direct_history_lookups(self):
        backend = MemoryBackend()
        finalizer = ScienceCustodyFinalizer(backend)
        counts = []
        for sequence in range(1, 61):
            request = request_for(backend, sequence=sequence, generation=f"{sequence:032x}")
            start = len(backend.reads)
            finalizer.finalize(request)
            counts.append(len(backend.reads) - start)
        self.assertEqual(1, len(set(counts)))
        self.assertEqual([], backend.enumeration_limits)

    def test_strict_request_types_fields_serialization_and_policy(self):
        backend = MemoryBackend()
        request = request_for(backend)
        self.assertEqual(request, CustodyCommitRequest.from_bytes(request.to_bytes()))
        for raw in (b'{"a":1,"a":2}\n', b'{}', request.to_bytes() + b'\n', b'[' * 2000):
            with self.subTest(raw=raw[:30]), self.assertRaises(CustodyCommitError):
                CustodyCommitRequest.from_bytes(raw)
        with self.assertRaises(CustodyCommitError):
            replace(request, byte_length=True)
        with self.assertRaises(CustodyCommitError):
            ScienceCustodyFinalizer(backend).finalize(replace(request, policy_sha256="d" * 64))
        with self.assertRaises(CustodyCommitError):
            CustodyCommitRequest.from_bytes(request.to_bytes(), max_bytes=10)

    def test_path_namespace_attacks_are_rejected(self):
        for path in ("../x", "x/../y", "/x", "C:/x", "x:stream", "x\\y", "x//y", "con.json",
                     "lpt1.foo", "x/y.", "x /y", "x/aux", "x/\x00", "x/é", "x/*"):
            with self.subTest(path=path), self.assertRaises(CustodyCommitError):
                validate_relative_path(path)

    def test_scientific_receipt_requires_exact_payload_claim_and_logical_session(self):
        backend = MemoryBackend()
        finalizer = ScienceCustodyFinalizer(backend)
        session = "sessions/2026-09-15/s-" + sha256(b"logical-session")
        record_id = {"recorder_id": "logical-record"}
        key = sha256(b"logical-record")
        payload_raw = canonical_json_bytes({"session_id": {"recorder_id": "logical-session"},
                                           "record_id": record_id, "channel": "discovery"})
        payload_path = f"{session}/payloads/discovery/{key}.payload.json"
        finalizer.finalize(artifact_request(backend, "custody", payload_path, payload_raw))
        receipt_raw = canonical_json_bytes({"record_id": record_id, "channel": "discovery",
            "record_key_sha256": key, "payload_sha256": sha256(payload_raw)})
        receipt_path_value = f"{session}/receipts/discovery/{key}.receipt.json"
        original_request = artifact_request(backend, "custody", receipt_path_value, receipt_raw)
        finalizer.finalize(original_request)
        for moved_session in (session.replace("2026-09-15", "2026-09-16"),
                              session.replace(sha256(b"logical-session"), sha256(b"other-session"))):
            with self.subTest(session=moved_session):
                moved_path = f"{moved_session}/receipts/discovery/{key}.receipt.json"
                moved = artifact_request(backend, "custody", moved_path, receipt_raw)
                with self.assertRaises(CustodyCommitError):
                    finalizer.finalize(moved)
                self.assertNotIn(("custody", moved_path), backend.objects)
        # An unclaimed physical copy under another logical session cannot supply
        # provenance for a moved receipt, even when its payload digest matches.
        foreign_session = session.replace(sha256(b"logical-session"), sha256(b"other-session"))
        backend._new("custody", f"{foreign_session}/payloads/discovery/{key}.payload.json", payload_raw)
        with self.assertRaises(CustodyCommitError):
            finalizer.finalize(artifact_request(backend, "custody", f"{foreign_session}/receipts/discovery/{key}.receipt.json", receipt_raw))

    def test_final_checksum_binds_original_manifest_inventory_without_history_scan(self):
        backend = MemoryBackend()
        finalizer = ScienceCustodyFinalizer(backend)
        session = "sessions/2026-09-15/s-" + sha256(b"logical-session")
        manifest_path = f"{session}/manifests/{'e' * 64}.final.json"
        manifest_raw = canonical_json_bytes({"session_id": {"recorder_id": "logical-session"},
                                             "artifact_inventory": []})
        finalizer.finalize(artifact_request(backend, "custody", manifest_path, manifest_raw))
        checksum_path = manifest_path.removesuffix(".final.json") + ".sha256"
        raw = f"{sha256(manifest_raw)}  {manifest_path}\n".encode("ascii")
        finalizer.finalize(artifact_request(backend, "custody", checksum_path, raw))
        foreign = checksum_path.replace(sha256(b"logical-session"), sha256(b"other-session"))
        with self.assertRaises(CustodyCommitIntegrityError):
            finalizer.finalize(artifact_request(backend, "custody", foreign, raw))
        self.assertEqual([], backend.enumeration_limits)


class ArtifactIdentityTests(unittest.TestCase):
    root = "b" * 64
    session = "sessions/2026-09-15/s-" + sha256(b"logical-session")

    def derive(self, root, path, value):
        return identity_for_artifact(source_root_identity=self.root, final_root=root,
                                     relative_path=path, raw=canonical_json_bytes(value))

    def test_cursor_identity_uses_ordinal_not_digest(self):
        identities = []
        for text in ("a", "b"):
            raw = canonical_json_bytes({"publication_ordinal": 3, "text": text})
            identities.append(identity_for_artifact(source_root_identity=self.root, final_root="cursors",
                relative_path=f"{3:020d}-{sha256(raw)}.reader-cursor.json", raw=raw))
        self.assertEqual(*identities)

    def test_source_payload_receipt_checkpoint_and_final_roles(self):
        event = "logical-event"
        stream = "logical-stream"
        event_key = sha256(event.encode())
        stream_key = sha256(canonical_json_bytes({"source_kind": "export", "stream_id": stream}))
        value = {"source_event_id": event, "stream_id": stream, "session_id": {"recorder_id": "logical-session"}}
        source = self.derive("custody", f"{self.session}/sources/export/{stream_key}/{event_key}.source.json", value)
        self.assertEqual("SOURCE", source.artifact_role)
        checkpoint = self.derive("custody", f"{self.session}/checkpoints/export/{stream_key}/{1:020d}-{event_key}.checkpoint.json",
                                 {**value, "source_sequence": 1})
        self.assertEqual("1", checkpoint.logical_key)
        record = {"record_id": {"recorder_id": "logical-record"}, "channel": "discovery", "session_id": {"recorder_id": "logical-session"}}
        key = sha256(b"logical-record")
        payload = self.derive("custody", f"{self.session}/payloads/discovery/{key}.payload.json", record)
        receipt = self.derive("custody", f"{self.session}/receipts/discovery/{key}.receipt.json",
                              {**record, "record_key_sha256": key})
        self.assertEqual(payload.logical_key, receipt.logical_key)
        self.assertNotEqual(payload.artifact_role, receipt.artifact_role)
        finals = [self.derive("custody", f"{self.session}/manifests/{x * 64}.final.json",
                             {"phase": "FINAL", "session_id": {"recorder_id": "logical-session"}}) for x in ("e", "f")]
        self.assertEqual(*finals)
        checksums = [identity_for_artifact(source_root_identity=self.root, final_root="custody",
            relative_path=f"{self.session}/manifests/{x * 64}.sha256", raw=b"checksum fixture") for x in ("e", "f")]
        self.assertEqual(*checksums)

    def test_moving_logical_record_or_source_to_other_partition_does_not_mint_identity(self):
        key = sha256(b"logical-record")
        record = {"record_id": {"recorder_id": "logical-record"}, "channel": "discovery", "session_id": {"recorder_id": "logical-session"}}
        first = self.derive("custody", f"{self.session}/payloads/discovery/{key}.payload.json", record)
        moved = self.derive("custody", f"{self.session.replace('2026-09-15', '2026-09-16')}/payloads/discovery/{key}.payload.json", record)
        self.assertEqual(first, moved)
        event_key = sha256(b"logical-event")
        stream_key = sha256(canonical_json_bytes({"source_kind": "export", "stream_id": "logical-stream"}))
        raw = {"source_event_id": "logical-event", "stream_id": "logical-stream", "session_id": {"recorder_id": "logical-session"}}
        path = f"{self.session}/sources/export/{stream_key}/{event_key}.source.json"
        self.assertEqual(self.derive("custody", path, raw),
                         self.derive("custody", path.replace('2026-09-15', '2026-09-16'), raw))

    def test_distinct_logical_sessions_keep_independent_record_and_source_domains(self):
        key = sha256(b"logical-record")
        record = {"record_id": {"recorder_id": "logical-record"}, "channel": "discovery", "session_id": {"recorder_id": "logical-session"}}
        path = f"{self.session}/payloads/discovery/{key}.payload.json"
        other_path = path.replace(sha256(b"logical-session"), sha256(b"other-session"))
        self.assertNotEqual(self.derive("custody", path, record), self.derive("custody", other_path,
                            {**record, "session_id": {"recorder_id": "other-session"}}))
        with self.assertRaises(CustodyCommitError):
            self.derive("custody", other_path, record)

    def test_final_manifest_rejects_foreign_session_namespace(self):
        with self.assertRaises(CustodyCommitError):
            self.derive("custody", f"{self.session}/manifests/{'e' * 64}.final.json",
                        {"session_id": {"recorder_id": "other-session"}})

    def test_conflict_occurrence_is_separate_from_accepted_source_identity(self):
        occurrence = {"accepted_sha256": "a" * 64, "conflicting_sha256": "b" * 64,
                      "logical_record_id": "record", "reason_code": "CONFLICT",
                      "source_event_id": "event", "stream_id": "stream"}
        key = sha256(canonical_json_bytes(occurrence))
        raw_id = identity_for_artifact(source_root_identity=self.root, final_root="custody",
            relative_path=f"{self.session}/conflicts/{key}.conflicting.raw", raw=b"not JSON")
        receipt = self.derive("custody", f"{self.session}/conflicts/{key}.conflict.json", {
            "accepted_payload_sha256": occurrence["accepted_sha256"], "conflicting_payload_sha256": occurrence["conflicting_sha256"],
            **{k: v for k, v in occurrence.items() if k not in {"accepted_sha256", "conflicting_sha256"}}})
        self.assertEqual(raw_id.logical_key, receipt.logical_key)
        self.assertEqual("CONFLICT_RAW", raw_id.artifact_role)
        self.assertEqual("CONFLICT_RECEIPT", receipt.artifact_role)

    def test_quarantine_identity_uses_original_partial_name(self):
        ids = []
        for digest in ("c" * 64, "d" * 64):
            partial = {"partial_name": "original.tmp", "sha256": digest, "byte_length": 4}
            ids.append(self.derive("custody", "quarantine-receipts/" + sha256(canonical_json_bytes(partial)) + ".quarantine.json",
                                    {"partial_before": partial}))
        self.assertEqual(*ids)


if __name__ == "__main__":
    unittest.main()
