"""Exact frozen-source handoff packaging; never builds, adopts or starts a service."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)


def relative(name):
    value = PurePosixPath(name)
    if not name or value.is_absolute() or any(p in ("..", ".") or ":" in p for p in value.parts) or "\\" in name:
        raise ValueError("UNSAFE_PACKAGE_PATH")
    return value


def git(root, *args, input_data=None):
    return subprocess.run(["git", "--no-optional-locks", "-C", str(root), *args],
        input=input_data, check=True, capture_output=True, timeout=60).stdout


def frozen_blobs(source, head):
    entries = []
    for row in git(source, "ls-tree", "-r", "-z", head).split(b"\0"):
        if not row:
            continue
        metadata, name = row.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError("NONREGULAR_SOURCE_TREE_ENTRY")
        entries.append((relative(name.decode()).as_posix(), oid))
    stream = git(source, "cat-file", "--batch", input_data=("\n".join(oid for _, oid in entries) + "\n").encode())
    offset, result = 0, []
    for name, expected in entries:
        end = stream.index(b"\n", offset)
        oid, kind, size = stream[offset:end].decode().split()
        size = int(size)
        raw = stream[end + 1:end + 1 + size]
        offset = end + 1 + size + 1
        if oid != expected or kind != "blob" or len(raw) != size or stream[offset - 1:offset] != b"\n":
            raise ValueError("GIT_BLOB_STREAM_IDENTITY_MISMATCH")
        if hashlib.sha1(b"blob " + str(size).encode() + b"\0" + raw).hexdigest() != oid:
            raise ValueError("GIT_OBJECT_BYTES_MISMATCH")
        result.append((name, oid, raw))
    if offset != len(stream):
        raise ValueError("EXTRA_GIT_BLOB_STREAM_BYTES")
    return result


def extract(archive, destination):
    if destination.exists():
        raise ValueError("NEW_EXTRACTION_ROOT_REQUIRED")
    with zipfile.ZipFile(archive) as incoming:
        names = incoming.namelist()
        if len(names) != len(set(n.casefold() for n in names)):
            raise ValueError("DUPLICATE_PACKAGE_PATH")
        for entry in incoming.infolist():
            relative(entry.filename)
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("PACKAGE_SYMLINK_REJECTED")
        destination.mkdir(parents=True)
        for entry in incoming.infolist():
            if entry.is_dir():
                continue
            path = destination.joinpath(*relative(entry.filename).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output:
                output.write(incoming.read(entry))


def copy_evidence(source, destination):
    for file in sorted(source.rglob("*")):
        if file.is_symlink():
            raise ValueError("EVIDENCE_SYMLINK_REJECTED")
        if not file.is_file():
            continue
        rel = file.relative_to(source)
        if any(part in {"pycache", "__pycache__", "bin", "obj", ".git", "native-temp"} for part in rel.parts):
            continue
        if file.suffix.lower() in {".zip", ".pyc"}:
            continue
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(file.read_bytes())


def prepare(source, stage, head, base, binary, selections):
    if stage.exists() or git(source, "rev-parse", "HEAD").decode().strip() != head:
        raise ValueError("NEW_STAGE_AND_EXACT_FROZEN_HEAD_REQUIRED")
    if git(source, "status", "--porcelain").strip():
        raise ValueError("FROZEN_SOURCE_MUST_BE_CLEAN")
    tree = git(source, "rev-parse", head + "^{tree}").decode().strip()
    checkout = []
    for name, oid, original in frozen_blobs(source, head):
        path = source / name
        if path.is_symlink():
            raise ValueError("SOURCE_SYMLINK_REJECTED")
        physical = path.read_bytes()
        representation = checkout_representation(original, physical)
        target = stage / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(physical)
        checkout.append({"path": name, "gitObjectId": oid, "gitBlobSha256": digest(original), "physicalSha256": digest(physical),
            "representation": representation})
    write(stage / "GIT-CHECKOUT-BYTE-BINDING.json", {"head": head, "tree": tree, "files": checkout,
        "runtimeVerification": "EXACT_PACKAGED_PHYSICAL_BYTES_NO_NORMALIZATION"})
    source_rows = [{"path": p.relative_to(stage / "source").as_posix(), "sha256": digest(p.read_bytes())}
        for p in sorted((stage / "source").rglob("*")) if p.is_file()]
    write(stage / "SOURCE-BYTE-INVENTORY.json", source_rows)
    write(stage / "CANDIDATE.json", {"head": head, "tree": tree, "base": base,
        "sourceArchive": "exact clean physical checkout bound to Git blobs; only explicit checkout line-ending representation permitted",
        "sourceFileCount": len(source_rows)})
    (stage / "EXACT-DIFF.patch").write_bytes(git(source, "diff", "--binary", base, head))
    (stage / "EXACT-DIFF-NAME-STATUS.txt").write_bytes(git(source, "diff", "--name-status", base, head))
    (stage / "binary").mkdir()
    for file in sorted(binary.rglob("*")):
        if file.is_symlink():
            raise ValueError("NATIVE_SYMLINK_REJECTED")
        if file.is_file() and file.suffix.lower() in {".exe", ".dll", ".json"}:
            target = stage / "binary" / file.relative_to(binary)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(file.read_bytes())
    if not (stage / "binary/MomentumHunter.AutomationService.exe").is_file():
        raise ValueError("EXACT_NATIVE_BINARY_REQUIRED")
    for label, location in selections.items():
        relative(label)
        location = Path(location).resolve()
        if location.is_dir():
            copy_evidence(location, stage / "evidence" / label)
        else:
            target = stage / "evidence" / label
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(location.read_bytes())
    return {"status": "PREPARED_NOT_QUALIFIED", "head": head, "tree": tree}


def checkout_representation(original, physical):
    if original == physical:
        return "EXACT_GIT_BLOB"
    if b"\0" not in original and b"\r" not in original and original.replace(b"\n", b"\r\n") == physical:
        return "EXACT_GIT_WINDOWS_CRLF_CHECKOUT"
    raise ValueError("PHYSICAL_SOURCE_NOT_EXACT_ACCEPTED_CHECKOUT")


SECRET_PATTERNS = {
    "PRIVATE_KEY": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "OPENAI_KEY": re.compile(rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{40,}"),
    "GITHUB_TOKEN": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "ALPACA_KEY": re.compile(rb"\bPK[A-Z0-9]{18,}\b"),
    "JWT": re.compile(rb"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"),
    "BEARER": re.compile(rb"(?i)Bearer [A-Za-z0-9._~-]{24,}"),
    "JSON_TOKEN_VALUE": re.compile(rb'(?i)"(?:access_token|refresh_token|client_secret|secret_key)"\s*:\s*"(?!<|REDACTED|null)[^"\s]{16,}"'),
}


# These exact unchanged canonical test files were inspected, not inferred safe
# from their names. Any byte change or different path/rule loses the exception.
REVIEWED_TEST_FIXTURES = {
    "source/tests/test_approved_environment_hard_chew.py": {
        "rule": "PRIVATE_KEY",
        "sha256": {"e4cb1b49a90dded3a64326bd0c6d018fe38d82da87228ec193c9abfc06c63f38", "d5411bfb95251a5c47571bfceb1329c7dbfe06d247e5e933ce772c105e3b306c"},
        "reason": "Scanner-negative test literals; no private-key body.",
    },
    "source/tests/test_schwab_oauth_listener.py": {
        "rule": "PRIVATE_KEY",
        "sha256": {"3429bd1b77eadbf72550d339c529c53742b58d43eccd61f53c968fdecc20fc52", "9893012bee56f540acd01cc4ed62477fc45cd16c30647f3055439b50997f12a5"},
        "reason": "Preexisting public localhost TLS fixture; temporary test directories only.",
    },
    "source/tests/test_schwab_onboarding.py": {
        "rule": "JSON_TOKEN_VALUE",
        "sha256": {"4042bb64d75023a5a58e5582274efeb91ecaacd822c22df8f799ddf95bf4a050", "e4fd3b9cc374dbbf501e3775bd16778cd25f7f32348e0665c428448b2019f810"},
        "reason": "SYNTHETIC-NEW-ACCESS in mocked OAuth response.",
    },
    "source/tests/test_schwab_readonly.py": {
        "rule": "JSON_TOKEN_VALUE",
        "sha256": {"e958e488493bec3e3eff617131eef1906bdf7ace109814f9a28bb15d42179f7f", "55f511420de4e2ea534dd37b94f225cb420000f1f322758fdcbc4cf80a7b0889"},
        "reason": "SYNTHETIC-TOKEN-VALUE redaction fixture.",
    },
    "source/tests/test_schwab_setup.py": {
        "rule": "JSON_TOKEN_VALUE",
        "sha256": {"52730e650f5b2bb107c04796fe623f63322b0a349ab3c06a008e80c08a537c0d", "c7855bdc8b17b4cfe1de5f960fed479d8f2c2e3de1657c69b298d51efb9d3673"},
        "reason": "SYNTHETIC-REFRESH local disposable DPAPI/redaction fixture.",
    },
    "source/tests/test_strategy_science_recorder_contract.py": {
        "rule": "BEARER",
        "sha256": {"3944c97c5f8d2674ba05c6bc653bbb382151cd7204b7b8f736bd8f07d5bf74a5", "2c36040e5e2f5e28afd8cc4cd97a21c537d213372e33566932d0f04537481eb5"},
        "reason": "FAKE-NOT-A-CREDENTIAL rejected recorder input.",
    },
}


def scan(root):
    findings, fixtures, count = [], [], 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("HANDOFF_SYMLINK_REJECTED")
        if not path.is_file():
            continue
        count += 1
        name = path.relative_to(root).as_posix()
        if path.suffix.lower() in {".pfx", ".p12", ".key"} or path.name == ".env":
            findings.append({"path": name, "rule": "PROTECTED_CREDENTIAL_FILE"})
        raw = path.read_bytes()
        for rule, pattern in SECRET_PATTERNS.items():
            if pattern.search(raw):
                reviewed = REVIEWED_TEST_FIXTURES.get(name)
                if reviewed and reviewed["rule"] == rule and digest(raw) in reviewed["sha256"]:
                    fixtures.append({"path": name, "rule": rule, "sha256": digest(raw), "reason": reviewed["reason"]})
                else:
                    findings.append({"path": name, "rule": rule})
    return {"status": "PASS" if not findings else "FAIL", "scannedFiles": count, "findings": findings,
        "reviewedPublicTestFixtures": fixtures,
        "scope": "High-signal private-key/token/credential-file scan; no credential-store reads or provider calls.",
        "limitations": "Not proof against unknown secret formats; source and evidence provenance review is additionally required."}


def seal(stage, archive):
    if archive.exists() or (stage / "MANIFEST.json").exists():
        raise ValueError("NEW_WRITE_ONCE_PACKAGE_REQUIRED")
    candidate = json.loads((stage / "CANDIDATE.json").read_text())
    source_rows = json.loads((stage / "SOURCE-BYTE-INVENTORY.json").read_text())
    actual_source = {p.relative_to(stage / "source").as_posix() for p in (stage / "source").rglob("*") if p.is_file()}
    if actual_source != {item["path"] for item in source_rows}:
        raise ValueError("FROZEN_SOURCE_MEMBERSHIP_CHANGED")
    for item in source_rows:
        if digest((stage / "source" / item["path"]).read_bytes()) != item["sha256"]:
            raise ValueError("FROZEN_SOURCE_BYTES_CHANGED")
    report = scan(stage)
    write(stage / "SANITIZATION.json", report)
    if report["status"] != "PASS":
        raise ValueError("SANITIZATION_BLOCKED_NO_ZIP_EMITTED")
    records = [{"path": p.relative_to(stage).as_posix(), "sha256": digest(p.read_bytes()), "size": p.stat().st_size}
        for p in sorted(stage.rglob("*")) if p.is_file()]
    write(stage / "MANIFEST.json", {"candidate": candidate, "files": records, "count": len(records),
        "excludedSelfInventory": ["MANIFEST.json", "SHA256SUMS.txt"]})
    inventory = records + [{"path": "MANIFEST.json", "sha256": digest((stage / "MANIFEST.json").read_bytes())}]
    with (stage / "SHA256SUMS.txt").open("x", encoding="utf-8", newline="\n") as output:
        output.write("".join(r["sha256"] + "  " + r["path"] + "\n" for r in inventory))
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                output.write(path, path.relative_to(stage).as_posix())
    return {"status": "SEALED", "path": str(archive.resolve()), "sha256": digest(archive.read_bytes()),
        "fileCount": len(records) + 2, "manifestCount": len(records), "sanitization": "PASS"}


def verify(root):
    manifest = json.loads((root / "MANIFEST.json").read_text())
    expected = {r["path"] for r in manifest["files"]} | {"MANIFEST.json", "SHA256SUMS.txt"}
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != expected:
        raise ValueError("MANIFEST_MEMBERSHIP_MISMATCH")
    for record in manifest["files"]:
        raw = root.joinpath(*relative(record["path"]).parts).read_bytes()
        if len(raw) != record["size"] or digest(raw) != record["sha256"]:
            raise ValueError("MANIFEST_BYTE_MISMATCH:" + record["path"])
    for line in (root / "SHA256SUMS.txt").read_text().splitlines():
        sha, name = line.split("  ", 1)
        if digest(root.joinpath(*relative(name).parts).read_bytes()) != sha:
            raise ValueError("CHECKSUM_MISMATCH:" + name)
    report = scan(root)
    if report["status"] != "PASS":
        raise ValueError("EXTRACTED_SANITIZATION_FAILED")
    return {"status": "PASS", "files": len(actual), "manifestCount": manifest["count"], "sanitization": "PASS"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "seal", "extract", "verify", "scan"))
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--head")
    parser.add_argument("--base")
    parser.add_argument("--selections", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare(args.source, args.stage, args.head, args.base, args.binary, json.loads(args.selections.read_text()))
    elif args.action == "seal": result = seal(args.stage, args.archive)
    elif args.action == "extract":
        extract(args.archive, args.stage)
        result = verify(args.stage)
    elif args.action == "verify": result = verify(args.stage)
    else: result = scan(args.stage)
    print(json.dumps(result, indent=2))
    return 1 if result.get("status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
