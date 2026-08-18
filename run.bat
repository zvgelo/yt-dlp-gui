@echo off
rem Runs the application, using .venv when one is present.
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" main.py %*
    goto :eof
)
start "" pythonw main.py %*
