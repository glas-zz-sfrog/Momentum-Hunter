[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("AccessMatrix", "HandleTarget", "DuplicateHandle")]
    [string]$Mode,

    [Parameter(Mandatory = $true)]
    [string]$ResultPath,

    [string]$Root,
    [string]$ActorLabel,
    [string]$ControlPath,
    [string]$ReleasePath,
    [int]$TargetProcessId,
    [Int64]$TargetHandle,
    [string]$ExpectedSha256,
    [int]$TimeoutSeconds = 90
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-ActorIdentity {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    $integrityLine = (whoami.exe /groups | Select-String "Mandatory Label").Line
    $integrity = if ($integrityLine -match "System Mandatory") {
        "SYSTEM"
    } elseif ($integrityLine -match "High Mandatory") {
        "HIGH"
    } elseif ($integrityLine -match "Medium Mandatory") {
        "MEDIUM"
    } elseif ($integrityLine -match "Low Mandatory") {
        "LOW"
    } else {
        "UNKNOWN"
    }
    return [ordered]@{
        name = $identity.Name
        sid = $identity.User.Value
        processId = $PID
        sessionId = (Get-Process -Id $PID).SessionId
        integrity = $integrity
        administrator = $principal.IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator
        )
        authenticationType = $identity.AuthenticationType
    }
}

function Get-Sha256Hex {
    param([byte[]]$Bytes)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha256.ComputeHash($Bytes)
        return ([BitConverter]::ToString($digest)).Replace("-", "")
    } finally {
        $sha256.Dispose()
    }
}

function Write-ProofJson {
    param(
        [Parameter(Mandatory = $true)] [string]$Path,
        [Parameter(Mandatory = $true)] [object]$Value
    )
    $parent = Split-Path -Parent $Path
    if ($parent) {
        [IO.Directory]::CreateDirectory($parent) | Out-Null
    }
    $json = $Value | ConvertTo-Json -Depth 12 -Compress
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json + "`n")
    $stream = [IO.FileStream]::new(
        $Path,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None
    )
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally {
        $stream.Dispose()
    }
}

function Invoke-Attempt {
    param(
        [Parameter(Mandatory = $true)] [scriptblock]$Action
    )
    try {
        & $Action
        return [ordered]@{ allowed = $true; errorType = $null; nativeCode = 0 }
    } catch {
        $native = if ($_.Exception.PSObject.Properties.Name -contains "NativeErrorCode") {
            $_.Exception.NativeErrorCode
        } else {
            $null
        }
        return [ordered]@{
            allowed = $false
            errorType = $_.Exception.GetType().Name
            nativeCode = $native
        }
    }
}

function Invoke-CommandAttempt {
    param(
        [Parameter(Mandatory = $true)] [string]$Executable,
        [Parameter(Mandatory = $true)] [string[]]$Arguments
    )
    try {
        $output = & $Executable @Arguments 2>&1
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            throw [InvalidOperationException]::new(
                "Native command was denied with exit code $exitCode."
            )
        }
        return [ordered]@{ allowed = $true; errorType = $null; nativeCode = 0 }
    } catch {
        return [ordered]@{
            allowed = $false
            errorType = $_.Exception.GetType().Name
            nativeCode = $LASTEXITCODE
        }
    }
}

