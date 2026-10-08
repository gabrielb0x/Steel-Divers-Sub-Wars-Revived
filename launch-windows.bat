@echo off
rem Sub Wars Open Sourced: double-click to open the launcher in your web browser.
rem It needs Python 3.11 or newer (python.org), nothing else.
cd /d "%~dp0"
py -3 --version >nul 2>nul && (py -3 subwars.py & goto end)
python --version >nul 2>nul && (python subwars.py & goto end)
echo Python 3.11 or newer is needed: https://www.python.org/downloads/
echo During the installation, tick "Add python.exe to PATH", then run this file again.
start "" https://www.python.org/downloads/
:end
pause
