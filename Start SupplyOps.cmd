@echo off
setlocal
title SupplyOps - keep this window open
cd /d "%~dp0"
set "STREAMLIT_GLOBAL_DEVELOPMENT_MODE=false"
if exist ".venv\Scripts\python.exe" (
    set "SUPPLYOPS_PYTHON=%~dp0.venv\Scripts\python.exe"
) else (
    set "SUPPLYOPS_PYTHON=C:\Users\shiva\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    set "PYTHONPATH=C:\Users\shiva\Documents\Codex\2026-10-15\files-pasted-by-the-user-project\work\packages;%PYTHONPATH%"
)
if not exist "%SUPPLYOPS_PYTHON%" (
    echo Python was not found. See LOCAL_START.md for the one-time setup.
    pause
    exit /b 1
)
echo SupplyOps: http://127.0.0.1:8501
echo Keep this window open while using the app. Press Ctrl+C to stop it.
echo If port 8501 is already in use, open the address above.
"%SUPPLYOPS_PYTHON%" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless false --browser.gatherUsageStats false
if errorlevel 1 (
    echo.
    echo If the app is not already running, see LOCAL_START.md for setup instructions.
    pause
)
endlocal
