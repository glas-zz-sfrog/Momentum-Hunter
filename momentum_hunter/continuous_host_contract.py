"""Versioned configuration admission for the existing Continuous process host."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Mapping


LIVE = "LIVE_PRODUCTION"
OFFLINE = "OFFLINE_QUALIFICATION"
PROFILE = "research-only-continuous-deployment-v1"
PRODUCTION_ROOTS = (
    Path("C:/ProgramData/MomentumHunter/Automation"),
    Path("C:/ProgramData/MomentumHunter/Continuous"),
    Path("C:/ProgramData/MomentumHunter/ContinuousRuntime"),
    Path("C:/Users/steve/OneDrive/Documents/Investing"),
    Path("C:/Users/steve/OneDrive/Documents/MomentumHunterData"),
)
ROOT_FIELDS = ("installRoot", "runtimeStateRoot", "evidenceRoot", "configRoot", "logRoot", "hostStateRoot")
ROLES = ("writer", "runtime", "science")
SCM_DIRECT = "SCM_DIRECT_SCIENCE_SERVICE_PROCESS"
PROTECTED_SERVICES = ("MomentumHunterAutomation", "MomentumHunterContinuousRuntime", "MomentumHunterContinuousWriter")


class HostConfigurationError(ValueError):
    pass


def canonical_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def host_fingerprint(config: Mapping) -> str:
    return hashlib.sha256(canonical_bytes({k: v for k, v in config.items() if k != "hostFingerprint"})).hexdigest()


def input_mode(config: Mapping) -> str:
    # Qualification targeting is not a legacy/live configuration extension.
    override_keys = [k for k in config if isinstance(k, str) and k.lower() == "qualificationservicetargets"]
    if override_keys:
        if (override_keys != ["qualificationServiceTargets"] or type(config.get("schemaVersion")) is not int
                or config.get("schemaVersion") != 2
                or config.get("inputMode") != OFFLINE):
            raise HostConfigurationError("Service-target override requires explicit offline qualification.")
        reference = config["qualificationServiceTargets"]
        if (not isinstance(reference, dict) or set(reference) != {"manifest", "sha256"}
                or reference["manifest"] != "qualification-targets.json"
                or not isinstance(reference["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", reference["sha256"])
                or any(config.get(k) != "NONE" for k in ("providerAuthority", "paperAuthority", "liveAuthority"))):
            raise HostConfigurationError("Qualification target reference or authority is invalid.")
    # This is a version decoder, not a default for absent or damaged new modes.
    if config.get("schemaVersion") == 1 and "inputMode" not in config and "host" not in config:
        if (config.get("activationProfile") == PROFILE and config.get("mode") == "RESEARCH_ONLY"
                and config.get("runtimeIdentity") == "production-continuous-runtime-v2"
                and config.get("orderCapability") == "UNAVAILABLE"):
            return LIVE
        raise HostConfigurationError("Unrecognized legacy production configuration.")
    if config.get("schemaVersion") != 2 or config.get("inputMode") not in (LIVE, OFFLINE):
        raise HostConfigurationError("Explicit versioned host input mode is required.")
    return config["inputMode"]


def service_names(instance: str) -> dict[str, str]:
    if instance == "production":
        return {role: "MomentumHunterContinuous" + role.title() for role in ROLES}
    if not re.fullmatch(r"qual-[a-z0-9][a-z0-9-]{0,31}", instance):
        raise HostConfigurationError("Qualification instance must use a bounded qual- identity.")
    return {role: "MomentumHunterContinuous-" + instance + "-" + role.title() for role in ROLES}


def absolute_root(value) -> Path:
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise HostConfigurationError("Host roots must be explicit absolute paths.")
    if value.startswith(("\\\\", "//")) or (os.name == "nt" and ":" in value[2:]):
        raise HostConfigurationError("Network/device/alternate-stream roots are forbidden.")
    if any(part.endswith((" ", ".")) or part.upper().split(".")[0] in
           {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}
           for part in Path(value).parts[1:]):
        raise HostConfigurationError("Ambiguous Windows path component.")
    path = Path(value)
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or (ancestor.exists() and getattr(ancestor.lstat(), "st_file_attributes", 0) & 0x400):
            raise HostConfigurationError("Host root contains a reparse redirect.")
    return path.resolve()


def overlaps(a: Path, b: Path) -> bool:
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def installed_source_root(install_root: Path) -> Path:
    """The install tree's read-only source role, shared by plan and admission."""
    return absolute_root(str(install_root / "source"))


