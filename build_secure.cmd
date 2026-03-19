@echo off
setlocal

cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] uv is required for secure builds.
    echo Install guide: https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)

call uv python install 3.13
if errorlevel 1 goto :fail

call uv sync --locked --group build
if errorlevel 1 goto :fail

call uv run python scripts/build_secure.py %*
if errorlevel 1 goto :fail

echo Secure build completed.
exit /b 0

:fail
echo [ERROR] Secure build failed.
pause
exit /b 1