function Invoke-AccessMatrix {
    if (-not $Root -or -not $ActorLabel) {
        throw "AccessMatrix requires Root and ActorLabel."
    }
    $resolvedRoot = [IO.Path]::GetFullPath($Root)
    $attempts = [ordered]@{}
    $attempts.create = Invoke-Attempt {
        [IO.File]::WriteAllText(
            (Join-Path $resolvedRoot "created.txt"),
            "created",
            [Text.Encoding]::ASCII
        )
    }
    $attempts.overwrite = Invoke-Attempt {
        [IO.File]::WriteAllText(
            (Join-Path $resolvedRoot "seed.txt"),
            "changed",
            [Text.Encoding]::ASCII
        )
    }
    $attempts.append = Invoke-Attempt {
        [IO.File]::AppendAllText(
            (Join-Path $resolvedRoot "seed.txt"),
            "+",
            [Text.Encoding]::ASCII
        )
    }
    $attempts.rename = Invoke-Attempt {
        [IO.File]::Move(
            (Join-Path $resolvedRoot "rename-source.txt"),
            (Join-Path $resolvedRoot "renamed.txt")
        )
    }
    $attempts.delete = Invoke-Attempt {
        [IO.File]::Delete((Join-Path $resolvedRoot "delete-source.txt"))
        if (Test-Path -LiteralPath (Join-Path $resolvedRoot "delete-source.txt")) {
            throw "Delete did not remove the source."
        }
    }
    $attempts.directoryCreate = Invoke-Attempt {
        [IO.Directory]::CreateDirectory((Join-Path $resolvedRoot "created-dir")) |
            Out-Null
    }
    $attempts.committedOverwrite = Invoke-Attempt {
        [IO.File]::WriteAllText(
            (Join-Path $resolvedRoot "committed.json"),
            "changed",
            [Text.Encoding]::ASCII
        )
    }
    $attempts.committedDelete = Invoke-Attempt {
        [IO.File]::Delete((Join-Path $resolvedRoot "committed-delete.json"))
        if (Test-Path -LiteralPath (Join-Path $resolvedRoot "committed-delete.json")) {
            throw "Delete did not remove committed evidence."
        }
    }
    $attempts.partialRename = Invoke-Attempt {
        [IO.File]::Move(
            (Join-Path $resolvedRoot "partial.tmp"),
            (Join-Path $resolvedRoot "partial-moved.tmp")
        )
    }
    $identity = Get-ActorIdentity
    $attempts.aclModification = Invoke-CommandAttempt -Executable "icacls.exe" -Arguments @(
        $resolvedRoot,
        "/grant",
        "*$($identity.sid):(RX)"
    )
    $attempts.ownershipChange = Invoke-CommandAttempt -Executable "icacls.exe" -Arguments @(
        $resolvedRoot,
        "/setowner",
        $identity.name,
        "/C"
    )
    $attempts.postOwnershipGrant = Invoke-CommandAttempt -Executable "icacls.exe" -Arguments @(
        $resolvedRoot,
        "/grant",
        "*$($identity.sid):(OI)(CI)F"
    )
    $attempts.postOwnershipWrite = Invoke-Attempt {
        [IO.File]::WriteAllText(
            (Join-Path $resolvedRoot "post-ownership.txt"),
            "write",
            [Text.Encoding]::ASCII
        )
    }
    $escape = Split-Path -Parent $resolvedRoot
    $junction = Join-Path $resolvedRoot "redirect"
    $attempts.junctionCreate = Invoke-CommandAttempt -Executable "cmd.exe" -Arguments @(
        "/d", "/c", "mklink", "/J", $junction, $escape
    )
    if (Test-Path -LiteralPath $junction) {
        & cmd.exe /d /c rmdir $junction 2>&1 | Out-Null
    }
    $readAllowed = $false
    try {
        [IO.File]::ReadAllBytes((Join-Path $resolvedRoot "readable.txt")) | Out-Null
        $readAllowed = $true
    } catch {
        $readAllowed = $false
    }
    Write-ProofJson -Path $ResultPath -Value ([ordered]@{
        schemaVersion = 1
        profile = "continuous-windows-isolation-actor-v1"
        mode = $Mode
        actor = $ActorLabel
        identity = $identity
        readAllowed = $readAllowed
        attempts = $attempts
    })
}

function Add-DuplicateHandleType {
    if ("MomentumHunter.Isolation.NativeProbe" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @"
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

namespace MomentumHunter.Isolation {
    public sealed class DuplicateResult {
        public bool OpenProcess { get; set; }
        public bool DuplicateHandle { get; set; }
        public bool Read { get; set; }
        public bool Sha256Matches { get; set; }
        public int NativeCode { get; set; }
    }

    public static class NativeProbe {
        private const uint PROCESS_DUP_HANDLE = 0x0040;
        private const uint DUPLICATE_SAME_ACCESS = 0x00000002;

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr GetCurrentProcess();
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool DuplicateHandle(
            IntPtr sourceProcess, IntPtr sourceHandle, IntPtr targetProcess,
            out IntPtr targetHandle, uint access, bool inherit, uint options);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetFilePointerEx(
            IntPtr handle, long distance, out long newPointer, uint method);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool ReadFile(
            IntPtr handle, byte[] buffer, uint count, out uint read, IntPtr overlapped);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr handle);

        public static DuplicateResult Run(
            int processId, long rawHandle, string expectedSha256) {
            var result = new DuplicateResult();
            IntPtr process = OpenProcess(PROCESS_DUP_HANDLE, false, processId);
            if (process == IntPtr.Zero) {
                result.NativeCode = Marshal.GetLastWin32Error();
                return result;
            }
            result.OpenProcess = true;
            try {
                IntPtr duplicate;
                if (!DuplicateHandle(
                    process, new IntPtr(rawHandle), GetCurrentProcess(),
                    out duplicate, 0, false, DUPLICATE_SAME_ACCESS)) {
                    result.NativeCode = Marshal.GetLastWin32Error();
                    return result;
                }
                result.DuplicateHandle = true;
                try {
                    long ignored;
                    if (!SetFilePointerEx(duplicate, 0, out ignored, 0)) {
                        result.NativeCode = Marshal.GetLastWin32Error();
                        return result;
                    }
                    byte[] buffer = new byte[4096];
                    uint read;
                    if (!ReadFile(duplicate, buffer, (uint)buffer.Length, out read, IntPtr.Zero)) {
                        result.NativeCode = Marshal.GetLastWin32Error();
                        return result;
                    }
                    result.Read = true;
                    Array.Resize(ref buffer, (int)read);
                    string actual;
                    using (SHA256 sha256 = SHA256.Create()) {
                        actual = BitConverter.ToString(sha256.ComputeHash(buffer))
                            .Replace("-", String.Empty);
                    }
                    result.Sha256Matches = String.Equals(
                        actual, expectedSha256, StringComparison.OrdinalIgnoreCase);
                    return result;
                } finally {
                    CloseHandle(duplicate);
                }
            } finally {
                CloseHandle(process);
            }
        }
    }
}
"@
}

