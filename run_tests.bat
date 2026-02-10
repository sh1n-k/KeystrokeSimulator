@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "PYTHON_EXE="

if exist "%ROOT_DIR%.venv\Scripts\python.exe" (
  set "PYTHON_EXE=%ROOT_DIR%.venv\Scripts\python.exe"
) else if exist "%ROOT_DIR%.venv\Scripts\python" (
  set "PYTHON_EXE=%ROOT_DIR%.venv\Scripts\python"
) else (
  where py >nul 2>&1
  if %ERRORLEVEL%==0 (
    set "PYTHON_EXE=py"
  ) else (
    where python >nul 2>&1
    if %ERRORLEVEL%==0 (
      set "PYTHON_EXE=python"
    )
  )
)

if "%PYTHON_EXE%"=="" (
  echo [run_tests.bat] Python executable not found.
  exit /b 1
)

"%PYTHON_EXE%" "%ROOT_DIR%run_tests.py" %*
exit /b %ERRORLEVEL%
