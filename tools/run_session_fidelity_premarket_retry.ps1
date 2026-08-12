[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("A", "B", "C")]
    [string]$Checkpoint,
    [string]$ProjectRoot = "",
    [string]$PythonRoot = "C:\Users\steve\OneDrive\Documents\Investing",
    [string]$OutputDirectory = "C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\SESSION-FIDELITY-003-20260812",
    [string]$AlpacaRoot = "C:\Users\steve\AppData\Local\MomentumHunter\worktrees\ARGUS-OVERNIGHT-001-readonly-market-data-probe",
    [string]$DiagnosticDirectory = "",
    [ValidateRange(0, 10)]
    [int]$PreflightRetryDelaySeconds = 2,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedGitCommit,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedRetryModuleSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedRetryRunnerSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedAdapterSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedAlpacaCommit,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedAlpacaModuleSha256,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($DiagnosticDirectory)) {
    $DiagnosticDirectory = [System.IO.Path]::Combine(
        $env:LOCALAPPDATA,
        "MomentumHunter",
        "diagnostics",
        "SESSION-FIDELITY-003-20260812"
    )
}
$DiagnosticDirectory = [System.IO.Path]::GetFullPath($DiagnosticDirectory)
[System.IO.Directory]::CreateDirectory($DiagnosticDirectory) | Out-Null
$diagnosticPath = [System.IO.Path]::Combine(
    $DiagnosticDirectory,
    "checkpoint-$($Checkpoint.ToLowerInvariant())-wrapper.log"
)

function Write-Diagnostic {
    param([string]$Message)
    $line = "[$([datetime]::UtcNow.ToString('o'))] $Message$([Environment]::NewLine)"
    try {
        [System.IO.File]::AppendAllText($diagnosticPath, $line, [System.Text.UTF8Encoding]::new($false))
    }
    catch {
        # The process exit still communicates failure if even the local fallback is unavailable.
    }
}

function Resolve-RequiredDirectory {
    param([string]$Path, [string]$Label)
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        Write-Diagnostic "preflight.start label=$Label attempt=$attempt"
        try {
            $resolved = [System.IO.Path]::GetFullPath($Path)
            if (-not [System.IO.Directory]::Exists($resolved)) {
                throw "$Label is unavailable."
            }
            Write-Diagnostic "preflight.pass label=$Label attempt=$attempt"
            return $resolved
        }
        catch {
            Write-Diagnostic "preflight.retry label=$Label attempt=$attempt errorType=$($_.Exception.GetType().Name)"
            if ($attempt -eq 3) { throw }
            Start-Sleep -Seconds $PreflightRetryDelaySeconds
        }
    }
}

function Get-Sha256 {
    param([string]$Path)
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        try {
            return ([System.BitConverter]::ToString($sha256.ComputeHash($stream))).Replace("-", "")
        }
        finally {
            $sha256.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
}

function Assert-CleanCommit {
    param([string]$Root, [string]$Expected, [string]$Label)
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        Write-Diagnostic "preflight.start label=$Label attempt=$attempt"
        try {
            $actual = (& git -C $Root rev-parse HEAD).Trim()
            if ($LASTEXITCODE -ne 0 -or $actual -ne $Expected.ToLowerInvariant()) {
                throw "$Label does not match its frozen Git commit."
            }
            $dirty = & git -C $Root status --porcelain
            if ($LASTEXITCODE -ne 0 -or $dirty) {
                throw "$Label is not clean."
            }
            Write-Diagnostic "preflight.pass label=$Label attempt=$attempt"
            return
        }
        catch {
            Write-Diagnostic "preflight.retry label=$Label attempt=$attempt errorType=$($_.Exception.GetType().Name)"
            if ($attempt -eq 3) { throw }
            Start-Sleep -Seconds $PreflightRetryDelaySeconds
        }
    }
}

function Assert-FileHash {
    param([string]$Path, [string]$Expected, [string]$Label)
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        Write-Diagnostic "preflight.start label=$Label attempt=$attempt"
        try {
            if (-not [System.IO.File]::Exists($Path)) {
                throw "$Label is unavailable."
            }
            $actual = Get-Sha256 -Path $Path
            if ($actual -ne $Expected.ToUpperInvariant()) {
                throw "$Label does not match its frozen SHA-256."
            }
            Write-Diagnostic "preflight.pass label=$Label attempt=$attempt"
            return
        }
        catch {
            Write-Diagnostic "preflight.retry label=$Label attempt=$attempt errorType=$($_.Exception.GetType().Name)"
            if ($attempt -eq 3) { throw }
            Start-Sleep -Seconds $PreflightRetryDelaySeconds
        }
    }
}

