"""One outstanding Science publication on an account-authorized file mailbox.

Transport acknowledgment is not scientific admission.  Normal callers must
register and drain their single committed namespace delta before acknowledge.
Startup may reconcile old transport before opening new namespace guards, then
must still run the existing complete scientific recovery/audit.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Callable, Protocol

from momentum_hunter.science_custody_commit import (
    CustodyCommitBackend, CustodyCommitConflict, CustodyCommitError,
    CustodyCommitIntegrityError, CustodyCommitPending, CustodyCommitRequest,
    CustodyCommitResult, CustodyObjectEvidence, ScienceCustodyFinalizer,
    identity_for_artifact, sha256,
)
from momentum_hunter.strategy_science_recorder.canonical import (
    canonical_json_bytes, parse_rfc3339, strict_json_loads,
)


REQUEST_NAME = "request.json"
_STAGE_NAME = re.compile(r"[0-9a-f]{32}\.stage")


class CustodyMailboxBackend(CustodyCommitBackend, Protocol):
    def bounded_names(self, namespace: str, limit: int) -> tuple[str, ...]: ...
    def create_transport(self, namespace: str, name: str, raw: bytes) -> CustodyObjectEvidence: ...
    def delete_transport(self, namespace: str, name: str, *,
                         expected_identity: tuple[int, int, int], expected_sha256: str) -> bool: ...


@dataclass(frozen=True)
class CustodyPendingRequest:
    request: CustodyCommitRequest
    request_file_identity: tuple[int, int, int]
    staging_file_identity: tuple[int, int, int] | None


@dataclass(frozen=True)
class CustodyOrphan:
    staging_name: str
    file_identity: tuple[int, int, int]
    byte_length: int
    sha256: str


def _names(backend, namespace, *, capacity):
    # The native method MUST stop after this many entries; it must not build an
    # unbounded list then slice. A sentinel detects overflow without history scans.
    values = backend.bounded_names(namespace, capacity + 1)
    if (not isinstance(values, tuple) or len(values) > capacity
            or len(set(values)) != len(values)):
        raise CustodyCommitIntegrityError("Mailbox namespace exceeds its finite capacity.")
    valid = (lambda name: name == REQUEST_NAME) if namespace == "requests" else (
        lambda name: isinstance(name, str) and _STAGE_NAME.fullmatch(name) is not None)
    if any(not valid(name) for name in values):
        raise CustodyCommitIntegrityError("Unknown mailbox namespace entry.")
    return values


class ScienceCustodyMailboxWriter:
    def __init__(self, finalizer: ScienceCustodyFinalizer, *, mailbox_backend: CustodyMailboxBackend):
        if finalizer.backend is not mailbox_backend:
            raise CustodyCommitError("Mailbox and finalizer must share their native policy/lease.")
        self.finalizer = finalizer
        self.backend = mailbox_backend

    def poll_once(self) -> CustodyCommitResult | None:
        names = _names(self.backend, "requests", capacity=1)
        _names(self.backend, "staging", capacity=2)
        if not names:
            return None
        try:
            evidence = self.backend.read_request(REQUEST_NAME, maximum=self.backend.max_request_bytes)
        except FileNotFoundError:
            # Client may have retired the exact receipt between enumeration and
            # opening. No input or outcome is inferred from this transient absence.
            return None
        request = CustodyCommitRequest.from_bytes(evidence.raw, max_bytes=self.backend.max_request_bytes)
        # Finalizer pins and independently verifies the separately staged object.
        # Writer never deletes a request/stage by its mutable pathname.
        return self.finalizer.finalize(request)

    def close(self) -> None:
        self.backend.close()


class ScienceCustodyMailboxClient:
    def __init__(self, *, policy_sha256: str, source_root_identity: str,
                  mailbox_backend: CustodyMailboxBackend,
                  fault_hook: Callable[[str], None] | None = None,
                  trace_hook: Callable[[dict[str, object]], None] | None = None):
        if (policy_sha256 != mailbox_backend.policy_sha256
                or source_root_identity != mailbox_backend.source_root_identity):
            raise CustodyCommitError("Client does not match the native policy binding.")
        self.backend = mailbox_backend
        self.mailbox_backend = mailbox_backend
        self.policy_sha256 = policy_sha256
        self.source_root_identity = source_root_identity
        self._reader = ScienceCustodyFinalizer(mailbox_backend, trace_hook=trace_hook)
        self._fault_hook = fault_hook

    def _fault(self, phase):
        if self._fault_hook is not None:
            self._fault_hook(phase)

    def _request(self):
        if not _names(self.backend, "requests", capacity=1):
            return None
        evidence = self.backend.read_request(REQUEST_NAME, maximum=self.backend.max_request_bytes)
        return CustodyCommitRequest.from_bytes(evidence.raw, max_bytes=self.backend.max_request_bytes), evidence

    def submit(self, *, final_root: str, relative_path: str, raw: bytes,
               crash_after_stage: bool = False) -> CustodyPendingRequest:
        return self._submit(final_root=final_root, relative_path=relative_path, raw=raw,
                            crash_after_stage=crash_after_stage, allowed_orphan=None)

    def _submit(self, *, final_root, relative_path, raw, crash_after_stage, allowed_orphan):
        if not isinstance(raw, bytes) or len(raw) > self.backend.max_artifact_bytes:
            raise CustodyCommitError("Staging input exceeds the configured byte limit.")
        with self.backend.transaction():
            if self._request() is not None:
                raise CustodyCommitPending("The prior request must be reconciled before another publication.")
            stages = _names(self.backend, "staging", capacity=1)
            if stages != (() if allowed_orphan is None else (allowed_orphan.staging_name,)):
                raise CustodyCommitPending("An abandoned stage requires explicit bounded reconciliation.")
            if allowed_orphan is not None:
                self._verify_orphan(allowed_orphan)
            identity = identity_for_artifact(source_root_identity=self.source_root_identity,
                                             final_root=final_root, relative_path=relative_path, raw=raw)
            generation = uuid.uuid4().hex
            request = CustodyCommitRequest(self.policy_sha256, identity, final_root, relative_path,
                                           sha256(raw), sha256(raw), len(raw), generation + ".stage", generation)
            serialized = request.to_bytes()
            if len(serialized) > self.backend.max_request_bytes:
                raise CustodyCommitError("Request exceeds the configured bound.")
            stage = self.backend.create_transport("staging", request.staging_name, raw)
            if stage.raw != raw:
                raise CustodyCommitIntegrityError("Flushed staging readback differs.")
            self._fault("after_stage")
            if crash_after_stage:
                raise CustodyCommitPending("Synthetic crash after durable stage and before request.")
            request_evidence = self.backend.create_transport("requests", REQUEST_NAME, serialized)
            if request_evidence.raw != serialized:
                raise CustodyCommitIntegrityError("Flushed request readback differs.")
            self._fault("after_request")
            return CustodyPendingRequest(request, request_evidence.file_identity, stage.file_identity)

    def recover_pending(self) -> CustodyPendingRequest | None:
        """Inspect existing transport only; never fabricate a new observation."""
        with self.backend.transaction():
            current = self._request()
            stages = _names(self.backend, "staging", capacity=2)
            if current is None:
                # Recovery metadata may itself have been flushed before a
                # crash published its request. Reuse those exact metadata
                # bytes/time; never regenerate an old market observation.
                if len(stages) != 2:
                    return None
                current = self._recover_orphan_receipt_stage(stages)
            request, evidence = current
            try:
                stage = self.backend.read_staged(request.staging_name, maximum=self.backend.max_artifact_bytes)
            except FileNotFoundError:
                # Receipt durable -> stage removed -> process crash -> request
                # remains is a valid cleanup crash boundary. Missing stage is
                # accepted only against the independently verified claim/final.
                if self._reader.lookup(request) is None:
                    raise CustodyCommitPending("Pending staging absent and no exact receipt exists.")
                identity = None
            else:
                if len(stage.raw) != request.byte_length or sha256(stage.raw) != request.staging_sha256:
                    raise CustodyCommitConflict("Recovered staging differs from the pending request.")
                committed = self._reader.lookup(request)
                if (committed is not None
                        and committed.receipt.original_request_sha256 == request.request_digest()
                        and committed.receipt.original_staging_identity != stage.file_identity):
                    raise CustodyCommitConflict("Original receipted staging object was replaced before recovery.")
                identity = stage.file_identity
            return CustodyPendingRequest(request, evidence.file_identity, identity)

    def _recover_orphan_receipt_stage(self, stages):
        candidates = []
        for name in stages:
            stage = self.backend.read_staged(name, maximum=self.backend.max_artifact_bytes)
            try:
                value = strict_json_loads(stage.raw)
            except (ValueError, RecursionError):
                continue
            if value.get("profile") != "SCIENCE_ABANDONED_STAGING_RECEIPT_007_V1":
                continue
            partial = value.get("partial_before")
            if not isinstance(partial, dict) or partial.get("partial_name") not in stages:
                continue
            orphan = CustodyOrphan(partial["partial_name"], tuple(value.get("staging_file_identity", ())),
                                  partial.get("byte_length"), partial.get("sha256"))
            if orphan.staging_name == name:
                continue
            self._verify_orphan(orphan)
            relative = "quarantine-receipts/" + sha256(canonical_json_bytes(partial)) + ".quarantine.json"
            identity = identity_for_artifact(source_root_identity=self.source_root_identity,
                final_root="custody", relative_path=relative, raw=stage.raw)
            request = CustodyCommitRequest(self.policy_sha256, identity, "custody", relative,
                sha256(stage.raw), sha256(stage.raw), len(stage.raw), name, name.removesuffix(".stage"))
            candidates.append(request)
        if len(candidates) != 1:
            raise CustodyCommitPending("Two orphan stages lack one exact recoverable abandonment receipt.")
        request = candidates[0]
        evidence = self.backend.create_transport("requests", REQUEST_NAME, request.to_bytes())
        if evidence.raw != request.to_bytes():
            raise CustodyCommitIntegrityError("Recovered request readback differs.")
        return request, evidence

    def _verify_pending(self, pending):
        if type(pending) is not CustodyPendingRequest:
            raise CustodyCommitError("Expected exact pending transport evidence.")
        current = self._request()
        if (current is None or current[0].to_bytes() != pending.request.to_bytes()
                or current[1].file_identity != pending.request_file_identity):
            raise CustodyCommitConflict("Pending request was replaced or reused; old completion cannot acknowledge it.")

    def read_confirmed(self, root, relative):
        return self._reader.read_confirmed(root, relative)

    def inspect_existing(self, root, relative):
        return self._reader.inspect_existing(root, relative)

    def reconcile(self, pending: CustodyPendingRequest) -> CustodyCommitResult | None:
        """Verify a direct durable receipt; this is not scientific admission."""
        with self.backend.transaction():
            self._verify_pending(pending)
            return self._reader.lookup(pending.request)

    def acknowledge(self, pending: CustodyPendingRequest, result: CustodyCommitResult) -> None:
        """Retire exact transport after caller readback/register/drain (or startup baseline)."""
        with self.backend.transaction():
            self._verify_pending(pending)
            exact = self._reader.lookup(pending.request)
            if exact is None or exact.receipt.to_bytes() != result.receipt.to_bytes():
                raise CustodyCommitIntegrityError("Acknowledgment lacks the exact verified durable receipt.")
            # An orphan receipt may retire only its explicitly bound never-
            # submitted temporary object, after the receipt itself is durable.
            orphan = self._orphan_from_receipt(pending.request)
            if orphan is not None:
                self.backend.delete_transport("staging", orphan.staging_name,
                    expected_identity=orphan.file_identity, expected_sha256=orphan.sha256)
                self._fault("after_orphan_cleanup")
            try:
                stage = self.backend.read_staged(pending.request.staging_name, maximum=self.backend.max_artifact_bytes)
            except FileNotFoundError:
                pass  # exact claim/receipt/final above proves completed cleanup
            else:
                if (pending.staging_file_identity is None or stage.file_identity != pending.staging_file_identity
                        or sha256(stage.raw) != pending.request.staging_sha256):
                    raise CustodyCommitConflict("Pending staging was replaced; cleanup is prohibited.")
                self.backend.delete_transport("staging", pending.request.staging_name,
                    expected_identity=pending.staging_file_identity, expected_sha256=pending.request.staging_sha256)
            self._fault("after_stage_cleanup")
            self.backend.delete_transport("requests", REQUEST_NAME,
                expected_identity=pending.request_file_identity, expected_sha256=pending.request.request_digest())
            self._fault("after_request_cleanup")

    def orphaned_staging(self) -> tuple[CustodyOrphan, ...]:
        """Return at most one never-submitted stage; never traverse old history."""
        with self.backend.transaction():
            if self._request() is not None:
                raise CustodyCommitPending("Reconcile the pending request before orphan inspection.")
            names = _names(self.backend, "staging", capacity=1)
            result = []
            for name in names:
                evidence = self.backend.read_staged(name, maximum=self.backend.max_artifact_bytes)
                result.append(CustodyOrphan(name, evidence.file_identity, len(evidence.raw), sha256(evidence.raw)))
            return tuple(result)

    def _verify_orphan(self, orphan):
        if type(orphan) is not CustodyOrphan or _STAGE_NAME.fullmatch(orphan.staging_name) is None:
            raise CustodyCommitError("Invalid orphan evidence.")
        evidence = self.backend.read_staged(orphan.staging_name, maximum=self.backend.max_artifact_bytes)
        if (evidence.file_identity != orphan.file_identity or len(evidence.raw) != orphan.byte_length
                or sha256(evidence.raw) != orphan.sha256):
            raise CustodyCommitConflict("Orphan object changed before reconciliation.")

    def submit_orphan_receipt(self, orphan: CustodyOrphan, *, observed_at: str) -> CustodyPendingRequest:
        """Persist a new, honestly timed abandonment receipt before temp cleanup.

        This metadata records never-submitted temporary work, not an admitted
        source record or its original observation time. It does not promote raw.
        """
        parse_rfc3339(observed_at, "orphan observed_at")
        partial = {"partial_name": orphan.staging_name, "byte_length": orphan.byte_length,
                   "sha256": orphan.sha256}
        value = {"profile": "SCIENCE_ABANDONED_STAGING_RECEIPT_007_V1",
                 "authority": "RESEARCH_ONLY", "execution_authority": "NONE",
                 "observed_at": observed_at, "classification": "ABANDONED_STAGING_NOT_ADMITTED",
                 "source_admission": "NONE", "partial_before": partial,
                 "staging_file_identity": list(orphan.file_identity),
                 "retention": "METADATA_RECEIPT_BEFORE_EXACT_TEMP_CLEANUP"}
        raw = canonical_json_bytes(value)
        path = "quarantine-receipts/" + sha256(canonical_json_bytes(partial)) + ".quarantine.json"
        return self._submit(final_root="custody", relative_path=path, raw=raw,
                            crash_after_stage=False, allowed_orphan=orphan)

    def _orphan_from_receipt(self, request):
        if request.identity.artifact_role != "QUARANTINE_RECEIPT":
            return None
        final = self.backend.read_trusted(request.final_root, request.final_relative_path,
                                         maximum=self.backend.max_artifact_bytes)
        if final is None:
            raise CustodyCommitIntegrityError("Verified orphan receipt is missing.")
        value = strict_json_loads(final.raw)
        if value.get("profile") != "SCIENCE_ABANDONED_STAGING_RECEIPT_007_V1":
            return None
        partial = value["partial_before"]
        return CustodyOrphan(partial["partial_name"], tuple(value["staging_file_identity"]),
                             partial["byte_length"], partial["sha256"])

    def close(self) -> None:
        self.backend.close()
