@echo off
set "PROJECT_ROOT=C:\Users\steve\OneDrive\Documents\Investing"

cd /d "%PROJECT_ROOT%"

if exist "%PROJECT_ROOT%\Momentum Hunter.vbs" (
    wscript.exe "%PROJECT_ROOT%\Momentum Hunter.vbs"
    exit /b 0
)

if exist "%PROJECT_ROOT%\.venv\Scripts\pythonw.exe" (
    start "" "%PROJECT_ROOT%\.venv\Scripts\pythonw.exe" "%PROJECT_ROOT%\run.py"
    exit /b 0
)

if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
    start "" "%PROJECT_ROOT%\.venv\Scripts\python.exe" "%PROJECT_ROOT%\run.py"
    exit /b 0
)

echo Momentum Hunter could not find the project Python environment.
echo Expected: %PROJECT_ROOT%\.venv\Scripts\pythonw.exe
pause
exit /b 1
