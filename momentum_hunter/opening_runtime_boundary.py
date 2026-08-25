from __future__ import annotations

"""Authoritative static dependency boundary for the opening runtime."""

import ast
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping


BOUNDARY_SCHEMA = "OpeningRuntimeDependencyClosureV2"
BOUNDARY_POLICY_VERSION = "opening-runtime-dependency-closure-v2"
PACKAGE_ROOT = "momentum_hunter"
ENTRY_MODULES = ("momentum_hunter.automation_supervisor",)
ENTRY_FILES = ("tools/capture_job.py",)
EXPLICIT_RUNTIME_FILES = (
    "tools/capture_job.py",
    "tools/run_capture_job.ps1",
    "requirements.txt",
)
EXPLICIT_DISTRIBUTIONS = {
    "lxml": {
        "reason": "Finviz BeautifulSoup calls select the lxml parser by literal name.",
        "source": "momentum_hunter/providers.py",
    },
    "tzdata": {
        "reason": "Windows zoneinfo resolution requires the packaged IANA database.",
        "source": "momentum_hunter/time_utils.py",
    },
}
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
SUBPROCESS_CALLS = frozenset(
    {
        "subprocess.run",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
    }
)


class OpeningRuntimeBoundaryError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


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
    explicit_distributions: tuple[str, ...]
    outside_surface_imports: tuple[ImportEscape, ...]
    dynamic_import_sites: tuple[SourceSite, ...]
    subprocess_sites: tuple[SourceSite, ...]

    def to_evidence(self) -> dict[str, object]:
        return asdict(self)


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


def _package_module_index(root: Path) -> dict[str, Path]:
    package = root / PACKAGE_ROOT
    if not package.is_dir():
        raise OpeningRuntimeBoundaryError(
            "OPENING_PACKAGE_ROOT_MISSING",
            f"Package root is missing: {package}",
        )
    index: dict[str, Path] = {}
    for path in package.rglob("*.py"):
        module = _module_name(root, path)
        if module:
            index[module] = path
    return index


def _resolve_local_module(root: Path, module_name: str) -> Path | None:
    parts = module_name.split(".")
    if not parts or any(not part.isidentifier() for part in parts):
        return None
    if any(part in IGNORED_WALK_PARTS for part in parts):
        return None
    module_path = root.joinpath(*parts).with_suffix(".py")
    if module_path.is_file():
        return module_path
    package_path = root.joinpath(*parts) / "__init__.py"
    if package_path.is_file():
        return package_path
    return None


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
        current_parts if current_path.name == "__init__.py" else current_parts[:-1]
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
        raise OpeningRuntimeBoundaryError(
            "OPENING_DEPENDENCY_SOURCE_INVALID",
            f"Cannot parse opening dependency source: {path}",
        ) from exc
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
            if absolute == PACKAGE_ROOT or absolute.startswith(f"{PACKAGE_ROOT}."):
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
            if operation in SUBPROCESS_CALLS:
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


def analyze_opening_boundary(repository_root: Path) -> BoundaryInventory:
    root = repository_root.resolve()
    package_index = _package_module_index(root)
    reachable: set[str] = set()
    queue = list(ENTRY_MODULES)
    external_roots: set[str] = set()
    imported_sites: list[tuple[str, int, str]] = []
    dynamic_sites: list[SourceSite] = []
    subprocess_sites: list[SourceSite] = []

    for relative in ENTRY_FILES:
        path = root / relative
        if not path.is_file():
            raise OpeningRuntimeBoundaryError(
                "OPENING_ENTRY_FILE_MISSING",
                f"Opening entry file is missing: {relative}",
            )
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
            raise OpeningRuntimeBoundaryError(
                "OPENING_ENTRY_MODULE_MISSING",
                f"Opening entry module cannot be resolved: {module}",
            )
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
    for relative in EXPLICIT_RUNTIME_FILES:
        if not (root / relative).is_file():
            raise OpeningRuntimeBoundaryError(
                "OPENING_EXPLICIT_FILE_MISSING",
                f"Explicit opening runtime file is missing: {relative}",
            )
    escapes: dict[tuple[str, int, str], ImportEscape] = {}
    for importer, line, imported_name in imported_sites:
        candidates = [imported_name]
        while candidates[-1] and "." in candidates[-1]:
            candidates.append(candidates[-1].rsplit(".", 1)[0])
        resolved = next(
            (
                local
                for name in candidates
                if (local := _resolve_local_module(root, name)) is not None
            ),
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
        current_surface_file_count=len(all_package_paths) + len(EXPLICIT_RUNTIME_FILES),
        reachable_package_count=len(reachable_paths),
        excluded_package_count=len(all_package_paths - reachable_paths),
        reachable_package_files=tuple(sorted(reachable_paths)),
        excluded_package_files=tuple(sorted(all_package_paths - reachable_paths)),
        dependency_closure_files=tuple(sorted(dependency_closure)),
        external_import_roots=tuple(
            sorted(
                name for name in external_roots if name not in sys.stdlib_module_names
            )
        ),
        explicit_distributions=tuple(sorted(EXPLICIT_DISTRIBUTIONS)),
        outside_surface_imports=tuple(escapes[key] for key in sorted(escapes)),
        dynamic_import_sites=tuple(
            sorted(dynamic_sites, key=lambda item: (item.path, item.line, item.operation))
        ),
        subprocess_sites=tuple(
            sorted(
                subprocess_sites,
                key=lambda item: (item.path, item.line, item.operation),
            )
        ),
    )


def require_authoritative_boundary(repository_root: Path) -> BoundaryInventory:
    inventory = analyze_opening_boundary(repository_root)
    if inventory.outside_surface_imports:
        raise OpeningRuntimeBoundaryError(
            "OPENING_DEPENDENCY_IMPORT_ESCAPE",
            "Opening dependency closure contains a local import outside the approved roots.",
            details={
                "imports": [asdict(item) for item in inventory.outside_surface_imports]
            },
        )
    if inventory.dynamic_import_sites:
        raise OpeningRuntimeBoundaryError(
            "OPENING_DYNAMIC_LOADING_UNCLASSIFIED",
            "Opening dependency closure contains unclassified dynamic loading.",
            details={
                "sites": [asdict(item) for item in inventory.dynamic_import_sites]
            },
        )
    return inventory