function Invoke-HandleTarget {
    if (-not $Root -or -not $ControlPath -or -not $ReleasePath) {
        throw "HandleTarget requires Root, ControlPath, and ReleasePath."
    }
    $identity = Get-ActorIdentity
    $bytes = [byte[]]::new(64)
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $random.GetBytes($bytes)
    } finally {
        $random.Dispose()
    }
    $capabilityPath = Join-Path $Root "writer-capability.bin"
    $stream = [IO.FileStream]::new(
        $capabilityPath,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::ReadWrite,
        [IO.FileShare]::None,
        4096,
        [IO.FileOptions]::DeleteOnClose
    )
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
        $stream.Position = 0
        $expected = Get-Sha256Hex -Bytes $bytes
        Write-ProofJson -Path $ControlPath -Value ([ordered]@{
            schemaVersion = 1
            profile = "continuous-windows-isolation-handle-target-v1"
            identity = $identity
            processId = $PID
            handle = $stream.SafeFileHandle.DangerousGetHandle().ToInt64()
            expectedSha256 = $expected
        })
        $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
        while (-not (Test-Path -LiteralPath $ReleasePath)) {
            if ([DateTime]::UtcNow -ge $deadline) {
                throw "Handle target timed out waiting for release."
            }
            Start-Sleep -Milliseconds 100
        }
    } finally {
        [Array]::Clear($bytes, 0, $bytes.Length)
        $stream.Dispose()
    }
    Write-ProofJson -Path $ResultPath -Value ([ordered]@{
        schemaVersion = 1
        profile = "continuous-windows-isolation-handle-target-result-v1"
        identity = $identity
        released = $true
    })
}

function Invoke-DuplicateHandle {
    if ($TargetProcessId -le 0 -or $TargetHandle -le 0 -or -not $ExpectedSha256) {
        throw "DuplicateHandle requires target process, handle, and expected hash."
    }
    Add-DuplicateHandleType
    $probe = [MomentumHunter.Isolation.NativeProbe]::Run(
        $TargetProcessId,
        $TargetHandle,
        $ExpectedSha256
    )
    Write-ProofJson -Path $ResultPath -Value ([ordered]@{
        schemaVersion = 1
        profile = "continuous-windows-isolation-duplicate-handle-v1"
        identity = Get-ActorIdentity
        targetProcessId = $TargetProcessId
        openProcess = $probe.OpenProcess
        duplicateHandle = $probe.DuplicateHandle
        read = $probe.Read
        sha256Matches = $probe.Sha256Matches
        nativeCode = $probe.NativeCode
    })
}

try {
    switch ($Mode) {
        "AccessMatrix" { Invoke-AccessMatrix }
        "HandleTarget" { Invoke-HandleTarget }
        "DuplicateHandle" { Invoke-DuplicateHandle }
    }
} catch {
    $failure = [ordered]@{
        schemaVersion = 1
        profile = "continuous-windows-isolation-actor-failure-v1"
        mode = $Mode
        actor = $ActorLabel
        error = [ordered]@{
            type = $_.Exception.GetType().Name
            message = $_.Exception.Message
            scriptStackTrace = $_.ScriptStackTrace
        }
    }
    try {
        Write-ProofJson -Path $ResultPath -Value $failure
    } catch {
        # The caller also records the scheduled-task result when the result path is inaccessible.
    }
    exit 1
}
