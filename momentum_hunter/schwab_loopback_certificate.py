from __future__ import annotations

"""Windows-local certificate lifecycle for the Schwab OAuth loopback listener."""

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import threading
import uuid
import webbrowser
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

from momentum_hunter.schwab_oauth_listener import (
    REGISTERED_CALLBACK_HOST,
    REGISTERED_CALLBACK_PATH,
    REGISTERED_CALLBACK_PORT,
    LoopbackListenerConfig,
    OneShotOAuthCallbackListener,
)
from momentum_hunter.schwab_setup import (
    DEFAULT_SECRET_PATH,
    LocalSecretStore,
    SchwabSetupError,
    WindowsDpapiProtector,
)


CERTIFICATE_SCHEMA_VERSION = 1
DEFAULT_CERTIFICATE_ROOT = DEFAULT_SECRET_PATH.parent / "oauth-loopback"
INSTALL_TRUST_CONFIRMATION = "INSTALL_MOMENTUM_HUNTER_LOOPBACK_ROOT"
REMOVE_TRUST_CONFIRMATION = "REMOVE_MOMENTUM_HUNTER_LOOPBACK_ROOT"
ROOT_SUBJECT = "CN=Momentum Hunter Local OAuth Root"
LEAF_SUBJECT = "CN=127.0.0.1"
_BROWSER_PROOF_CODE = "LOCAL-CERTIFICATE-PROOF"
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,95}$")


class LoopbackCertificateError(SchwabSetupError):
    pass


