from __future__ import annotations

"""Offline audit of the approved opening runtime dependency boundary.

This module is deliberately outside the production ``momentum_hunter`` package.
It does not define execution authority; it measures the current V1 surface and
models a possible dependency-closure refinement for review and tests.
"""

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Sequence


PACKAGE_ROOT = "momentum_hunter"
ENTRY_MODULES = ("momentum_hunter.automation_supervisor",)
ENTRY_FILES = ("tools/capture_job.py",)
EXPLICIT_RUNTIME_FILES = (
    "tools/capture_job.py",
    "tools/run_capture_job.ps1",
    "requirements.txt",
)
CURRENT_RUNTIME_PATTERNS = (
    re.compile(r"^momentum_hunter/.+\.py$"),
    re.compile(r"^tools/capture_job\.py$"),
    re.compile(r"^tools/run_capture_job\.ps1$"),
    re.compile(r"^requirements\.txt$"),
)
IGNORED_WALK_PARTS = frozenset(
    {".git", ".venv", "__pycache__", "bin", "obj", "node_modules"}
)
DYNAMIC_IMPORT_CALLS = frozenset(
    {
        "__import__",
        "importlib.import_module",
        "importlib.util.spec_from_file_location",
        "pkgutil.iter_modules",
        "pkgutil.walk_packages",
        "runpy.run_module",
        "runpy.run_path",
    }
)


class BoundaryAuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceSite:
    path: str
    line: int
    operation: str


@dataclass(frozen=True)
class ImportEscape:
    importer: str
    line: int
    imported_module: str
    resolved_path: str


@dataclass(frozen=True)
class BoundaryInventory:
    package_python_count: int
    current_surface_file_count: int
    reachable_package_count: int
    excluded_package_count: int
    reachable_package_files: tuple[str, ...]
    excluded_package_files: tuple[str, ...]
    dependency_closure_files: tuple[str, ...]
    external_import_roots: tuple[str, ...]
    outside_surface_imports: tuple[ImportEscape, ...]
    dynamic_import_sites: tuple[SourceSite, ...]
    subprocess_sites: tuple[SourceSite, ...]


@dataclass(frozen=True)
class _ImportScan:
    package_targets: frozenset[str]
    imported_names: tuple[tuple[str, int], ...]
    external_roots: frozenset[str]
    dynamic_sites: tuple[SourceSite, ...]
    subprocess_sites: tuple[SourceSite, ...]


def _relative(path: Path, root: Path) -> str:
    return PurePosixPath(path.relative_to(root).as_posix()).as_posix()


