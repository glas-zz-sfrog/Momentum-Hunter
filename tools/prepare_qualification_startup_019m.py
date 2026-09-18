"""Stage the S09 Python and Product layout for an offline 019M startup proof."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest().upper()


def copy_bound(source: Path, target: Path, expected: str | None = None) -> dict[str, object]:
    if source.is_symlink() or source.stat().st_file_attributes & 0x400:
        raise ValueError(f"REPARSE_SOURCE:{source}")
    original = digest(source)
    if expected is not None and original != expected.upper():
        raise ValueError(f"SOURCE_HASH_DRIFT:{source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as input_stream, target.open("xb") as output:
        shutil.copyfileobj(input_stream, output)
        output.flush()
        os.fsync(output.fileno())
    if digest(target) != original:
        raise ValueError(f"COPY_HASH_MISMATCH:{target}")
    return {"source": str(source), "target": str(target), "sha256": original,
            "bytes": target.stat().st_size}


def save(path: Path, value: dict[str, object]) -> None:
    with path.open("xb") as output:
        output.write((json.dumps(value, sort_keys=True, indent=2) + "\n").encode("ascii"))
        output.flush()
        os.fsync(output.fileno())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--s09-root", type=Path, required=True)
    parser.add_argument("--product-manifest-sha256", required=True)
    parser.add_argument("--runtime-manifest-sha256", required=True)
    parser.add_argument("--tzdata", type=Path, required=True)
    args = parser.parse_args()

    root = args.destination.resolve()
    if root.exists():
        raise FileExistsError(f"Qualification destination already exists: {root}")
    source_root = args.source_root.resolve(strict=True)
    old_product_path = args.s09_root / "product-successor" / "PRODUCT-MANIFEST.json"
    old_runtime_path = args.s09_root / "PYTHON-RUNTIME-COPY-IDENTITY.json"
    if digest(old_product_path) != args.product_manifest_sha256.upper():
        raise ValueError("S09_PRODUCT_MANIFEST_DRIFT")
    if digest(old_runtime_path) != args.runtime_manifest_sha256.upper():
        raise ValueError("S09_RUNTIME_MANIFEST_DRIFT")
    old_product = json.loads(old_product_path.read_bytes())
    old_runtime = json.loads(old_runtime_path.read_bytes())
    old_install = args.s09_root / "instance" / "install" / "python-base"
    python_base = root / "install" / "python-base"
    venv = root / "install" / "python"
    product = root / "install" / "source"
    root.mkdir(parents=True)
    runtime_rows = []
    for row in old_runtime["files"]:
        relative = Path(row["path"]).relative_to(old_install)
        runtime_rows.append(copy_bound(Path(row["source"]), python_base / relative,
                                       row["sha256"]))
    for filename in ("python.exe", "pythonw.exe"):
        copy_bound(python_base / "Lib" / "venv" / "scripts" / "nt" / filename,
                   venv / "Scripts" / filename)
    with (venv / "pyvenv.cfg").open("x", encoding="ascii") as output:
        output.write(f"home = {python_base}\ninclude-system-site-packages = false\nversion = 3.12.6\n")
        output.flush()
        os.fsync(output.fileno())
    site = venv / "Lib" / "site-packages"
    hook_row = next(row for row in old_product["files"] if row["path"] == "sitecustomize.py")
    hook = copy_bound(source_root / "sitecustomize.py", site / "sitecustomize.py")
    hook["previousSha256"] = hook_row["sha256"]
    tzdata_root = args.tzdata.resolve(strict=True)
    tzdata_rows = []
    for path in sorted(tzdata_root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            tzdata_rows.append(copy_bound(path, site / "tzdata" / path.relative_to(tzdata_root)))
    product_rows = []
    for row in old_product["files"]:
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("PRODUCT_PATH_ESCAPE")
        copied = copy_bound(source_root / relative, product / relative)
        copied["previousSha256"] = row["sha256"]
        product_rows.append(copied)
    save(root / "STARTUP-STAGING-MANIFEST.json", {
        "status": "STAGED_OFFLINE_NOT_PHYSICAL",
        "sourceRoot": str(source_root),
        "s09ProductManifestSha256": digest(old_product_path),
        "s09RuntimeManifestSha256": digest(old_runtime_path),
        "runtimeRows": runtime_rows,
        "productRows": product_rows,
        "hook": hook,
        "tzdataRows": tzdata_rows,
        "venvPython": str(venv / "Scripts" / "python.exe"),
        "venvPythonSha256": digest(venv / "Scripts" / "python.exe"),
        "pyvenvCfgSha256": digest(venv / "pyvenv.cfg"),
        "serviceActions": 0,
        "providerContact": False,
    })
    print(json.dumps({"status": "STAGED_OFFLINE_NOT_PHYSICAL", "root": str(root),
                      "runtimeCount": len(runtime_rows), "productCount": len(product_rows),
                      "tzdataCount": len(tzdata_rows), "hookSha256": hook["sha256"]}))


if __name__ == "__main__":
    main()
