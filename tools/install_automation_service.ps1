[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonExe = "",
    [string]$ServiceRoot = "C:\ProgramData\MomentumHunter\Automation",
    [string]$ServiceName = "MomentumHunterAutomation",
    [string]$WakeTaskName = "Momentum Hunter Automation Readiness Wake",
    [ValidatePattern("^(?:[01]\d|2[0-3]):[0-5]\d$")]
    [string]$WakeTime = "08:15",
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole(
        [System.Security.Principal.WindowsBuiltInRole]::Administrator
    )
}

function Resolve-CodexExecutable {
    $nativePackageExecutable = Join-Path $env:APPDATA (
        "npm\node_modules\@openai\codex\node_modules\" +
        "@openai\codex-win32-x64\vendor\x86_64-pc-windows-msvc\" +
        "bin\codex.exe"
    )
    if (Test-Path -LiteralPath $nativePackageExecutable -PathType Leaf) {
        return (Resolve-Path -LiteralPath $nativePackageExecutable).Path
    }
    $command = Get-Command codex.exe -ErrorAction SilentlyContinue
    if (
        $command -and
        $command.Source -notlike "$env:ProgramFiles\WindowsApps\*"
    ) {
        return $command.Source
    }
    return ""
}

function Grant-LogOnAsService {
    param([Parameter(Mandatory)][string]$AccountName)

    if (-not ("MomentumHunter.ServiceAccountRights" -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Principal;

namespace MomentumHunter
{
    public static class ServiceAccountRights
    {
        private const int PolicyLookupNames = 0x00000800;
        private const int PolicyCreateAccount = 0x00000010;

        [StructLayout(LayoutKind.Sequential)]
        private struct LsaObjectAttributes
        {
            public int Length;
            public IntPtr RootDirectory;
            public IntPtr ObjectName;
            public int Attributes;
            public IntPtr SecurityDescriptor;
            public IntPtr SecurityQualityOfService;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct LsaUnicodeString
        {
            public ushort Length;
            public ushort MaximumLength;
            public IntPtr Buffer;
        }

        [DllImport("advapi32.dll")]
        private static extern uint LsaOpenPolicy(
            IntPtr systemName,
            ref LsaObjectAttributes objectAttributes,
            int desiredAccess,
            out IntPtr policyHandle);

        [DllImport("advapi32.dll")]
        private static extern uint LsaAddAccountRights(
            IntPtr policyHandle,
            IntPtr accountSid,
            [MarshalAs(UnmanagedType.LPArray)] LsaUnicodeString[] userRights,
            int countOfRights);

        [DllImport("advapi32.dll")]
        private static extern int LsaNtStatusToWinError(uint status);

        [DllImport("advapi32.dll")]
        private static extern uint LsaClose(IntPtr policyHandle);

        public static void Grant(string accountName, string rightName)
        {
            var sid = (SecurityIdentifier)new NTAccount(accountName).Translate(
                typeof(SecurityIdentifier));
            var sidBytes = new byte[sid.BinaryLength];
            sid.GetBinaryForm(sidBytes, 0);
            var sidPointer = Marshal.AllocHGlobal(sidBytes.Length);
            var rightPointer = Marshal.StringToHGlobalUni(rightName);
            IntPtr policyHandle = IntPtr.Zero;
            try
            {
                Marshal.Copy(sidBytes, 0, sidPointer, sidBytes.Length);
                var attributes = new LsaObjectAttributes
                {
                    Length = Marshal.SizeOf<LsaObjectAttributes>()
                };
                ThrowIfFailed(LsaOpenPolicy(
                    IntPtr.Zero,
                    ref attributes,
                    PolicyLookupNames | PolicyCreateAccount,
                    out policyHandle));
                var rights = new[]
                {
                    new LsaUnicodeString
                    {
                        Buffer = rightPointer,
                        Length = checked((ushort)(rightName.Length * 2)),
                        MaximumLength = checked((ushort)((rightName.Length + 1) * 2))
                    }
                };
                ThrowIfFailed(LsaAddAccountRights(
                    policyHandle,
                    sidPointer,
                    rights,
                    rights.Length));
            }
            finally
            {
                if (policyHandle != IntPtr.Zero)
                {
                    LsaClose(policyHandle);
                }
                Marshal.FreeHGlobal(rightPointer);
                Marshal.FreeHGlobal(sidPointer);
            }
        }

        private static void ThrowIfFailed(uint status)
        {
            if (status != 0)
            {
                throw new Win32Exception(LsaNtStatusToWinError(status));
            }
        }
    }
}
'@
    }

    [MomentumHunter.ServiceAccountRights]::Grant(
        $AccountName,
        "SeServiceLogonRight"
    )
}

$projectPath = (Resolve-Path -LiteralPath $ProjectRoot).Path
if (-not $PythonExe) {
    $PythonExe = Join-Path $projectPath ".venv\Scripts\python.exe"
}
$pythonPath = (Resolve-Path -LiteralPath $PythonExe).Path
$serviceProject = Join-Path $projectPath (
    "src\MomentumHunter.AutomationService\" +
    "MomentumHunter.AutomationService.csproj"
)
if (-not (Test-Path -LiteralPath $serviceProject -PathType Leaf)) {
    throw "Automation service project is missing: $serviceProject"
}
$powershellPath = (
    "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
)
if (-not (Test-Path -LiteralPath $powershellPath -PathType Leaf)) {
    throw "Windows PowerShell is unavailable."
}
$dotnet = Get-Command dotnet -ErrorAction Stop
$serviceAccount = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$serviceSid = (
    [System.Security.Principal.NTAccount]$serviceAccount
).Translate([System.Security.Principal.SecurityIdentifier]).Value
$engineStateDirectory = Join-Path (
    [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::LocalApplicationData
    )
) "MomentumHunter\python-engine-host"
$publishDirectory = Join-Path $ServiceRoot "service"
$manifestPath = Join-Path $ServiceRoot "automation-manifest.json"
$stateDirectory = Join-Path $ServiceRoot "state"
$serviceExecutable = Join-Path (
    $publishDirectory
) "MomentumHunter.AutomationService.exe"
$codexPath = Resolve-CodexExecutable
$canaryAt = (Get-Date).AddMinutes(2)
$canaryLatest = $canaryAt.AddMinutes(15)
$codexCanaryPromptPath = Join-Path (
    $projectPath
) "config\codex-service-canary-prompt.txt"
if (
    $codexPath -and
    -not (Test-Path -LiteralPath $codexCanaryPromptPath -PathType Leaf)
) {
    throw "The Codex service canary prompt is missing."
}
$initialJobs = @(
    [ordered]@{
        jobId = "installation-canary"
        kind = "nonmarket_canary"
        scheduledAt = $canaryAt.ToString("o")
        latestStartAt = $canaryLatest.ToString("o")
        enabled = $true
        timeoutSeconds = 60
    }
)
if ($codexPath) {
    $initialJobs += [ordered]@{
        jobId = "installation-codex-probe"
        kind = "codex_review"
        scheduledAt = $canaryAt.AddSeconds(1).ToString("o")
        latestStartAt = $canaryLatest.ToString("o")
        enabled = $true
        dependsOnJobId = "installation-canary"
        promptPath = $codexCanaryPromptPath
        expectedOutput = "CODEX_SERVICE_READY"
        timeoutSeconds = 180
    }
}
$binaryPath = (
    "`"$serviceExecutable`" " +
    "--repository-root `"$projectPath`" " +
    "--python-executable `"$pythonPath`" " +
    "--manifest `"$manifestPath`""
)

$plan = [ordered]@{
    schemaVersion = 1
    serviceName = $ServiceName
    displayName = "Momentum Hunter Automation Service"
    serviceAccount = $serviceAccount
    startupType = "Automatic"
    recovery = @("restart/5000", "restart/15000", "restart/60000")
    wakeTask = [ordered]@{
        taskName = $WakeTaskName
        runAt = $WakeTime
        principal = "SYSTEM"
        wakeToRun = $true
        startWhenAvailable = $false
        action = "NO_OP_WAKE_ONLY"
        interactiveLogon = $false
    }
    serviceRoot = $ServiceRoot
    repositoryRoot = $projectPath
    pythonExecutable = $pythonPath
    manifestPath = $manifestPath
    engineHostStateDirectory = $engineStateDirectory
    codexHeadlessConfigured = [bool]$codexPath
    initialJobs = $initialJobs
    shadowJobsEnabled = 0
    orderTransmission = "UNAVAILABLE"
    credentials = "Prompted locally through Get-Credential; never printed."
}

if ($PlanOnly) {
    $plan | ConvertTo-Json -Depth 6
    exit 0
}

if (-not (Test-IsAdministrator)) {
    throw (
        "Service installation requires an elevated PowerShell session. " +
        "Run this script with Run as administrator."
    )
}
if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
    throw (
        "Service $ServiceName already exists. This installer will not replace, " +
        "stop, or delete an existing service."
    )
}
if (Get-ScheduledTask -TaskName $WakeTaskName -ErrorAction SilentlyContinue) {
    throw (
        "Wake task $WakeTaskName already exists. This installer will not " +
        "replace or delete it."
    )
}

$temporaryPublish = Join-Path $env:TEMP (
    "momentum-hunter-service-publish-" + [guid]::NewGuid().ToString("N")
)
try {
    & $dotnet.Source publish $serviceProject `
        --configuration Release `
        --runtime win-x64 `
        --self-contained false `
        --output $temporaryPublish
    if ($LASTEXITCODE -ne 0) {
        throw "Automation service publish failed."
    }
    $publishedExecutable = Join-Path (
        $temporaryPublish
    ) "MomentumHunter.AutomationService.exe"
    if (-not (Test-Path -LiteralPath $publishedExecutable -PathType Leaf)) {
        throw "Published service executable is missing."
    }

    New-Item -ItemType Directory -Force -Path $ServiceRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $publishDirectory | Out-Null
    New-Item -ItemType Directory -Force -Path $stateDirectory | Out-Null

    & icacls.exe $ServiceRoot /inheritance:r `
        /grant:r "*$serviceSid`:(OI)(CI)F" `
        "*S-1-5-18:(OI)(CI)F" `
        "*S-1-5-32-544:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Automation service directory ACL configuration failed."
    }
    Copy-Item -Path (
        Join-Path $temporaryPublish "*"
    ) -Destination $publishDirectory -Recurse -Force

    $manifest = [ordered]@{
        schemaVersion = 1
        repositoryRoot = $projectPath
        pythonExecutable = $pythonPath
        powershellExecutable = $powershellPath
        codexExecutable = $codexPath
        stateDirectory = $stateDirectory
        engineHostStateDirectory = $engineStateDirectory
        expectedAccountEnding = "2573"
        expectedAccountType = "INDIVIDUAL_CASH"
        pollIntervalSeconds = 1
        jobs = $initialJobs
    }
    $temporaryManifest = "$manifestPath.$([guid]::NewGuid().ToString('N')).tmp"
    $manifest | ConvertTo-Json -Depth 6 |
        Set-Content -LiteralPath $temporaryManifest -Encoding utf8
    Move-Item -LiteralPath $temporaryManifest -Destination $manifestPath

    $credential = Get-Credential `
        -UserName $serviceAccount `
        -Message (
            "Enter the Windows account password for $serviceAccount. " +
            "Do not enter a PIN or any Schwab credential."
        )
    if ($credential.UserName -ne $serviceAccount) {
        throw "The service credential must use $serviceAccount."
    }
    $credentialProof = Start-Process `
        -FilePath $env:ComSpec `
        -ArgumentList "/d", "/c", "exit 0" `
        -Credential $credential `
        -LoadUserProfile `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($credentialProof.ExitCode -ne 0) {
        throw "The Windows service credential validation process failed."
    }
    Grant-LogOnAsService -AccountName $serviceAccount

    New-Service `
        -Name $ServiceName `
        -BinaryPathName $binaryPath `
        -DisplayName "Momentum Hunter Automation Service" `
        -Description (
            "Boot-starting, fail-closed Momentum Hunter automation supervisor."
        ) `
        -StartupType Automatic `
        -Credential $credential | Out-Null

    & sc.exe failure $ServiceName `
        reset= 86400 `
        actions= restart/5000/restart/15000/restart/60000 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Service recovery configuration failed."
    }
    & sc.exe failureflag $ServiceName 1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Service failure-action flag configuration failed."
    }

    $wakeAction = New-ScheduledTaskAction `
        -Execute "$env:SystemRoot\System32\cmd.exe" `
        -Argument "/d /c exit 0"
    $wakeTrigger = New-ScheduledTaskTrigger -Daily -At $WakeTime
    $wakePrincipal = New-ScheduledTaskPrincipal `
        -UserId "SYSTEM" `
        -LogonType ServiceAccount `
        -RunLevel Highest
    $wakeSettings = New-ScheduledTaskSettingsSet `
        -WakeToRun `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit ([TimeSpan]::FromMinutes(1))
    Register-ScheduledTask `
        -TaskName $WakeTaskName `
        -Action $wakeAction `
        -Trigger $wakeTrigger `
        -Principal $wakePrincipal `
        -Settings $wakeSettings | Out-Null

    Start-Service -Name $ServiceName
    $service = Get-Service -Name $ServiceName
    $service.WaitForStatus(
        [System.ServiceProcess.ServiceControllerStatus]::Running,
        [TimeSpan]::FromSeconds(30)
    )

    [ordered]@{
        installed = $true
        serviceName = $ServiceName
        status = $service.Status.ToString()
        startupType = "Automatic"
        serviceAccount = $serviceAccount
        wakeTaskName = $WakeTaskName
        wakeTime = $WakeTime
        wakeToRun = $true
        interactiveLogon = $false
        manifestPath = $manifestPath
        initialCanaryScheduledAt = $canaryAt.ToString("o")
        shadowJobsEnabled = 0
        orderTransmission = "UNAVAILABLE"
    } | ConvertTo-Json -Depth 4
}
finally {
    if (
        $temporaryPublish -and
        (Test-Path -LiteralPath $temporaryPublish -PathType Container) -and
        $temporaryPublish.StartsWith(
            [System.IO.Path]::GetFullPath($env:TEMP),
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        Remove-Item -LiteralPath $temporaryPublish -Recurse -Force
    }
}
