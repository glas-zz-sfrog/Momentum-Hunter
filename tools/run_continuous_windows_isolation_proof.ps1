[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$CanonicalRoot = "C:\Users\steve\OneDrive\Documents\Investing",
    [string]$OutputDirectory = (
        "C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\" +
        "WRITER-HARDENING-001"
    ),
    [string]$PythonExecutable = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$canonical = (Resolve-Path -LiteralPath $CanonicalRoot).Path
$python = if ($PythonExecutable) {
    (Resolve-Path -LiteralPath $PythonExecutable).Path
} elseif (Test-Path -LiteralPath (Join-Path $project ".venv\Scripts\python.exe")) {
    (Resolve-Path -LiteralPath (Join-Path $project ".venv\Scripts\python.exe")).Path
} else {
    (Resolve-Path -LiteralPath (Join-Path $canonical ".venv\Scripts\python.exe")).Path
}
$elevatedScript = Join-Path $project "tools\run_windows_isolation_elevated.ps1"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "The project Python executable is unavailable."
}
if (-not (Test-Path -LiteralPath $elevatedScript -PathType Leaf)) {
    throw "The elevated physical proof script is unavailable."
}
$git = (Get-Command git.exe -ErrorAction Stop).Source
$runId = ([guid]::NewGuid().ToString("N")).Substring(0, 16)
$stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$temporaryRoot = Join-Path $env:LOCALAPPDATA (
    "MomentumHunter\windows-isolation-proof\$runId"
)
[IO.Directory]::CreateDirectory($temporaryRoot) | Out-Null
[IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null
$nonElevated = Join-Path $temporaryRoot "non-elevated.json"
$elevated = Join-Path $temporaryRoot "elevated.json"
$outputJson = Join-Path $OutputDirectory (
    "WRITER-HARDENING-001-$stamp-$runId.json"
)
$outputMarkdown = Join-Path $OutputDirectory (
    "WRITER-HARDENING-001-$stamp-$runId.md"
)

Push-Location $project
try {
    function Quote-PowerShellLiteral([string]$value) {
        return "'" + $value.Replace("'", "''") + "'"
    }
    $command = (
        "& " + (Quote-PowerShellLiteral $elevatedScript) +
        " -ProjectRoot " + (Quote-PowerShellLiteral $project) +
        " -CanonicalRoot " + (Quote-PowerShellLiteral $canonical) +
        " -OutputPath " + (Quote-PowerShellLiteral $elevated) +
        " -RunId " + (Quote-PowerShellLiteral $runId) +
        " -GitExecutable " + (Quote-PowerShellLiteral $git)
    )
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    $process = Start-Process `
        -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $encoded) `
        -Verb RunAs `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($process.ExitCode -ne 0) {
        if (Test-Path -LiteralPath $elevated -PathType Leaf) {
            $failurePath = Join-Path $OutputDirectory (
                "WRITER-HARDENING-001-$stamp-$runId-elevated-failure.json"
            )
            Copy-Item -LiteralPath $elevated -Destination $failurePath
        }
        throw "The elevated physical proof failed with exit code $($process.ExitCode)."
    }
    if (-not (Test-Path -LiteralPath $elevated -PathType Leaf)) {
        throw "The elevated physical proof did not produce its result."
    }

    & $python -B -m momentum_hunter.windows_isolation_proof `
        non-elevated --output $nonElevated --include-soak
    if ($LASTEXITCODE -ne 0) {
        throw "The non-elevated physical proof failed."
    }

    & $python -B -m momentum_hunter.windows_isolation_proof finalize `
        --non-elevated $nonElevated `
        --elevated $elevated `
        --output-json $outputJson `
        --output-markdown $outputMarkdown
    if ($LASTEXITCODE -ne 0) {
        throw "The physical proof finalizer failed."
    }
    $report = Get-Content -Raw -LiteralPath $outputJson | ConvertFrom-Json
    [ordered]@{
        status = "COMPLETED"
        runId = $runId
        reportJson = $outputJson
        reportMarkdown = $outputMarkdown
        reportSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $outputJson).Hash
        classification = @($report.classification)
    } | ConvertTo-Json -Depth 5
} finally {
    Pop-Location
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}
