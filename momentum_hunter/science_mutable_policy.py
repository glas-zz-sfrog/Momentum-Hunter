"""Architecture-B fixed-parent and inherited-child contract, not a provisioner.

No runtime privileges, migration, descriptor rewriting or actor admission are
provided here. Version 1 remains a separate contract in windows_science_custody.
"""
from __future__ import annotations

from pathlib import PureWindowsPath

PROFILE = "SCIENCE_MUTABLE_POLICY_V2"
VERSION = 2
OWNER_LEASE_ACCESS = 0x00120081
READER_LOCK_ACCESS = 0x00120083
TRANSPORT_ACCESS = 0x00130083
RECOVERY_ACCESS = 0x00130081
PARENT_ACCESS = 0x00120080
PARENT_CONTROL = 0x9C14
CHILD_CONTROL = 0x8C14
WRITER = "S-1-5-19"
HIGH = "S-1-16-12288"
COMMON = "mutable-common"
KINDS = frozenset({"owner", "derived", "scratch", "staging", "requests"})
CHILD_MASKS = {
    "owner": OWNER_LEASE_ACCESS,
    "derived": READER_LOCK_ACCESS,
    "scratch": TRANSPORT_ACCESS,
    "staging": TRANSPORT_ACCESS,
    "requests": TRANSPORT_ACCESS,
}
RELATIVE_ROOTS = {
    COMMON: "mutable-v2",
    "owner": "mutable-v2/owner-lease",
    "derived": "mutable-v2/reader-lock",
    "scratch": "mutable-v2/transport-scratch",
    "staging": "staging-v2",
    "requests": "requests-v2",
}


def namespace_path(state_root: str, namespace: str) -> str:
    relative = RELATIVE_ROOTS.get(namespace, "reader/cursors" if namespace == "cursors" else namespace)
    return str(PureWindowsPath(state_root) / relative)


def expected_aces(science_sid: str, kind: str, *, directory: bool):
    if kind == COMMON and directory:
        return ((1, 0, 0xD0156, WRITER), (0, 0, 0x20000, "S-1-3-4"),
                (0, 0, 0x1200A1, WRITER), (0, 0, 0x1F01FF, "S-1-5-18"),
                (0, 0, 0x1200A1, science_sid))
    if kind not in KINDS:
        raise ValueError("Unknown Architecture-B object class.")
    writer_child = 0x120080 if kind in {"owner", "derived"} else 0x120089
    child = CHILD_MASKS[kind]
    if directory:
        return ((1, 3, 0xD0156, WRITER), (0, 3, 0x20000, "S-1-3-4"),
                (0, 0, 0x1200A1, WRITER), (0, 9, writer_child, WRITER),
                (0, 3, 0x1F01FF, "S-1-5-18"),
                (0, 0, 0x1200A3, science_sid), (0, 9, child, science_sid))
    return ((1, 16, 0xD0156, WRITER), (0, 16, 0x20000, "S-1-3-4"),
            (0, 16, writer_child, WRITER), (0, 16, 0x1F01FF, "S-1-5-18"),
            (0, 16, child, science_sid))


def parent_sddl(science_sid: str, kind: str) -> str:
    # Setup supplies the owner using its existing authority. Runtime never
    # calls this for a child: NULL security attributes are mandatory there.
    aces = expected_aces(science_sid, kind, directory=True)
    result = f"O:{WRITER}G:{WRITER}D:PAI" + "".join(
        f"({'D' if typ == 1 else 'A'};{''.join(text for bit, text in ((1, 'OI'), (2, 'CI'), (8, 'IO')) if flags & bit)};0x{mask:08X};;;{sid})"
        for typ, flags, mask, sid in aces)
    return result + f"S:AI(ML;{'' if kind == COMMON else 'OICI'};NW;;;HI)"


def security_matches(sec, science_sid: str, kind: str, *, directory: bool) -> bool:
    owner = WRITER if directory else science_sid
    flags = (0 if kind == COMMON else 3) if directory else 16
    return (sec.owner == sec.group == owner
            and sec.control == (PARENT_CONTROL if directory else CHILD_CONTROL)
            and sec.protected is directory
            and sec.aces == expected_aces(science_sid, kind, directory=directory)
            and sec.labels == ((flags, 1, HIGH),))