def validate_host(config: Mapping, config_path: Path | None = None) -> dict:
    mode = input_mode(config)
    if config.get("schemaVersion") == 1:
        return {"inputMode": LIVE, "instanceId": "production", "legacy": True,
                "services": service_names("production"), "scienceEnabled": False}
    if config.get("hostFingerprint") != host_fingerprint(config):
        raise HostConfigurationError("Host configuration fingerprint mismatch.")
    if any(config.get(k) != v for k, v in {
        "activationProfile": PROFILE, "mode": "RESEARCH_ONLY", "executionAuthority": "NONE",
        "orderCapability": "UNAVAILABLE", "accountReads": "UNAVAILABLE",
        "positionReads": "UNAVAILABLE", "alpacaPaper": "UNAVAILABLE",
        "alpacaLive": "UNAVAILABLE", "shadowExecution": "UNAVAILABLE",
    }.items()):
        raise HostConfigurationError("Host configuration expands authority.")
    host = config.get("host")
    if not isinstance(host, dict) or set(host) != {
        "instanceId", "instanceRoot", "services", "science", "shutdownSeconds"
    }:
        raise HostConfigurationError("Exact host identity/lifecycle descriptor required.")
    instance = host["instanceId"]
    names = service_names(instance)
    raw_science = host.get("science")
    raw_custody = raw_science.get("custodyPolicy") if isinstance(raw_science, dict) else None
    raw_actor = raw_custody.get("actor_profile") if isinstance(raw_custody, dict) else None
    if mode == OFFLINE and raw_actor is not None:
        from momentum_hunter.windows_writer_profile import decode_profile, WriterProfileError
        try:
            actor_profile = decode_profile(raw_actor)
        except WriterProfileError as exc:
            raise HostConfigurationError("Invalid bounded Writer launch profile.") from exc
        expected_writer = names["writer"]
        if actor_profile.writer.service_name != expected_writer:
            raise HostConfigurationError("Bounded Writer must reuse the existing qualification Writer target.")
    if host["services"] != names:
        raise HostConfigurationError("Host service names differ from instance identity.")
    if type(host["shutdownSeconds"]) not in (int, float) or not 10 <= host["shutdownSeconds"] <= 120:
        raise HostConfigurationError("Host shutdown bound must be 10..120 seconds.")
    if mode == LIVE:
        if instance != "production" or config.get("offlineInput") is not None:
            raise HostConfigurationError("Qualification identity cannot select live inputs.")
        # New live descriptors do not implicitly relocate the installed instance.
        if host["science"] != {"enabled": False}:
            raise HostConfigurationError("New live Science activation is not admitted by this host contract.")
        for field, expected in zip(("configRoot", "evidenceRoot", "runtimeStateRoot"), PRODUCTION_ROOTS[:3]):
            if absolute_root(config[field]) != expected.resolve():
                raise HostConfigurationError("Production roots differ from the established instance.")
    else:
        if instance == "production":
            raise HostConfigurationError("Offline qualification cannot own production identity.")
        root = absolute_root(host["instanceRoot"])
        if any(overlaps(root, p.resolve()) for p in PRODUCTION_ROOTS):
            raise HostConfigurationError("Qualification overlaps a production root.")
        roots = {field: absolute_root(config.get(field)) for field in ROOT_FIELDS}
        installed_source = installed_source_root(roots["installRoot"])
        source = absolute_root(__file__).parents[1]
        if overlaps(root, source):
            if source != installed_source:
                raise HostConfigurationError("Qualification overlaps its source checkout.")
            # An installed copy may be contained, but a development checkout may not.
            for parent in (source, *source.parents):
                try:
                    (parent / ".git").lstat()
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise HostConfigurationError("Installed source checkout metadata is unreadable.") from exc
                raise HostConfigurationError("Qualification overlaps its source checkout.")
        science = host["science"]
        if not isinstance(science, dict) or set(science) != {"enabled", "stateRoot", "pollSeconds", "maxItems", "restrictingSid", "principal", "hostingModel", "imageManifestSha256", "custodyPolicy"}:
            raise HostConfigurationError("Science lifecycle descriptor is incomplete.")
        if science["enabled"] is not True:
            raise HostConfigurationError("Qualification requires the Science recorder role.")
        if science["restrictingSid"] != science_service_sid(instance) or science["principal"] != "NT SERVICE\\" + names["science"]:
            raise HostConfigurationError("Science must use its instance-specific restricted and service identities.")
        if science["hostingModel"] != SCM_DIRECT or not isinstance(science["imageManifestSha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", science["imageManifestSha256"]):
            raise HostConfigurationError("Science requires the bound direct SCM image contract.")
        roots["scienceStateRoot"] = absolute_root(science["stateRoot"])
        science_custody_policy(config)
        export = config.get("researchFactExportV2")
        if not isinstance(export, dict) or set(export) != {"exportRoot", "startManifest", "scienceCustodyRoots"}:
            raise HostConfigurationError("Qualification requires a bound V2 session descriptor.")
        roots["exportRoot"] = absolute_root(export["exportRoot"])
        if [absolute_root(p) for p in export["scienceCustodyRoots"]] != [roots["scienceStateRoot"]]:
            raise HostConfigurationError("Science custody root binding mismatch.")
        for name, path in roots.items():
            if path == root or not path.is_relative_to(root):
                raise HostConfigurationError(f"{name} is outside its isolated instance.")
            for other, other_path in roots.items():
                if name != other and overlaps(path, other_path):
                    raise HostConfigurationError(f"Overlapping qualification roots: {name}/{other}.")
        if config_path is not None and not absolute_root(str(config_path)).is_relative_to(roots["configRoot"]):
            raise HostConfigurationError("Configuration file is outside bound config root.")
        if not absolute_root(config["ipcKeyPath"]).is_relative_to(roots["configRoot"]):
            raise HostConfigurationError("Writer IPC key is outside isolated config root.")
        if config_path is not None and absolute_root(str(config_path)) == absolute_root(config["ipcKeyPath"]):
            raise HostConfigurationError("Science nonsecret configuration cannot alias the writer key.")
        if config.get("runtimeIdentity") != instance + "-runtime":
            raise HostConfigurationError("Runtime identity does not belong to qualification instance.")
        if config.get("ipcHost") != "127.0.0.1" or type(config.get("ipcPort")) is not int or not 1024 <= config["ipcPort"] <= 65535 or config["ipcPort"] == 49281:
            raise HostConfigurationError("Qualification must use a distinct loopback IPC endpoint.")
        if any(k in config for k in ("expectedAccountEnding", "credentials", "oauth", "token", "password")):
            raise HostConfigurationError("Offline configuration must not contain provider credentials/identity.")
        offline = config.get("offlineInput")
        if not isinstance(offline, dict) or set(offline) != {"packagePath", "packageSha256", "tickSeconds", "wallPauseSeconds", "maxTicks"}:
            raise HostConfigurationError("Exact retained-input descriptor is required.")
        from momentum_hunter.preserved_provider_replay import EXPECTED_PACKAGE_SHA256
        if offline["packageSha256"] != EXPECTED_PACKAGE_SHA256:
            raise HostConfigurationError("Retained package is not the accepted provider boundary.")
        absolute_root(offline["packagePath"])
        for name, low, high in (("tickSeconds", 1, 300), ("wallPauseSeconds", 0.01, 60), ("maxTicks", 1, 20000)):
            if type(offline[name]) not in (int, float) or not low <= offline[name] <= high:
                raise HostConfigurationError("Offline observation bound invalid: " + name)
        if type(offline["maxTicks"]) is not int:
            raise HostConfigurationError("Offline tick count must be integral.")
        if type(science["maxItems"]) is not int or not 1 <= science["maxItems"] <= 1024:
            raise HostConfigurationError("Science batch bound is invalid.")
        if type(science["pollSeconds"]) not in (int, float) or not 0.01 <= science["pollSeconds"] <= 60:
            raise HostConfigurationError("Science poll interval is invalid.")
    return {"inputMode": mode, "instanceId": instance, "legacy": False, "services": names,
            "scienceEnabled": host["science"].get("enabled") is True}


def install_plan(config: Mapping, config_path: Path, repository: Path, python: Path) -> dict:
    boundary = validate_host(config, config_path)
    if boundary["inputMode"] != OFFLINE:
        raise HostConfigurationError("Qualification planning requires an offline descriptor.")
    install = absolute_root(config["installRoot"])
    source = installed_source_root(install)
    executable = install / "host" / "MomentumHunter.ContinuousServiceHost.exe"
    services = []
    custody_policy = science_custody_policy(config)
    for role in ("writer", "science", "runtime"):
        interpreter = (custody_policy.actor_profile.writer.python_path
            if role == "writer" and custody_policy.actor_profile is not None
            else str(install / "python" / "Scripts" / "python.exe"))
        services.append({"role": role, "name": boundary["services"][role],
            "executable": str(executable), "arguments": ["--role", role, "--repository-root", str(source),
                "--python-executable", interpreter, "--config", str(config_path),
                "--instance", boundary["instanceId"]],
            "dependsOn": [] if role == "writer" else [boundary["services"]["writer" if role == "science" else "science"]],
            "startupMode": "Manual",
            "principal": ("NT AUTHORITY\\LOCAL SERVICE" if role == "writer" else
                          config["host"]["science"]["principal"] if role == "science" else "EXPLICIT_QUALIFICATION_RUNTIME_USER"),
            **({"hostingModel": SCM_DIRECT, "serviceSidType": "RESTRICTED", "requiredPrivileges": ["SeChangeNotifyPrivilege"],
                "imageManifest": str(install / "science-image-manifest.json"),
                "imageManifestSha256": config["host"]["science"]["imageManifestSha256"],
                "productionServiceDenial": {"services": list(PROTECTED_SERVICES), "scienceSid": science_service_sid(boundary["instanceId"]),
                    "denyObservedGrantMask": 0x2018d, "daclOnly": True, "applicationAuthorizedByPlan": False}}
               if role == "science" else {}),
            **({"serviceSidType": "RESTRICTED", "requiredPrivileges": ["SeChangeNotifyPrivilege"],
                "launchProfile": custody_policy.actor_profile.profile,
                "nativeAdmissionBeforeWriterMutation": True,
                "productionApplicationAuthorized": False}
               if role == "writer" and custody_policy.actor_profile is not None else {})})
    return {"profile": "continuous-host-qualification-install-plan-v1", "hostFingerprint": config["hostFingerprint"],
        "sourceRepository": str(repository), "sourcePython": str(python), "services": services,
        "roots": {name: config[name] for name in ROOT_FIELDS}, "scienceRoot": config["host"]["science"]["stateRoot"],
        "environment": {"PYTHONUTF8": "1", "MOMENTUM_HUNTER_CONTINUOUS_SERVICE_MODE": "1",
                        "providerCredentials": "NOT_REQUIRED_OR_PROPAGATED"},
        "permissions": permission_map(config, config_path),
        "startupOrder": ["writer recovery/listen", "Science recovering", "runtime bootstrap/START", "aggregate current-generation readiness"],
        "stopOrder": ["runtime admission stop/drain/close", "Science consume/flush/close", "writer close"],
        "windowsMutation": False, "providerContact": False}


def science_sid(instance: str) -> str:
    """Historical child-token identity; never the direct SCM service identity."""
    service_names(instance)
    digest = hashlib.sha256(("continuous-science-restriction-v1:" + instance).encode("ascii")).digest()
    return "S-1-5-21-" + "-".join(str(int.from_bytes(digest[i:i+4], "little")) for i in range(0, 16, 4))


def science_service_sid(instance: str) -> str:
    name = service_names(instance)["science"]
    digest = hashlib.sha1(name.upper().encode("utf-16-le")).digest()
    return "S-1-5-80-" + "-".join(str(int.from_bytes(digest[i:i+4], "little")) for i in range(0, 20, 4))


def science_custody_policy(config: Mapping):
    """Decode only an explicit host-bound policy; native APIs verify its authority."""
    mode = input_mode(config)
    if mode != OFFLINE:
        if config.get("host", {}).get("science", {}).get("enabled") is True:
            raise HostConfigurationError("Live Science custody activation is not authorized.")
        return None
    from dataclasses import fields
    from momentum_hunter.windows_science_custody import CustodyRootBinding, ScienceCustodyPolicy
    from momentum_hunter.windows_writer_profile import WriterProfileError

    try:
        settings = config["host"]["science"]
        raw = settings["custodyPolicy"]
        expected_fields = {f.name for f in fields(ScienceCustodyPolicy)}
        if type(raw) is not dict or set(raw) not in (expected_fields, expected_fields - {"actor_profile"}):
            raise HostConfigurationError("Exact explicit Science007 policy fields required.")
        values = dict(raw)
        from momentum_hunter.windows_writer_profile import decode_profile
        # Legacy inspection retains its original digest, never launch authority.
        values["actor_profile"] = decode_profile(values.get("actor_profile"))
        for key in ("roots", "ancestors"):
            if type(values[key]) is not list:
                raise HostConfigurationError("Policy bindings must be JSON arrays.")
            bindings = []
            for item in values[key]:
                if type(item) is not dict or set(item) != {f.name for f in fields(CustodyRootBinding)}:
                    raise HostConfigurationError("Exact root/ancestor binding fields required.")
                if type(item["file_identity"]) is not list:
                    raise HostConfigurationError("Root identity must be a JSON array.")
                bindings.append(CustodyRootBinding(**{**item, "file_identity": tuple(item["file_identity"])}))
            values[key] = tuple(bindings)
        for key in ("science_group_sids", "science_privilege_names",
                    "science_enabled_group_sids", "science_enabled_privilege_names"):
            if type(values[key]) is not list:
                raise HostConfigurationError("Policy token inventory must be JSON arrays.")
            values[key] = tuple(values[key])
        policy = ScienceCustodyPolicy(**values)
        if (settings["enabled"] is not True or
                policy.source_root_identity != config["runtimeBuildHash"] or
                policy.science_sid != science_service_sid(config["host"]["instanceId"]) or
                policy.writer_sid != "S-1-5-19"):
            raise HostConfigurationError("Science007 source/account binding differs from installed host.")
        root = absolute_root(settings["stateRoot"])
        for binding in policy.roots:
            if policy.version == 2:
                from momentum_hunter.science_mutable_policy import namespace_path
                expected = absolute_root(namespace_path(str(root), binding.namespace))
            else:
                expected = root / "reader" / "cursors" if binding.namespace == "cursors" else root / binding.namespace
            if absolute_root(binding.path) != expected:
                raise HostConfigurationError("Science007 namespace differs from fixed host custody role.")
        if policy.actor_profile is not None:
            from momentum_hunter.windows_writer_profile import validate_profile_paths
            validate_profile_paths(config, policy.actor_profile)
        return policy
    except (KeyError, TypeError, ValueError, WriterProfileError) as exc:
        raise HostConfigurationError("Invalid host Science007 custody policy.") from exc


def permission_map(config: Mapping, config_path: Path | None = None) -> dict:
    return {
        "runtimeSource": {"path": config["installRoot"], "access": ["READ_REQUIRED"], "write": False},
        "producerPublication": {"path": config["researchFactExportV2"]["exportRoot"], "access": ["READ_REQUIRED"], "write": False},
        "scienceCustodyRoot": {"path": config["host"]["science"]["stateRoot"],
            "access": ["READ_REQUIRED"], "write": False},
        "scienceStorageRoles": {
            binding.namespace: {"path": binding.path, "ownerSid": binding.owner_sid,
                "access": "SCIENCE_MUTABLE_TRANSPORT_ONLY" if binding.namespace in ("staging", "requests", "derived", "owner", "scratch")
                else "WRITER_ONLY" if binding.namespace == "private" else "SCIENCE_READ_AUDIT_ONLY",
                "descriptorSha256": binding.descriptor_sha256}
            for binding in science_custody_policy(config).roots},
        "scienceLogStatus": {"path": str(Path(config["logRoot"]) / "science"),
            "access": ["READ_REQUIRED", "WRITE_REQUIRED", "CREATE_REQUIRED", "DELETE_REQUIRED"]},
        "configuration": {"path": str(config_path) if config_path else None, "access": ["READ_REQUIRED"], "write": False,
            "scope": "EXACT_NONSECRET_FILE_ONLY", "directoryRead": False, "pathProven": config_path is not None},
        "supervisorGenerations": {"path": config["hostStateRoot"], "access": ["READ_REQUIRED"], "write": False},
        "scienceServiceGeneration": {"path": str(Path(config["hostStateRoot"]) / "science"),
            "access": ["READ_REQUIRED", "WRITE_REQUIRED", "CREATE_REQUIRED", "DELETE_REQUIRED"]},
        "writerKey": {"path": config["ipcKeyPath"], "access": ["NOT_REQUIRED"], "read": False, "write": False},
        "runtimeState": {"path": config["runtimeStateRoot"], "access": ["NOT_REQUIRED"], "write": False},
        "writerEvidence": {"path": config["evidenceRoot"], "access": ["NOT_REQUIRED"], "write": False},
        "providerCredentials": {"access": ["NOT_REQUIRED"], "read": False, "write": False},
        "unrelatedNamespace": {"access": ["NOT_REQUIRED"], "write": False},
        "aclPolicy": "Exact protected DACLs; no retained arbitrary explicit ACEs; owner/ancestor mutation denied; verify effective token physically.",
        "sciencePrincipal": config["host"]["science"]["principal"],
        "restrictingSid": config["host"]["science"]["restrictingSid"],
        "indirectAuthority": "No writer key, unrestricted process/token, or inherited non-stdio capability.",
    }



class OfflineNetworkGuard:
    """Process-local denial; the sole socket exception is authenticated writer IPC."""

    def __init__(self, host: str, port: int, role: str):
        self.endpoint = (host, port)
        self.role = role
        self.denied_attempts = 0

    def __call__(self, event, args):
        permitted = True
        if event in ("socket.connect", "socket.bind"):
            permitted = (self.role == ("writer" if event == "socket.bind" else "runtime")
                         and args[1] == self.endpoint)
        elif event == "socket.getaddrinfo":
            permitted = self.role == "runtime" and args[:2] == self.endpoint
        elif event in ("socket.gethostbyname", "socket.gethostbyaddr", "socket.sendto", "socket.sendmsg"):
            permitted = False
        if not permitted:
            self.denied_attempts += 1
            raise PermissionError("OFFLINE_QUALIFICATION denies provider/network activity.")

    def install(self):
        sys.addaudithook(self)


def scrub_provider_environment():
    for key in tuple(os.environ):
        if re.search(r"SCHWAB|FINVIZ|ALPACA|IBKR|MH_CANARY|API_KEY|API_SECRET|OAUTH|ACCESS_TOKEN|REFRESH_TOKEN", key, re.I):
            os.environ.pop(key, None)
