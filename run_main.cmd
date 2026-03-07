@echo off
setlocal

cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] uv is not installed or not on PATH.
    echo Install guide: https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)

call uv python install 3.13
if errorlevel 1 goto :fail

call uv sync --locked
if errorlevel 1 goto :fail

if /I "%~1"=="--check" (
    echo Environment check passed.
    exit /b 0
)

call uv run python main.py
exit /b %errorlevel%

:fail
echo [ERROR] Failed to prepare the runtime environment.
pause
exit /b 1