@dataclass(frozen=True)
class LoopbackCertificateMetadata:
    schema_version: int
    version_id: str
    created_at: str
    host: str
    dns_name: str
    root_subject: str
    leaf_subject: str
    root_store_thumbprint_sha1: str
    root_thumbprint_sha256: str
    leaf_thumbprint_sha256: str
    not_before: str
    not_after: str
    current_user_sid: str
    key_protection: str
    trust_status: str

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "LoopbackCertificateMetadata":
        try:
            metadata = cls(
                schema_version=int(payload["schema_version"]),
                version_id=str(payload["version_id"]),
                created_at=str(payload["created_at"]),
                host=str(payload["host"]),
                dns_name=str(payload["dns_name"]),
                root_subject=str(payload["root_subject"]),
                leaf_subject=str(payload["leaf_subject"]),
                root_store_thumbprint_sha1=str(payload["root_store_thumbprint_sha1"]),
                root_thumbprint_sha256=str(payload["root_thumbprint_sha256"]),
                leaf_thumbprint_sha256=str(payload["leaf_thumbprint_sha256"]),
                not_before=str(payload["not_before"]),
                not_after=str(payload["not_after"]),
                current_user_sid=str(payload["current_user_sid"]),
                key_protection=str(payload["key_protection"]),
                trust_status=str(payload.get("trust_status", "STAGED_UNTRUSTED")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LoopbackCertificateError("Loopback certificate metadata is incomplete.") from exc
        if metadata.schema_version != CERTIFICATE_SCHEMA_VERSION:
            raise LoopbackCertificateError("Loopback certificate metadata version is unsupported.")
        _validate_version_id(metadata.version_id)
        if metadata.host != REGISTERED_CALLBACK_HOST or metadata.dns_name != "localhost":
            raise LoopbackCertificateError("Loopback certificate identity does not match the registered callback.")
        return metadata


@dataclass(frozen=True)
class LoopbackCertificateMaterial:
    metadata: LoopbackCertificateMetadata
    version_directory: Path
    certificate_chain_file: Path
    private_key_file: Path
    root_certificate_file: Path
    secret_store_file: Path
    metadata_file: Path


@dataclass(frozen=True)
class LoopbackCertificateVerification:
    status: str
    version_id: str
    host: str
    not_after: str
    days_remaining: int
    windows_trusted: bool
    private_key_encrypted: bool
    tls_handshake_passed: bool
    acl_hardened: bool


@dataclass(frozen=True)
class BrowserCertificateProof:
    status: str
    version_id: str
    host: str
    port: int
    listener_closed: bool
    credentials_loaded: bool = False
    oauth_attempted: bool = False
    broker_connected: bool = False


_GENERATE_CERTIFICATE_SCRIPT = r"""
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Convert-ToPem([string]$Label, [byte[]]$Bytes) {
    $base64 = [Convert]::ToBase64String(
        $Bytes,
        [Base64FormattingOptions]::InsertLineBreaks
    )
    return "-----BEGIN $Label-----`n$base64`n-----END $Label-----`n"
}

$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
$outputDirectory = [IO.Path]::GetFullPath([string]$payload.output_directory)
$password = [string]$payload.private_key_password
$versionId = [string]$payload.version_id
[IO.Directory]::CreateDirectory($outputDirectory) | Out-Null

$rootKey = [Security.Cryptography.RSA]::Create(3072)
$leafKey = [Security.Cryptography.RSA]::Create(2048)
$rootCert = $null
$leafCert = $null
try {
    $now = [DateTimeOffset]::UtcNow
    $rootRequest = [Security.Cryptography.X509Certificates.CertificateRequest]::new(
        "CN=Momentum Hunter Local OAuth Root",
        $rootKey,
        [Security.Cryptography.HashAlgorithmName]::SHA256,
        [Security.Cryptography.RSASignaturePadding]::Pkcs1
    )
    $rootRequest.CertificateExtensions.Add(
        [Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new(
            $true, $false, 0, $true
        )
    )
    $rootUsage = (
        [Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyCertSign -bor
        [Security.Cryptography.X509Certificates.X509KeyUsageFlags]::CrlSign
    )
    $rootRequest.CertificateExtensions.Add(
        [Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new(
            $rootUsage, $true
        )
    )
    $rootRequest.CertificateExtensions.Add(
        [Security.Cryptography.X509Certificates.X509SubjectKeyIdentifierExtension]::new(
            $rootRequest.PublicKey, $false
        )
    )
    $rootCert = $rootRequest.CreateSelfSigned(
        $now.AddDays(-1),
        $now.AddYears(5)
    )

    $leafRequest = [Security.Cryptography.X509Certificates.CertificateRequest]::new(
        "CN=127.0.0.1",
        $leafKey,
        [Security.Cryptography.HashAlgorithmName]::SHA256,
        [Security.Cryptography.RSASignaturePadding]::Pkcs1
    )
    $leafRequest.CertificateExtensions.Add(
        [Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new(
            $false, $false, 0, $true
        )
    )
    $leafUsage = (
        [Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature -bor
        [Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyEncipherment
    )
    $leafRequest.CertificateExtensions.Add(
        [Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new(
            $leafUsage, $true
        )
    )
    $serverAuth = [Security.Cryptography.OidCollection]::new()
    $serverAuth.Add([Security.Cryptography.Oid]::new("1.3.6.1.5.5.7.3.1")) | Out-Null
    $leafRequest.CertificateExtensions.Add(
        [Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]::new(
            $serverAuth, $true
        )
    )
    $san = [Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
    $san.AddIpAddress([Net.IPAddress]::Parse("127.0.0.1"))
    $san.AddDnsName("localhost")
    $leafRequest.CertificateExtensions.Add($san.Build($true))
    $leafRequest.CertificateExtensions.Add(
        [Security.Cryptography.X509Certificates.X509SubjectKeyIdentifierExtension]::new(
            $leafRequest.PublicKey, $false
        )
    )
    [byte[]]$serial = [byte[]]::new(16)
    [Security.Cryptography.RandomNumberGenerator]::Fill($serial)
    $serial[0] = $serial[0] -bor 1
    $leafCert = $leafRequest.Create(
        $rootCert,
        $now.AddMinutes(-5),
        $now.AddDays(365),
        $serial
    )

    $pbe = [Security.Cryptography.PbeParameters]::new(
        [Security.Cryptography.PbeEncryptionAlgorithm]::Aes256Cbc,
        [Security.Cryptography.HashAlgorithmName]::SHA256,
        200000
    )
    $encryptedKey = $leafKey.ExportEncryptedPkcs8PrivateKey($password, $pbe)
    $leafPem = Convert-ToPem "CERTIFICATE" $leafCert.RawData
    $rootPem = Convert-ToPem "CERTIFICATE" $rootCert.RawData
    $keyPem = Convert-ToPem "ENCRYPTED PRIVATE KEY" $encryptedKey

    [IO.File]::WriteAllText(
        [IO.Path]::Combine($outputDirectory, "loopback-cert-chain.pem"),
        $leafPem + $rootPem,
        [Text.Encoding]::ASCII
    )
    [IO.File]::WriteAllText(
        [IO.Path]::Combine($outputDirectory, "loopback-root.pem"),
        $rootPem,
        [Text.Encoding]::ASCII
    )
    [IO.File]::WriteAllText(
        [IO.Path]::Combine($outputDirectory, "loopback-key.pem"),
        $keyPem,
        [Text.Encoding]::ASCII
    )

    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $result = @{
            schema_version = 1
            version_id = $versionId
            created_at = $now.ToString("yyyy-MM-ddTHH:mm:ss.ffffffK")
            host = "127.0.0.1"
            dns_name = "localhost"
            root_subject = $rootCert.Subject
            leaf_subject = $leafCert.Subject
            root_store_thumbprint_sha1 = $rootCert.Thumbprint
            root_thumbprint_sha256 = [Convert]::ToHexString(
                $sha256.ComputeHash($rootCert.RawData)
            )
            leaf_thumbprint_sha256 = [Convert]::ToHexString(
                $sha256.ComputeHash($leafCert.RawData)
            )
            not_before = $leafCert.NotBefore.ToUniversalTime().ToString(
                "yyyy-MM-ddTHH:mm:ss.ffffffK"
            )
            not_after = $leafCert.NotAfter.ToUniversalTime().ToString(
                "yyyy-MM-ddTHH:mm:ss.ffffffK"
            )
            current_user_sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
            key_protection = "AES256_PKCS8_PASSWORD_IN_DPAPI_CURRENT_USER"
            trust_status = "STAGED_UNTRUSTED"
        }
    } finally {
        $sha256.Dispose()
    }
    $result | ConvertTo-Json -Compress
} finally {
    if ($leafCert) { $leafCert.Dispose() }
    if ($rootCert) { $rootCert.Dispose() }
    $leafKey.Dispose()
    $rootKey.Dispose()
}
"""

_TRUST_STATUS_SCRIPT = r"""
$ErrorActionPreference = "Stop"
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
$expectedThumbprint = ([string]$payload.root_thumbprint).Replace(" ", "").ToUpperInvariant()
$expectedSubject = [string]$payload.root_subject
$store = [Security.Cryptography.X509Certificates.X509Store]::new(
    [Security.Cryptography.X509Certificates.StoreName]::Root,
    [Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser
)
try {
    $store.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadOnly)
    $matches = @(
        $store.Certificates | Where-Object {
            $_.Thumbprint.Replace(" ", "").ToUpperInvariant() -eq $expectedThumbprint -and
            $_.Subject -eq $expectedSubject
        }
    )
    @{ trusted = ($matches.Count -eq 1); match_count = $matches.Count } |
        ConvertTo-Json -Compress
} finally {
    $store.Close()
}
"""

_INSTALL_TRUST_SCRIPT = r"""
$ErrorActionPreference = "Stop"
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
$certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::CreateFromPemFile(
    [string]$payload.root_certificate_file
)
$expectedThumbprint = ([string]$payload.root_thumbprint).Replace(" ", "").ToUpperInvariant()
if ($certificate.Thumbprint.Replace(" ", "").ToUpperInvariant() -ne $expectedThumbprint) {
    throw "Root certificate thumbprint does not match staged metadata."
}
$store = [Security.Cryptography.X509Certificates.X509Store]::new(
    [Security.Cryptography.X509Certificates.StoreName]::Root,
    [Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser
)
try {
    $store.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
    $matches = @(
        $store.Certificates | Where-Object {
            $_.Thumbprint.Replace(" ", "").ToUpperInvariant() -eq $expectedThumbprint
        }
    )
    if ($matches.Count -eq 0) {
        $store.Add($certificate)
    }
    @{ installed = $true; thumbprint = $expectedThumbprint } |
        ConvertTo-Json -Compress
} finally {
    $store.Close()
    $certificate.Dispose()
}
"""

_REMOVE_TRUST_SCRIPT = r"""
$ErrorActionPreference = "Stop"
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
$expectedThumbprint = ([string]$payload.root_thumbprint).Replace(" ", "").ToUpperInvariant()
$expectedSubject = [string]$payload.root_subject
$store = [Security.Cryptography.X509Certificates.X509Store]::new(
    [Security.Cryptography.X509Certificates.StoreName]::Root,
    [Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser
)
$removed = 0
try {
    $store.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
    $matches = @(
        $store.Certificates | Where-Object {
            $_.Thumbprint.Replace(" ", "").ToUpperInvariant() -eq $expectedThumbprint -and
            $_.Subject -eq $expectedSubject
        }
    )
    foreach ($match in $matches) {
        $store.Remove($match)
        $removed += 1
    }
    @{ removed = $removed } | ConvertTo-Json -Compress
} finally {
    $store.Close()
}
"""

_HARDEN_ACL_SCRIPT = r"""
$ErrorActionPreference = "Stop"
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
$root = [IO.Path]::GetFullPath([string]$payload.version_directory)
$sid = [Security.Principal.SecurityIdentifier]::new([string]$payload.current_user_sid)
$items = @([IO.DirectoryInfo]::new($root))
$items += @([IO.Directory]::EnumerateDirectories($root, "*", [IO.SearchOption]::AllDirectories) |
    ForEach-Object { [IO.DirectoryInfo]::new($_) })
$files = @([IO.Directory]::EnumerateFiles($root, "*", [IO.SearchOption]::AllDirectories) |
    ForEach-Object { [IO.FileInfo]::new($_) })

foreach ($directory in $items) {
    $security = [Security.AccessControl.DirectorySecurity]::new()
    $security.SetOwner($sid)
    $security.SetAccessRuleProtection($true, $false)
    $inheritance = (
        [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [Security.AccessControl.InheritanceFlags]::ObjectInherit
    )
    $rule = [Security.AccessControl.FileSystemAccessRule]::new(
        $sid,
        [Security.AccessControl.FileSystemRights]::FullControl,
        $inheritance,
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow
    )
    $security.AddAccessRule($rule)
    [IO.FileSystemAclExtensions]::SetAccessControl($directory, $security)
}
foreach ($file in $files) {
    $security = [Security.AccessControl.FileSecurity]::new()
    $security.SetOwner($sid)
    $security.SetAccessRuleProtection($true, $false)
    $rule = [Security.AccessControl.FileSystemAccessRule]::new(
        $sid,
        [Security.AccessControl.FileSystemRights]::FullControl,
        [Security.AccessControl.AccessControlType]::Allow
    )
    $security.AddAccessRule($rule)
    [IO.FileSystemAclExtensions]::SetAccessControl($file, $security)
}
@{ hardened = $true; item_count = ($items.Count + $files.Count) } |
    ConvertTo-Json -Compress
"""

_VERIFY_ACL_SCRIPT = r"""
$ErrorActionPreference = "Stop"
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
$root = [IO.Path]::GetFullPath([string]$payload.version_directory)
$expectedSid = [string]$payload.current_user_sid
$paths = @($root)
$paths += @([IO.Directory]::EnumerateFileSystemEntries(
    $root, "*", [IO.SearchOption]::AllDirectories
))
$protected = $true
$ownerMatches = $true
$onlyExpectedAllowRules = $true
$fullControlPresent = $true
foreach ($path in $paths) {
    $acl = Get-Acl -LiteralPath $path
    if (-not $acl.AreAccessRulesProtected) {
        $protected = $false
    }
    $ownerSid = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
    if ($ownerSid -ne $expectedSid) {
        $ownerMatches = $false
    }
    $rules = @($acl.GetAccessRules(
        $true,
        $true,
        [Security.Principal.SecurityIdentifier]
    ))
    $allowRules = @($rules | Where-Object {
        $_.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow
    })
    if (@($allowRules | Where-Object {
        $_.IdentityReference.Value -ne $expectedSid -or $_.IsInherited
    }).Count -gt 0) {
        $onlyExpectedAllowRules = $false
    }
    $matchingFullControl = @($allowRules | Where-Object {
        $_.IdentityReference.Value -eq $expectedSid -and
        (($_.FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl) -eq
            [Security.AccessControl.FileSystemRights]::FullControl)
    })
    if ($matchingFullControl.Count -eq 0) {
        $fullControlPresent = $false
    }
}
@{
    protected = $protected
    owner_matches = $ownerMatches
    only_expected_allow_rules = $onlyExpectedAllowRules
    full_control_present = $fullControlPresent
    item_count = $paths.Count
} | ConvertTo-Json -Compress
"""


class WindowsLoopbackCertificateManager:
    def __init__(
        self,
        *,
        root_directory: Path = DEFAULT_CERTIFICATE_ROOT,
        protector: WindowsDpapiProtector | None = None,
        powershell_executable: str | None = None,
        powershell_runner: Callable[[str, dict[str, object]], dict[str, object]] | None = None,
    ) -> None:
        self.root_directory = Path(root_directory)
        self.protector = protector or WindowsDpapiProtector()
        self._powershell_executable = powershell_executable
        self._powershell_runner = powershell_runner

    @property
    def versions_directory(self) -> Path:
        return self.root_directory / "versions"

    @property
    def active_file(self) -> Path:
        return self.root_directory / "active.json"

    def stage(self) -> LoopbackCertificateMaterial:
        self._require_windows()
        version_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:12]
        )
        password = secrets.token_urlsafe(48)
        version_directory = self._version_directory(version_id)
        version_directory.mkdir(parents=True, exist_ok=False)
        try:
            payload = {
                "output_directory": str(version_directory),
                "private_key_password": password,
                "version_id": version_id,
            }
            result = self._run_powershell(_GENERATE_CERTIFICATE_SCRIPT, payload)
            metadata = LoopbackCertificateMetadata.from_dict(result)
            material = self._material(metadata)
            LocalSecretStore(
                path=material.secret_store_file,
                protector=self.protector,
            ).save(
                {
                    "version_id": version_id,
                    "private_key_password": password,
                    "leaf_thumbprint_sha256": metadata.leaf_thumbprint_sha256,
                }
            )
            self._write_metadata(material.metadata_file, metadata)
            self._harden_version_acl(material)
            self.verify(version_id, require_windows_trust=False)
            return material
        except Exception:
            self._remove_failed_version(version_directory)
            raise

    def load(self, version_id: str) -> LoopbackCertificateMaterial:
        _validate_version_id(version_id)
        metadata_file = self._version_directory(version_id) / "metadata.json"
        try:
            payload = json.loads(metadata_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LoopbackCertificateError("Loopback certificate metadata cannot be loaded.") from exc
        if not isinstance(payload, dict):
            raise LoopbackCertificateError("Loopback certificate metadata has an invalid shape.")
        metadata = LoopbackCertificateMetadata.from_dict(payload)
        if metadata.version_id != version_id:
            raise LoopbackCertificateError("Loopback certificate metadata identity does not match its directory.")
        material = self._material(metadata)
        for path in (
            material.certificate_chain_file,
            material.private_key_file,
            material.root_certificate_file,
            material.secret_store_file,
        ):
            if not path.is_file():
                raise LoopbackCertificateError("Loopback certificate material is incomplete.")
        return material

    def verify(
        self,
        version_id: str,
        *,
        require_windows_trust: bool,
    ) -> LoopbackCertificateVerification:
        material = self.load(version_id)
        secret = self._load_secret(material)
        password = secret["private_key_password"]
        key_text = material.private_key_file.read_text(encoding="ascii")
        if "BEGIN ENCRYPTED PRIVATE KEY" not in key_text or password in key_text:
            raise LoopbackCertificateError("Loopback private-key encryption proof failed.")
        self._verify_thumbprints(material)
        self._verify_tls_handshake(material, password)
        self._verify_version_acl(material)
        trusted = self.is_trusted(version_id)
        if require_windows_trust and not trusted:
            raise LoopbackCertificateError("Loopback root certificate is not trusted for the current user.")
        now = datetime.now(timezone.utc)
        not_before = _parse_timestamp(material.metadata.not_before)
        not_after = _parse_timestamp(material.metadata.not_after)
        if not_before > now or not_after <= now:
            raise LoopbackCertificateError("Loopback certificate is outside its validity window.")
        days_remaining = max(0, int((not_after - now).total_seconds() // 86400))
        return LoopbackCertificateVerification(
            status="TRUSTED_VERIFIED" if trusted else "STAGED_VERIFIED_UNTRUSTED",
            version_id=version_id,
            host=material.metadata.host,
            not_after=material.metadata.not_after,
            days_remaining=days_remaining,
            windows_trusted=trusted,
            private_key_encrypted=True,
            tls_handshake_passed=True,
            acl_hardened=True,
        )

    def is_trusted(self, version_id: str) -> bool:
        material = self.load(version_id)
        result = self._run_powershell(
            _TRUST_STATUS_SCRIPT,
            {
                "root_thumbprint": material.metadata.root_store_thumbprint_sha1,
                "root_subject": material.metadata.root_subject,
            },
        )
        return result.get("trusted") is True and result.get("match_count") == 1

    def install_trust(
        self,
        version_id: str,
        *,
        confirmation: str,
    ) -> LoopbackCertificateVerification:
        if confirmation != INSTALL_TRUST_CONFIRMATION:
            raise LoopbackCertificateError("Installing loopback trust requires the exact confirmation phrase.")
        material = self.load(version_id)
        self.verify(version_id, require_windows_trust=False)
        try:
            self._run_powershell(
                _INSTALL_TRUST_SCRIPT,
                {
                    "root_certificate_file": str(material.root_certificate_file),
                    "root_thumbprint": material.metadata.root_store_thumbprint_sha1,
                },
            )
            verification = self.verify(version_id, require_windows_trust=True)
            trusted_metadata = replace(
                material.metadata,
                trust_status="TRUSTED_CURRENT_USER_ROOT",
            )
            self._write_metadata(material.metadata_file, trusted_metadata)
            self._harden_version_acl(self._material(trusted_metadata))
            self._verify_version_acl(self._material(trusted_metadata))
            self._write_json_atomic(
                self.active_file,
                {
                    "schema_version": CERTIFICATE_SCHEMA_VERSION,
                    "version_id": version_id,
                    "root_store_thumbprint_sha1": trusted_metadata.root_store_thumbprint_sha1,
                    "activated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception:
            try:
                self._run_powershell(
                    _REMOVE_TRUST_SCRIPT,
                    {
                        "root_thumbprint": material.metadata.root_store_thumbprint_sha1,
                        "root_subject": material.metadata.root_subject,
                    },
                )
            except LoopbackCertificateError:
                pass
            try:
                self._write_metadata(material.metadata_file, material.metadata)
                self._harden_version_acl(material)
            except (OSError, LoopbackCertificateError):
                pass
            raise
        return verification

    def remove_trust(self, version_id: str, *, confirmation: str) -> bool:
        if confirmation != REMOVE_TRUST_CONFIRMATION:
            raise LoopbackCertificateError("Removing loopback trust requires the exact confirmation phrase.")
        material = self.load(version_id)
        self.verify(version_id, require_windows_trust=False)
        result = self._run_powershell(
            _REMOVE_TRUST_SCRIPT,
            {
                "root_thumbprint": material.metadata.root_store_thumbprint_sha1,
                "root_subject": material.metadata.root_subject,
            },
        )
        if self.active_file.is_file():
            try:
                active = json.loads(self.active_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                active = {}
            if isinstance(active, dict) and active.get("version_id") == version_id:
                self.active_file.unlink(missing_ok=True)
        untrusted_metadata = replace(material.metadata, trust_status="STAGED_UNTRUSTED")
        self._write_metadata(material.metadata_file, untrusted_metadata)
        self._harden_version_acl(self._material(untrusted_metadata))
        self._verify_version_acl(self._material(untrusted_metadata))
        return int(result.get("removed", 0)) > 0

    def listener_config(
        self,
        version_id: str,
        *,
        require_windows_trust: bool = True,
        timeout_seconds: float = 120.0,
        test_only_allow_ephemeral_port: bool = False,
    ) -> LoopbackListenerConfig:
        self.verify(version_id, require_windows_trust=require_windows_trust)
        material = self.load(version_id)
        secret = self._load_secret(material)
        return LoopbackListenerConfig(
            certificate_file=material.certificate_chain_file,
            private_key_file=material.private_key_file,
            timeout_seconds=timeout_seconds,
            port=0 if test_only_allow_ephemeral_port else REGISTERED_CALLBACK_PORT,
            test_only_allow_ephemeral_port=test_only_allow_ephemeral_port,
            private_key_password=secret["private_key_password"],
        )

    def list_versions(self) -> tuple[LoopbackCertificateMetadata, ...]:
        if not self.versions_directory.is_dir():
            return ()
        rows: list[LoopbackCertificateMetadata] = []
        for directory in sorted(self.versions_directory.iterdir()):
            if not directory.is_dir() or not _VERSION_PATTERN.fullmatch(directory.name):
                continue
            try:
                rows.append(self.load(directory.name).metadata)
            except LoopbackCertificateError:
                continue
        return tuple(rows)

    def _material(self, metadata: LoopbackCertificateMetadata) -> LoopbackCertificateMaterial:
        version_directory = self._version_directory(metadata.version_id)
        return LoopbackCertificateMaterial(
            metadata=metadata,
            version_directory=version_directory,
            certificate_chain_file=version_directory / "loopback-cert-chain.pem",
            private_key_file=version_directory / "loopback-key.pem",
            root_certificate_file=version_directory / "loopback-root.pem",
            secret_store_file=version_directory / "secret.bin",
            metadata_file=version_directory / "metadata.json",
        )

    def _version_directory(self, version_id: str) -> Path:
        _validate_version_id(version_id)
        versions = self.versions_directory.resolve()
        candidate = (versions / version_id).resolve()
        if candidate.parent != versions:
            raise LoopbackCertificateError("Loopback certificate version path is unsafe.")
        return candidate

    def _load_secret(self, material: LoopbackCertificateMaterial) -> dict[str, str]:
        secret = LocalSecretStore(
            path=material.secret_store_file,
            protector=self.protector,
        ).load()
        if (
            secret.get("version_id") != material.metadata.version_id
            or secret.get("leaf_thumbprint_sha256")
            != material.metadata.leaf_thumbprint_sha256
            or not secret.get("private_key_password")
        ):
            raise LoopbackCertificateError("Loopback certificate secret identity does not match.")
        return secret

    def _verify_thumbprints(self, material: LoopbackCertificateMaterial) -> None:
        chain_text = material.certificate_chain_file.read_text(encoding="ascii")
        leaf_pem = _first_certificate_pem(chain_text)
        root_pem = material.root_certificate_file.read_text(encoding="ascii")
        leaf_hash = _certificate_sha256(leaf_pem)
        root_hash = _certificate_sha256(root_pem)
        if leaf_hash != material.metadata.leaf_thumbprint_sha256:
            raise LoopbackCertificateError("Loopback leaf certificate thumbprint does not match.")
        if root_hash != material.metadata.root_thumbprint_sha256:
            raise LoopbackCertificateError("Loopback root certificate thumbprint does not match.")

    @staticmethod
    def _verify_tls_handshake(
        material: LoopbackCertificateMaterial,
        password: str,
    ) -> None:
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.minimum_version = ssl.TLSVersion.TLSv1_2
        server_context.load_cert_chain(
            certfile=str(material.certificate_chain_file),
            keyfile=str(material.private_key_file),
            password=password,
        )
        client_context = ssl.create_default_context(cafile=str(material.root_certificate_file))
        client_context.minimum_version = ssl.TLSVersion.TLSv1_2
        listening_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listening_socket.settimeout(2.0)
        listening_socket.bind((REGISTERED_CALLBACK_HOST, 0))
        listening_socket.listen(1)
        port = int(listening_socket.getsockname()[1])
        server_errors: list[Exception] = []

        def serve_once() -> None:
            try:
                connection, _address = listening_socket.accept()
                with connection:
                    with server_context.wrap_socket(connection, server_side=True) as secure:
                        secure.settimeout(2.0)
                        if secure.recv(1) != b"x":
                            raise LoopbackCertificateError("Loopback TLS proof received invalid data.")
                        secure.sendall(b"y")
            except Exception as exc:
                server_errors.append(exc)

        thread = threading.Thread(target=serve_once, name="LoopbackCertificateProof", daemon=True)
        thread.start()
        try:
            with socket.create_connection((REGISTERED_CALLBACK_HOST, port), timeout=2.0) as client:
                with client_context.wrap_socket(
                    client,
                    server_hostname=REGISTERED_CALLBACK_HOST,
                ) as secure_client:
                    secure_client.sendall(b"x")
                    if secure_client.recv(1) != b"y":
                        raise LoopbackCertificateError("Loopback TLS proof did not complete.")
        except (OSError, ssl.SSLError) as exc:
            raise LoopbackCertificateError("Loopback TLS certificate verification failed.") from exc
        finally:
            listening_socket.close()
            thread.join(timeout=2.0)
        if thread.is_alive() or server_errors:
            raise LoopbackCertificateError("Loopback TLS certificate verification failed.")

    def _harden_version_acl(self, material: LoopbackCertificateMaterial) -> None:
        result = self._run_powershell(
            _HARDEN_ACL_SCRIPT,
            {
                "version_directory": str(material.version_directory),
                "current_user_sid": material.metadata.current_user_sid,
            },
        )
        if result.get("hardened") is not True or int(result.get("item_count", 0)) < 5:
            raise LoopbackCertificateError(
                "Loopback certificate file permissions could not be hardened."
            )

    def _verify_version_acl(self, material: LoopbackCertificateMaterial) -> None:
        result = self._run_powershell(
            _VERIFY_ACL_SCRIPT,
            {
                "version_directory": str(material.version_directory),
                "current_user_sid": material.metadata.current_user_sid,
            },
        )
        required = (
            result.get("protected") is True,
            result.get("owner_matches") is True,
            result.get("only_expected_allow_rules") is True,
            result.get("full_control_present") is True,
            int(result.get("item_count", 0)) >= 5,
        )
        if not all(required):
            raise LoopbackCertificateError(
                "Loopback certificate file-permission verification failed."
            )

    def _run_powershell(
        self,
        script: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        if self._powershell_runner is not None:
            return self._powershell_runner(script, payload)
        self._require_windows()
        executable = self._powershell_executable or shutil.which("pwsh")
        if not executable:
            raise LoopbackCertificateError("PowerShell 7 is required for local certificate operations.")
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        kwargs: dict[str, object] = {
            "input": json.dumps(payload),
            "text": True,
            "capture_output": True,
            "timeout": 45,
            "check": False,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            completed = subprocess.run(
                [
                    executable,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-EncodedCommand",
                    encoded,
                ],
                **kwargs,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise LoopbackCertificateError("Local certificate operation could not start.") from exc
        if completed.returncode != 0:
            raise LoopbackCertificateError("Local certificate operation failed safely.")
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            raise LoopbackCertificateError("Local certificate operation returned no result.")
        try:
            result = json.loads(lines[-1])
        except json.JSONDecodeError as exc:
            raise LoopbackCertificateError("Local certificate operation returned an invalid result.") from exc
        if not isinstance(result, dict):
            raise LoopbackCertificateError("Local certificate operation returned an invalid shape.")
        return result

    @staticmethod
    def _write_metadata(path: Path, metadata: LoopbackCertificateMetadata) -> None:
        WindowsLoopbackCertificateManager._write_json_atomic(path, asdict(metadata))

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _remove_failed_version(self, version_directory: Path) -> None:
        versions = self.versions_directory.resolve()
        resolved = version_directory.resolve()
        if resolved.parent == versions and resolved.exists():
            shutil.rmtree(resolved)

    @staticmethod
    def _require_windows() -> None:
        if os.name != "nt":
            raise LoopbackCertificateError("Loopback certificate management is available only on Windows.")


def _validate_version_id(version_id: str) -> None:
    if not _VERSION_PATTERN.fullmatch(version_id) or ".." in version_id:
        raise LoopbackCertificateError("Loopback certificate version identifier is invalid.")


def _first_certificate_pem(text: str) -> str:
    match = re.search(
        r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
        text,
        flags=re.DOTALL,
    )
    if not match:
        raise LoopbackCertificateError("Loopback certificate chain is malformed.")
    return match.group(0)


def _certificate_sha256(pem: str) -> str:
    try:
        der = ssl.PEM_cert_to_DER_cert(pem)
    except ValueError as exc:
        raise LoopbackCertificateError("Loopback certificate PEM is invalid.") from exc
    return hashlib.sha256(der).hexdigest().upper()


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LoopbackCertificateError("Loopback certificate timestamp is invalid.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _status_payload(manager: WindowsLoopbackCertificateManager) -> dict[str, object]:
    versions: list[dict[str, object]] = []
    for metadata in manager.list_versions():
        trusted = manager.is_trusted(metadata.version_id)
        versions.append(
            {
                "version_id": metadata.version_id,
                "host": metadata.host,
                "not_after": metadata.not_after,
                "trust_status": "TRUSTED_CURRENT_USER_ROOT" if trusted else "STAGED_UNTRUSTED",
            }
        )
    return {
        "callback": f"https://{REGISTERED_CALLBACK_HOST}:{REGISTERED_CALLBACK_PORT}{REGISTERED_CALLBACK_PATH}",
        "versions": versions,
        "credentials_loaded": False,
        "oauth_attempted": False,
        "broker_connected": False,
    }


def run_browser_certificate_proof(
    manager: WindowsLoopbackCertificateManager,
    version_id: str,
    *,
    browser_opener: Callable[[str], bool] | None = None,
    timeout_seconds: float = 120.0,
    require_windows_trust: bool = True,
    test_only_allow_ephemeral_port: bool = False,
) -> BrowserCertificateProof:
    """Open a synthetic localhost callback to prove browser trust without Schwab access."""
    config = manager.listener_config(
        version_id,
        require_windows_trust=require_windows_trust,
        timeout_seconds=timeout_seconds,
        test_only_allow_ephemeral_port=test_only_allow_ephemeral_port,
    )
    listener = OneShotOAuthCallbackListener(config)
    state = secrets.token_urlsafe(32)
    callback_url = listener.start(expected_state=state)
    proof_url = f"{callback_url}?{urlencode({'code': _BROWSER_PROOF_CODE, 'state': state})}"
    open_browser = browser_opener or (lambda url: webbrowser.open(url, new=2))
    try:
        if not open_browser(proof_url):
            raise LoopbackCertificateError("The local browser certificate proof could not open a browser.")
        callback = listener.wait(timeout_seconds=timeout_seconds + 1.0)
        if callback.authorization_code != _BROWSER_PROOF_CODE:
            raise LoopbackCertificateError("The local browser certificate proof returned an invalid result.")
    finally:
        listener.close()
    if listener.is_running or not _tcp_listener_is_closed(config.host, listener.bound_port):
        raise LoopbackCertificateError("The local browser certificate proof listener did not close safely.")
    return BrowserCertificateProof(
        status="BROWSER_TRUST_PROOF_PASSED",
        version_id=version_id,
        host=config.host,
        port=listener.bound_port,
        listener_closed=True,
    )


def _tcp_listener_is_closed(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return False
    except OSError:
        return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the local Schwab OAuth loopback certificate.")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--stage", action="store_true")
    action.add_argument("--status", action="store_true")
    action.add_argument("--install-trust", metavar="VERSION")
    action.add_argument("--remove-trust", metavar="VERSION")
    action.add_argument("--browser-proof", metavar="VERSION")
    parser.add_argument("--root", type=Path, default=DEFAULT_CERTIFICATE_ROOT)
    parser.add_argument("--confirm-trust-change", default="")
    parser.add_argument("--proof-timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    manager = WindowsLoopbackCertificateManager(root_directory=args.root)
    if args.stage:
        material = manager.stage()
        print(
            json.dumps(
                {
                    "status": "STAGED_VERIFIED_UNTRUSTED",
                    "version_id": material.metadata.version_id,
                    "host": material.metadata.host,
                    "credentials_loaded": False,
                },
                indent=2,
            )
        )
        return 0
    if args.install_trust:
        verification = manager.install_trust(
            args.install_trust,
            confirmation=args.confirm_trust_change,
        )
        print(json.dumps(asdict(verification), indent=2))
        return 0
    if args.remove_trust:
        removed = manager.remove_trust(
            args.remove_trust,
            confirmation=args.confirm_trust_change,
        )
        print(json.dumps({"removed": removed, "version_id": args.remove_trust}, indent=2))
        return 0
    if args.browser_proof:
        proof = run_browser_certificate_proof(
            manager,
            args.browser_proof,
            timeout_seconds=args.proof_timeout,
        )
        print(json.dumps(asdict(proof), indent=2))
        return 0
    print(json.dumps(_status_payload(manager), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