def _module_name(root: Path, path: Path) -> str | None:
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if not parts or any(not part.isidentifier() for part in parts):
        return None
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def _python_module_index(root: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in root.rglob("*.py"):
        relative_parts = path.relative_to(root).parts
        if any(part in IGNORED_WALK_PARTS for part in relative_parts):
            continue
        module = _module_name(root, path)
        if module:
            index[module] = path
    return index


def _package_module_index(root: Path) -> dict[str, Path]:
    package = root / PACKAGE_ROOT
    if not package.is_dir():
        raise BoundaryAuditError(f"Package root is missing: {package}")
    return {
        module: path
        for module, path in _python_module_index(root).items()
        if module == PACKAGE_ROOT or module.startswith(f"{PACKAGE_ROOT}.")
    }


def _attribute_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _attribute_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _absolute_from_module(
    *,
    current_module: str,
    current_path: Path,
    level: int,
    imported_module: str,
) -> str:
    if level == 0:
        return imported_module
    current_parts = current_module.split(".")
    package_parts = (
        current_parts
        if current_path.name == "__init__.py"
        else current_parts[:-1]
    )
    keep = len(package_parts) - (level - 1)
    if keep < 0:
        return imported_module
    suffix = imported_module.split(".") if imported_module else []
    return ".".join([*package_parts[:keep], *suffix])


def _existing_module_targets(
    name: str,
    aliases: Iterable[str],
    module_index: Mapping[str, Path],
) -> set[str]:
    targets: set[str] = set()
    if name in module_index:
        targets.add(name)
    for alias in aliases:
        candidate = f"{name}.{alias}" if name else alias
        if candidate in module_index:
            targets.add(candidate)
    for target in tuple(targets):
        parts = target.split(".")
        for length in range(1, len(parts)):
            parent = ".".join(parts[:length])
            if parent in module_index:
                targets.add(parent)
    return targets


def _scan_imports(
    *,
    root: Path,
    path: Path,
    module_name: str,
    package_index: Mapping[str, Path],
) -> _ImportScan:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise BoundaryAuditError(f"Cannot parse Python source: {path}") from exc
    package_targets: set[str] = set()
    imported_names: list[tuple[str, int]] = []
    external_roots: set[str] = set()
    dynamic_sites: list[SourceSite] = []
    subprocess_sites: list[SourceSite] = []
    relative_path = _relative(path, root)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.append((alias.name, node.lineno))
                if alias.name == PACKAGE_ROOT or alias.name.startswith(
                    f"{PACKAGE_ROOT}."
                ):
                    package_targets.update(
                        _existing_module_targets(alias.name, (), package_index)
                    )
                else:
                    external_roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            absolute = _absolute_from_module(
                current_module=module_name,
                current_path=path,
                level=node.level,
                imported_module=node.module or "",
            )
            aliases = tuple(alias.name for alias in node.names if alias.name != "*")
            imported_names.append((absolute, node.lineno))
            imported_names.extend(
                (
                    f"{absolute}.{alias}" if absolute else alias,
                    node.lineno,
                )
                for alias in aliases
            )
            if absolute == PACKAGE_ROOT or absolute.startswith(
                f"{PACKAGE_ROOT}."
            ):
                package_targets.update(
                    _existing_module_targets(absolute, aliases, package_index)
                )
            elif absolute:
                external_roots.add(absolute.split(".")[0])
        elif isinstance(node, ast.Call):
            operation = _attribute_name(node.func)
            if operation in DYNAMIC_IMPORT_CALLS:
                dynamic_sites.append(
                    SourceSite(relative_path, node.lineno, operation)
                )
            if operation in {
                "subprocess.run",
                "subprocess.Popen",
                "subprocess.call",
                "subprocess.check_call",
                "subprocess.check_output",
            }:
                subprocess_sites.append(
                    SourceSite(relative_path, node.lineno, operation)
                )
    return _ImportScan(
        package_targets=frozenset(package_targets),
        imported_names=tuple(imported_names),
        external_roots=frozenset(external_roots),
        dynamic_sites=tuple(dynamic_sites),
        subprocess_sites=tuple(subprocess_sites),
    )


def _current_surface_paths(root: Path) -> set[str]:
    paths = {
        _relative(path, root)
        for path in (root / PACKAGE_ROOT).rglob("*.py")
        if path.is_file()
    }
    for relative in EXPLICIT_RUNTIME_FILES:
        path = root / relative
        if not path.is_file():
            raise BoundaryAuditError(f"Explicit runtime file is missing: {relative}")
        paths.add(relative)
    return paths


def analyze_opening_boundary(repository_root: Path) -> BoundaryInventory:
    root = repository_root.resolve()
    package_index = _package_module_index(root)
    all_index = _python_module_index(root)
    current_surface = _current_surface_paths(root)
    reachable: set[str] = set()
    queue = list(ENTRY_MODULES)
    external_roots: set[str] = set()
    imported_sites: list[tuple[str, int, str]] = []
    dynamic_sites: list[SourceSite] = []
    subprocess_sites: list[SourceSite] = []

    for relative in ENTRY_FILES:
        path = root / relative
        scan = _scan_imports(
            root=root,
            path=path,
            module_name=relative.removesuffix(".py").replace("/", "."),
            package_index=package_index,
        )
        queue.extend(scan.package_targets)
        external_roots.update(scan.external_roots)
        imported_sites.extend(
            (relative, line, name) for name, line in scan.imported_names
        )
        dynamic_sites.extend(scan.dynamic_sites)
        subprocess_sites.extend(scan.subprocess_sites)

    while queue:
        module = queue.pop()
        if module in reachable:
            continue
        path = package_index.get(module)
        if path is None:
            continue
        reachable.add(module)
        scan = _scan_imports(
            root=root,
            path=path,
            module_name=module,
            package_index=package_index,
        )
        queue.extend(scan.package_targets - reachable)
        external_roots.update(scan.external_roots)
        relative = _relative(path, root)
        imported_sites.extend(
            (relative, line, name) for name, line in scan.imported_names
        )
        dynamic_sites.extend(scan.dynamic_sites)
        subprocess_sites.extend(scan.subprocess_sites)

    reachable_paths = {_relative(package_index[module], root) for module in reachable}
    dependency_closure = reachable_paths | set(EXPLICIT_RUNTIME_FILES)
    escapes: dict[tuple[str, int, str], ImportEscape] = {}
    for importer, line, imported_name in imported_sites:
        candidates = [imported_name]
        while candidates[-1] and "." in candidates[-1]:
            candidates.append(candidates[-1].rsplit(".", 1)[0])
        resolved = next(
            (all_index[name] for name in candidates if name in all_index),
            None,
        )
        if resolved is None:
            continue
        resolved_relative = _relative(resolved, root)
        if resolved_relative in dependency_closure:
            continue
        key = (importer, line, resolved_relative)
        escapes[key] = ImportEscape(
            importer=importer,
            line=line,
            imported_module=imported_name,
            resolved_path=resolved_relative,
        )

    all_package_paths = {_relative(path, root) for path in package_index.values()}
    return BoundaryInventory(
        package_python_count=len(all_package_paths),
        current_surface_file_count=len(current_surface),
        reachable_package_count=len(reachable_paths),
        excluded_package_count=len(all_package_paths - reachable_paths),
        reachable_package_files=tuple(sorted(reachable_paths)),
        excluded_package_files=tuple(sorted(all_package_paths - reachable_paths)),
        dependency_closure_files=tuple(sorted(dependency_closure)),
        external_import_roots=tuple(
            sorted(root_name for root_name in external_roots if root_name not in sys.stdlib_module_names)
        ),
        outside_surface_imports=tuple(escapes[key] for key in sorted(escapes)),
        dynamic_import_sites=tuple(
            sorted(dynamic_sites, key=lambda item: (item.path, item.line, item.operation))
        ),
        subprocess_sites=tuple(
            sorted(subprocess_sites, key=lambda item: (item.path, item.line, item.operation))
        ),
    )


def dependency_closure_fingerprint(repository_root: Path) -> str:
    root = repository_root.resolve()
    inventory = analyze_opening_boundary(root)
    if inventory.outside_surface_imports:
        raise BoundaryAuditError(
            "Dependency closure contains a local import outside the proposed surface."
        )
    if inventory.dynamic_import_sites:
        raise BoundaryAuditError(
            "Dependency closure contains dynamic loading that requires explicit classification."
        )
    components = []
    for relative in inventory.dependency_closure_files:
        path = root / relative
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        components.append(
            {"path": relative, "sha256": digest, "size": path.stat().st_size}
        )
    payload = json.dumps(
        components,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_current_runtime_path(path: str) -> bool:
    normalized = PurePosixPath(path).as_posix()
    return any(pattern.fullmatch(normalized) for pattern in CURRENT_RUNTIME_PATTERNS)


def _path_class(path: str, dependency_paths: frozenset[str]) -> str:
    normalized = PurePosixPath(path).as_posix()
    if normalized in dependency_paths:
        return "OPENING_DEPENDENCY"
    if normalized.startswith("momentum_hunter/") and normalized.endswith(".py"):
        return "RESEARCH_OR_NONOPENING_PACKAGE"
    if normalized.startswith("src/MomentumHunter.Desktop.Wpf/") or normalized.startswith(
        "src/MomentumHunter.Presentation/"
    ):
        return "WPF_PRESENTATION"
    if normalized.startswith("src/MomentumHunter.AutomationService/"):
        return "SERVICE_SOURCE_REQUIRES_PROMOTION_IF_INSTALLED"
    if normalized.startswith("docs/") or normalized.lower().endswith(".md"):
        return "DOCUMENTATION_GOVERNANCE"
    if normalized.startswith("tests/"):
        return "TEST_ONLY"
    if normalized.startswith("tools/"):
        return "OFFLINE_OR_ADMIN_TOOL"
    return "OTHER_OR_UNKNOWN"


def recent_commit_analysis(repository_root: Path, count: int = 20) -> dict[str, object]:
    root = repository_root.resolve()
    inventory = analyze_opening_boundary(root)
    dependency_paths = frozenset(inventory.dependency_closure_files)
    log = subprocess.run(
        ["git", "log", f"-{count}", "--format=%H%x09%s"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    commits = []
    for line in log:
        commit, _, subject = line.partition("\t")
        names = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.splitlines()
        classes = sorted({_path_class(path, dependency_paths) for path in names})
        current_requires = any(_is_current_runtime_path(path) for path in names)
        closure_requires = any(PurePosixPath(path).as_posix() in dependency_paths for path in names)
        commits.append(
            {
                "commit": commit,
                "subject": subject,
                "changedPaths": names,
                "classes": classes,
                "currentV1PromotionRequired": current_requires,
                "dependencyClosurePromotionRequired": closure_requires,
            }
        )
    return {
        "commitCount": len(commits),
        "currentV1PromotionRequiredCount": sum(
            bool(item["currentV1PromotionRequired"]) for item in commits
        ),
        "dependencyClosurePromotionRequiredCount": sum(
            bool(item["dependencyClosurePromotionRequired"]) for item in commits
        ),
        "gitOnlyUnderCurrentV1Count": sum(
            not bool(item["currentV1PromotionRequired"]) for item in commits
        ),
        "commits": commits,
    }


def _json_default(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--recent-commits", type=int, default=20)
    return parser


def main() -> int:
    args = _parser().parse_args()
    inventory = analyze_opening_boundary(args.repository_root)
    payload = {
        "schemaVersion": "OpeningRuntimeBoundaryAuditV1",
        "authority": "OFFLINE_NONAUTHORITATIVE_AUDIT",
        "inventory": asdict(inventory),
        "prototypeDependencyClosureFingerprint": dependency_closure_fingerprint(
            args.repository_root
        ),
        "recentCommitAnalysis": recent_commit_analysis(
            args.repository_root,
            count=args.recent_commits,
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
