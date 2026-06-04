param(
    [string]$ProjectRoot = "C:\Users\steve\OneDrive\Documents\Investing"
)

$pythonw = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$runPath = Join-Path $ProjectRoot "run.py"

if (Test-Path $pythonw) {
    $launcher = $pythonw
} else {
    $launcher = $python
}

Start-Process -FilePath $launcher -ArgumentList "`"$runPath`"" -WorkingDirectory $ProjectRoot -WindowStyle Hidden
