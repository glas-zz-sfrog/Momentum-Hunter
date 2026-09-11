"""Freeze/verify a task 001A review capsule with a detached ZIP checksum.

Source is the complete committed Git blob closure, never ignored worktree state.
Evidence is copied from this task's selected qualification directories. Packages,
temporary staging, environment-variable values and host credential stores are
not collected. A final capsule may bind a prior capsule and include later review
artifacts without changing its frozen source candidate or claiming self-review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.run_approved_environment_tests import environment_descriptor
from tools.verify_shared_runtime_fact_export_001a import (
    BASE, ENVIRONMENT_FINGERPRINT, OWNED, PYTHON_SHA256, ROOT, git, require,
    safe_member, sealed_design, sha256, write_json,
)


def checked_file(path: Path, root: Path, retained_link_identity: tuple[int, int, int] | None = None) -> bytes:
    require(path.resolve(strict=True).is_relative_to(root.resolve(strict=True)), "Evidence path escaped its declared root")
    for part in (path, *path.parents):
        info = part.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT), "Evidence path contains a link/reparse point")
        if part == root:
            break
    before = path.stat()
    identity = (before.st_dev, before.st_ino, before.st_nlink)
    require(stat.S_ISREG(before.st_mode) and (before.st_nlink == 1 or identity == retained_link_identity),
            "Evidence member must be regular and every retained hardlink alias must be accounted for")
    raw = path.read_bytes()
    after = path.stat()
    require((after.st_dev, after.st_ino, after.st_nlink, after.st_size, after.st_mtime_ns)
            == (*identity, before.st_size, before.st_mtime_ns) and len(raw) == before.st_size,
            "Evidence file changed during its read-only byte copy")
    return raw


def retained_runtime_links(paths: list[Path], evidence: Path) -> dict[Path, dict[str, object]]:
    """Retain failed-test hardlink facts as ordinary ZIP bytes, never as links."""
    groups: dict[tuple[int, int], list[tuple[Path, os.stat_result]]] = {}
    for path in paths:
        info = path.lstat()
        if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            groups.setdefault((info.st_dev, info.st_ino), []).append((path, info))
    admitted = {}
    for aliases in groups.values():
        require(all(path.is_relative_to(evidence / "runtime") for path, _ in aliases),
                "Only retained task-runtime hardlinks may be copied")
        require(all(info.st_nlink == len(aliases) for _, info in aliases),
                "A retained hardlink has an unaccounted alias outside selected task evidence")
        names = sorted(path.relative_to(evidence).as_posix() for path, _ in aliases)
        for path, info in aliases:
            admitted[path] = {"identity": (info.st_dev, info.st_ino, info.st_nlink),
                              "manifest": {"sourceHardlinkAliasPaths": names, "sourceHardlinkCount": info.st_nlink,
                                           "custodyForm": "REGULAR_FILE_BYTE_COPY_OF_RETAINED_TEST_HARDLINK"}}
    return admitted


def git_closure(candidate: str) -> list[tuple[str, bytes, dict[str, object]]]:
    entries = []
    for entry in git("ls-tree", "-rz", "--full-tree", candidate).split(b"\0"):
        if not entry:
            continue
        header, raw_path = entry.split(b"\t", 1)
        mode, kind, oid = header.decode("ascii").split()
        require(kind == "blob" and mode in {"100644", "100755"}, "Git closure contains a symlink/submodule or unsupported object")
        name = safe_member(raw_path.decode("utf-8"))
        require(Path(name).name.lower() not in {".env", "credentials.json", "token.json", "tokens.json"}
                and Path(name).suffix.lower() not in {".pem", ".key", ".pfx", ".p12"}, "Credential-like tracked path requires explicit review")
        entries.append((name, oid, mode))
    result = subprocess.run(["git", "-C", str(ROOT), "cat-file", "--batch"],
                            input=("\n".join(oid for _, oid, _ in entries) + "\n").encode("ascii"),
                            capture_output=True, check=False)
    require(result.returncode == 0, "Could not read immutable Git closure")
    offset = 0
    closure = []
    for name, oid, mode in entries:
        header_end = result.stdout.index(b"\n", offset)
        actual_oid, kind, raw_size = result.stdout[offset:header_end].decode("ascii").split()
        require(actual_oid == oid and kind == "blob", "Git batch identity mismatch")
        size = int(raw_size)
        start = header_end + 1
        raw = result.stdout[start:start + size]
        require(len(raw) == size and result.stdout[start + size:start + size + 1] == b"\n", "Git batch framing mismatch")
        offset = start + size + 1
        closure.append((f"source/{name}", raw, {"gitBlob": oid, "gitMode": mode}))
    require(offset == len(result.stdout), "Unexpected trailing Git batch output")
    return closure


def git_object_id(kind: str, raw: bytes) -> str:
    return hashlib.sha1(kind.encode("ascii") + b" " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def source_tree_id(archive: ZipFile, entries: list[dict[str, object]]) -> str:
    """Reconstruct Git trees from the complete archived blob/mode/path closure."""
    root: dict[str, object] = {}
    for item in entries:
        name = item["path"]
        if not name.startswith("source/"):
            continue
        raw = archive.read(name)
        require(git_object_id("blob", raw) == item["gitBlob"], "Source Git blob identity mismatch")
        require(item["gitMode"] in {"100644", "100755"}, "Invalid source Git mode")
        parts = PurePosixPath(name).parts[1:]
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            require(isinstance(node, dict), "Source tree path collision")
        require(parts[-1] not in node, "Duplicate source tree leaf")
        node[parts[-1]] = (item["gitMode"], item["gitBlob"])

    def digest(node: dict[str, object]) -> str:
        rows = []
        for name, value in sorted(node.items(), key=lambda pair: (pair[0] + ("/" if isinstance(pair[1], dict) else "")).encode("utf-8")):
            mode, oid = ("40000", digest(value)) if isinstance(value, dict) else value
            rows.append(mode.encode("ascii") + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(oid))
        return git_object_id("tree", b"".join(rows))
    return digest(root)


def build(args: argparse.Namespace) -> dict[str, object]:
    environment = environment_descriptor()
    require(environment["executableSha256"] == PYTHON_SHA256 and environment["environmentFingerprint"] == ENVIRONMENT_FINGERPRINT,
            "Package builder is not running in the approved environment")
    require(git("rev-parse", "HEAD").decode().strip() == args.candidate_head, "Candidate HEAD drift")
    require(git("rev-parse", f"{args.candidate_head}^{{tree}}").decode().strip() == args.candidate_tree, "Candidate tree mismatch")
    parents = git("show", "-s", "--format=%P", args.candidate_head).decode().strip().split()
    require(parents == [BASE], "Candidate must be one commit with the admitted base as its sole direct parent")
    require(not git("status", "--porcelain").strip(), "Freeze requires a clean task worktree")
    changed = git("diff", "--name-status", BASE, args.candidate_head).decode().splitlines()
    require(len(changed) == len(OWNED) and set(changed) == {f"A\t{name}" for name in OWNED},
            "Frozen diff must contain exactly the five authorized added paths")
    evidence = args.evidence_root.resolve(strict=True)
    require(not evidence.is_relative_to(ROOT) and not ROOT.is_relative_to(evidence), "Evidence must be outside the source checkout")
    package_root = evidence / "packages"
    package_root.mkdir(exist_ok=True)
    output = args.output.resolve()
    require(output.parent == package_root.resolve() and output.suffix.lower() == ".zip", "Output must be a ZIP directly in task evidence/packages")
    require(not output.exists() and not output.with_suffix(".zip.sha256").exists(), "Package output already exists; retain it and choose a new name")
    design = sealed_design(args.v1_design_root)
    members = git_closure(args.candidate_head)
    members.append(("CANDIDATE.commit", git("cat-file", "commit", args.candidate_head), {"origin": "EXACT_GIT_COMMIT_OBJECT"}))
    selected = []
    # Root admission/fingerprint metadata and all command receipts, including failures.
    for path in sorted(evidence.iterdir()):
        if path.is_file() and path.suffix.lower() in {".json", ".md", ".txt", ".sha256"}:
            selected.append(path)
    # Explicit artifact directories only. Never recurse into packages or staging.
    for directory in ("commands", "runtime", "reviews"):
        root = evidence / directory
        if root.exists():
            for current, dirs, files in os.walk(root, followlinks=False):
                for name in dirs:
                    child = Path(current) / name
                    info = child.lstat()
                    require(not child.is_symlink() and not (getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT), "Evidence directory is a link/reparse point")
                dirs[:] = [name for name in dirs if name not in {"__pycache__", "staging"}]
                selected.extend(Path(current) / name for name in files)
    selected = sorted(set(selected))
    retained_links = retained_runtime_links(selected, evidence)
    for path in selected:
        name = safe_member(path.relative_to(evidence).as_posix())
        link = retained_links.get(path)
        raw = checked_file(path, evidence, link["identity"] if link else None)
        origin = {"origin": "TASK_OWNED_EVIDENCE", **(link["manifest"] if link else {})}
        members.append((f"evidence/{name}", raw, origin))
    for item in [*design["entries"], {"path": "artifact-checksums.sha256"}]:
        name = item["path"]
        path = args.v1_design_root / name
        raw = checked_file(path, args.v1_design_root.resolve(strict=True))
        members.append((f"historical-v1-design/{name}", raw, {"origin": "SEALED_HISTORICAL_V1_DESIGN_UNMODIFIED"}))
    prior = None
    if args.prior_package:
        prior_path = args.prior_package.resolve(strict=True)
        require(prior_path.parent == package_root.resolve() and prior_path != output, "Prior package must be a separate task capsule")
        prior = {"name": prior_path.name, "sha256": sha256(prior_path.read_bytes()), "bytes": prior_path.stat().st_size}
    metadata = {"schemaVersion": 1, "task": "ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001A",
                "baseCanonicalHead": BASE, "baseCanonicalTree": git("rev-parse", f"{BASE}^{{tree}}").decode().strip(), "sourceCandidateHead": args.candidate_head,
                "sourceCandidateTree": args.candidate_tree, "sourceCandidateParents": parents, "changedPaths": changed,
                "createdAt": datetime.now(timezone.utc).isoformat(), "environment": environment,
                "sourceClosure": "ALL_COMMITTED_GIT_BLOBS", "sourceFileCount": sum(name.startswith("source/") for name, _, _ in members),
                "evidenceSelection": {"rootMetadataExtensions": [".json", ".md", ".txt", ".sha256"],
                                      "directories": ["commands", "runtime", "reviews"],
                                      "excludedDirectories": ["packages", "__pycache__", "staging"],
                                      "retainedRuntimeHardlinks": "All aliases must be selected and contained; archived/extracted as ordinary byte copies."},
                "sealedV1Design": design, "priorReviewCapsule": prior,
                "reviewStatus": "SEE_INCLUDED_INDEPENDENT_REVIEW_ARTIFACTS; PACKAGING_IS_NOT_ACCEPTANCE",
                "authority": {"canonicalIntegrated": False, "productionInstalled": False, "captureActivated": False,
                              "providerContact": False, "accountOrOrderAuthority": False},
                "rollback": "Nonadoption; retain isolated branch and evidence. No canonical rollback or deletion.",
                "manifestSelfHash": "EXCLUDED; ZIP identity is the detached checksum", "zipSelfHash": "DETACHED_ONLY"}
    metadata_raw = (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode("utf-8")
    members.append(("CANDIDATE.json", metadata_raw, {"origin": "PACKAGE_IDENTITY"}))
    manifest_entries = []
    seen: set[str] = set()
    for name, raw, origin in members:
        safe_member(name)
        require(name.casefold() not in seen, "Duplicate/case-colliding package member")
        seen.add(name.casefold())
        manifest_entries.append({"path": name, "bytes": len(raw), "sha256": sha256(raw), **origin})
    manifest = {"schemaVersion": 1, "entries": manifest_entries,
                "manifestSelfHash": "Not listed; detached ZIP checksum binds this manifest."}
    with ZipFile(output, "x", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for name, raw, _ in members:
            archive.writestr(name, raw)
        archive.writestr("MANIFEST.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    digest = sha256(output.read_bytes())
    checksum = output.with_suffix(".zip.sha256")
    with checksum.open("x", encoding="ascii", newline="\n") as stream:
        stream.write(f"{digest}  {output.name}\n")
    require(sealed_design(args.v1_design_root) == design, "Historical design drifted during packaging")
    require(git("rev-parse", "HEAD").decode().strip() == args.candidate_head and not git("status", "--porcelain").strip(), "Source drifted during packaging")
    return {"status": "PASS", "package": str(output), "sha256": digest,
            "bytes": output.stat().st_size, "checksum": str(checksum), "members": len(members) + 1,
            "sourceCandidateHead": args.candidate_head, "sourceCandidateTree": args.candidate_tree,
            "reviewAcceptanceClaimed": False}


def verify(args: argparse.Namespace) -> dict[str, object]:
    package = args.package.resolve(strict=True)
    expected, name = args.checksum.read_text(encoding="ascii").strip().split("  ", 1)
    require(name == package.name and len(expected) == 64, "Detached checksum does not name this package")
    actual = sha256(package.read_bytes())
    require(actual == expected, "Detached package checksum mismatch")
    extraction = args.extract_root.resolve() if args.extract_root else None
    if extraction:
        require(not extraction.exists() and not extraction.is_relative_to(ROOT) and not ROOT.is_relative_to(extraction), "Extraction requires a new isolated root")
    with ZipFile(package, "r") as archive:
        infos = archive.infolist()
        names = [safe_member(info.filename) for info in infos]
        require(len({name.casefold() for name in names}) == len(names), "Duplicate/case-colliding ZIP members")
        require(all(not info.is_dir() and not stat.S_ISLNK(info.external_attr >> 16) for info in infos), "ZIP contains a directory/link member")
        manifest = json.loads(archive.read("MANIFEST.json"))
        entries = manifest["entries"]
        require(len({item["path"].casefold() for item in entries}) == len(entries), "Duplicate manifest entries")
        require(set(names) == {item["path"] for item in entries} | {"MANIFEST.json"}, "Manifest inventory mismatch")
        for item in entries:
            raw = archive.read(item["path"])
            require(len(raw) == item["bytes"] and sha256(raw) == item["sha256"], f"Manifest bytes mismatch: {item['path']}")
        candidate = json.loads(archive.read("CANDIDATE.json"))
        require(candidate["sourceFileCount"] == sum(name.startswith("source/") for name in names), "Source closure count mismatch")
        require(source_tree_id(archive, entries) == candidate["sourceCandidateTree"], "Complete source Git tree mismatch")
        commit = archive.read("CANDIDATE.commit")
        require(git_object_id("commit", commit) == candidate["sourceCandidateHead"], "Source candidate commit identity mismatch")
        require(commit.splitlines()[0] == f"tree {candidate['sourceCandidateTree']}".encode("ascii"), "Candidate commit does not bind source tree")
        parents = [line[7:].decode("ascii") for line in commit.split(b"\n\n", 1)[0].splitlines() if line.startswith(b"parent ")]
        require(parents == [BASE] and candidate["sourceCandidateParents"] == parents, "Candidate is not a direct child of the admitted base")
        require(len(candidate["changedPaths"]) == len(OWNED)
                and set(candidate["changedPaths"]) == {f"A\t{name}" for name in OWNED}, "Candidate does not declare exactly the five authorized additions")
        if extraction:
            extraction.mkdir(parents=True, exist_ok=False)
            for name in names:
                target = extraction.joinpath(*PurePosixPath(name).parts)
                require(target.resolve().is_relative_to(extraction), "Extraction path escape")
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(archive.read(name))
            for item in entries:
                require(sha256((extraction / item["path"]).read_bytes()) == item["sha256"], "Extracted bytes do not match manifest")
    return {"status": "PASS", "package": str(package), "sha256": actual, "members": len(names),
            "sourceCandidateHead": candidate["sourceCandidateHead"], "sourceCandidateTree": candidate["sourceCandidateTree"],
            "extractedRoot": str(extraction) if extraction else None, "reviewAcceptanceClaimed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    create = modes.add_parser("build")
    create.add_argument("--candidate-head", required=True)
    create.add_argument("--candidate-tree", required=True)
    create.add_argument("--evidence-root", type=Path, required=True)
    create.add_argument("--v1-design-root", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--prior-package", type=Path)
    check = modes.add_parser("verify")
    check.add_argument("--package", type=Path, required=True)
    check.add_argument("--checksum", type=Path, required=True)
    check.add_argument("--extract-root", type=Path)
    for subparser in (create, check):
        subparser.add_argument("--receipt", type=Path, required=True, help="New receipt path; failed receipts are retained.")
    args = parser.parse_args()
    require(not args.receipt.exists(), "Receipt already exists; preserve it and choose another path")
    started = datetime.now(timezone.utc)
    try:
        receipt = build(args) if args.mode == "build" else verify(args)
        code = 0
    except Exception:
        receipt = {"status": "FAIL", "traceback": traceback.format_exc()}
        code = 1
    receipt.update({"command": [sys.executable, *sys.argv], "startedAt": started.isoformat(),
                    "completedAt": datetime.now(timezone.utc).isoformat(), "returnCode": code})
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.receipt, receipt)
    print(json.dumps(receipt))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