Write-Diagnostic "wrapper.start taskId=SESSION-FIDELITY-003 checkpoint=$Checkpoint"
try {
    if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
        $ProjectRoot = [System.IO.Path]::GetDirectoryName($PSScriptRoot)
    }
    $ProjectRoot = Resolve-RequiredDirectory -Path $ProjectRoot -Label "Premarket retry worktree"
    $PythonRoot = Resolve-RequiredDirectory -Path $PythonRoot -Label "Python root"
    $AlpacaRoot = Resolve-RequiredDirectory -Path $AlpacaRoot -Label "Frozen Alpaca probe"
    $python = [System.IO.Path]::Combine($PythonRoot, ".venv", "Scripts", "python.exe")
    $retryModule = [System.IO.Path]::Combine($ProjectRoot, "momentum_hunter", "session_fidelity_premarket_retry.py")
    $retryRunner = [System.IO.Path]::Combine($ProjectRoot, "tools", "run_session_fidelity_premarket_retry.py")
    $adapter = [System.IO.Path]::Combine($ProjectRoot, "tools", "run_session_fidelity_alpaca.py")

    Assert-CleanCommit -Root $ProjectRoot -Expected $ExpectedGitCommit -Label "Premarket retry worktree"
    Assert-FileHash -Path $retryModule -Expected $ExpectedRetryModuleSha256 -Label "Premarket retry module"
    Assert-FileHash -Path $retryRunner -Expected $ExpectedRetryRunnerSha256 -Label "Premarket retry runner"
    Assert-FileHash -Path $adapter -Expected $ExpectedAdapterSha256 -Label "Repaired Alpaca adapter"
    Assert-CleanCommit -Root $AlpacaRoot -Expected $ExpectedAlpacaCommit -Label "Frozen Alpaca probe"
    Assert-FileHash -Path ([System.IO.Path]::Combine($AlpacaRoot, "momentum_hunter", "alpaca_overnight_probe.py")) -Expected $ExpectedAlpacaModuleSha256 -Label "Frozen Alpaca module"

    if (-not [System.IO.File]::Exists($python)) {
        throw "The pinned Python executable is unavailable."
    }
    [System.IO.Directory]::CreateDirectory([System.IO.Path]::GetFullPath($OutputDirectory)) | Out-Null
    $OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
    if ($OutputDirectory.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Premarket retry evidence must remain outside the repository."
    }

    if (-not $Execute) {
        Write-Diagnostic "wrapper.complete mode=PLAN_ONLY"
        [ordered]@{
            mode = "PLAN_ONLY"
            taskId = "SESSION-FIDELITY-003"
            checkpoint = $Checkpoint
            expectedGitCommit = $ExpectedGitCommit.ToLowerInvariant()
            outputDirectory = $OutputDirectory
            providerScope = "ALPACA_ONLY"
            serviceChanged = $false
            schedulerChanged = $false
            productionPersistence = $false
            accountRequested = $false
            positionsRequested = $false
            ordersRequested = $false
            orderTransmission = "UNAVAILABLE"
        } | ConvertTo-Json
        exit 0
    }

    $outputPath = [System.IO.Path]::Combine($OutputDirectory, "checkpoint-$($Checkpoint.ToLowerInvariant())-alpaca.json")
    $logPath = [System.IO.Path]::Combine($OutputDirectory, "checkpoint-$($Checkpoint.ToLowerInvariant())-retry.log")
    $arguments = @(
        "-B", $retryRunner,
        "--checkpoint", $Checkpoint,
        "--project-root", $ProjectRoot,
        "--source-root", $AlpacaRoot,
        "--output", $outputPath
    )
    $startedAt = [datetime]::UtcNow.ToString("o")
    Write-Diagnostic "provider.start"
    $savedErrorActionPreference = $ErrorActionPreference
    try {
        # Native stderr is evidence, not a PowerShell terminating error. Capture
        # it so the runner's sanitized failure classification reaches the log.
        $ErrorActionPreference = "Continue"
        $output = & $python @arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }
    [System.IO.File]::AppendAllLines(
        $logPath,
        @(
            "[$startedAt] taskId=SESSION-FIDELITY-003 checkpoint=$Checkpoint commit=$($ExpectedGitCommit.ToLowerInvariant())",
            ($output | Out-String).TrimEnd(),
            "[$([datetime]::UtcNow.ToString('o'))] exitCode=$exitCode"
        ),
        [System.Text.UTF8Encoding]::new($false)
    )
    $output | Write-Output
    if ($exitCode -ne 0) {
        throw "The read-only premarket retry failed safely with exit code $exitCode."
    }
    Write-Diagnostic "wrapper.complete mode=EXECUTE exitCode=0"
}
catch {
    $safeMessage = $_.Exception.Message -replace '[\r\n]+', ' '
    Write-Diagnostic "wrapper.failed errorType=$($_.Exception.GetType().Name) message=$safeMessage"
    Write-Error "Premarket retry failed safely. See local diagnostic log: $diagnosticPath"
    exit 1
}
