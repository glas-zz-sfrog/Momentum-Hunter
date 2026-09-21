"""Explicit install/setup operation for fixed Architecture-B parents only.

Callers supply an already-approved, pinned installation ancestry. This module
never adjusts privilege, repairs existing security, creates mutable children,
or runs from the Science/Writer publication path.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from momentum_hunter import science_mutable_policy as mutable
from momentum_hunter.windows_science_custody import (
    CustodyRootBinding, DIRECTORY, REPARSE, _Native, _absolute, _path_key,
    _require, _sid,
)


@dataclass(frozen=True)
class MutableParentsProvisioned:
    profile: str
    version: int
    common: CustodyRootBinding
    roots: tuple[CustodyRootBinding, ...]


def provision_mutable_parents(state_root: str, science_sid: str, *,
                              approved_ancestry: tuple[CustodyRootBinding, ...]) -> MutableParentsProvisioned:
    root = _absolute(state_root)
    _sid(science_sid)
    _require(science_sid.startswith("S-1-5-80-") and science_sid != mutable.WRITER,
             "Setup requires the exact accepted Science service SID.")
    expected = {_path_key(root), *(_path_key(p) for p in PureWindowsPath(root).parents)}
    _require(type(approved_ancestry) is tuple
             and all(type(x) is CustodyRootBinding for x in approved_ancestry)
             and len(approved_ancestry) == len(expected)
             and {_path_key(x.path) for x in approved_ancestry} == expected,
             "Setup requires every approved installation ancestor, including state root.")
    native = _Native()
    pinned = []

    def inspect(handle, path):
        info = native.information(handle)
        _require(bool(info.dwFileAttributes & DIRECTORY) and not info.dwFileAttributes & REPARSE,
                 "Setup encountered a reparse or non-directory parent.")
        native.require_path(handle, path)
        return native.security(handle), native.identity(handle)

    try:
        for bound in sorted(approved_ancestry, key=lambda x: len(PureWindowsPath(x.path).parts)):
            path = Path(bound.path)
            handle = native.open(path, directory=True, access=mutable.PARENT_ACCESS, share=3)
            pinned.append((handle, bound))
            sec, identity = inspect(handle, path)
            _require(identity == bound.file_identity and sec.digest == bound.descriptor_sha256
                     and sec.owner == bound.owner_sid and sec.owner != science_sid,
                     "Approved setup ancestry has drifted.")
        result = {}
        for kind in (mutable.COMMON, "owner", "derived", "scratch", "staging", "requests"):
            # No SetSecurityInfo/SetNamedSecurityInfo path exists. Existing
            # incompatible objects fail validation, not an in-place restamp.
            for handle, bound in pinned:
                sec, identity = inspect(handle, handle.path)
                _require(identity == bound.file_identity and sec.digest == bound.descriptor_sha256,
                         "Setup parent changed during provisioning.")
            path = Path(mutable.namespace_path(root, kind))
            native.mkdir(path, mutable.parent_sddl(science_sid, kind))
            handle = native.open(path, directory=True, access=mutable.PARENT_ACCESS, share=3)
            try:
                sec, identity = inspect(handle, path)
                _require(mutable.security_matches(sec, science_sid, kind, directory=True),
                         "Provisioned parent does not match exact Architecture-B security.")
                binding = CustodyRootBinding(kind, str(path), identity, sec.owner, sec.digest)
            except BaseException:
                handle.close()
                raise
            pinned.append((handle, binding))
            result[kind] = binding
        return MutableParentsProvisioned(mutable.PROFILE, mutable.VERSION, result[mutable.COMMON],
                                         tuple(result[k] for k in sorted(mutable.KINDS)))
    finally:
        # Preserve all created resources for the install owner's cleanup plan.
        # Do not erase or repair partial setup after a failed security check.
        errors = []
        for handle, _ in reversed(pinned):
            try:
                handle.close()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise errors[0]
