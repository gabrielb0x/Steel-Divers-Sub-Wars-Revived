@echo off
rem Sub Wars Open Sourced: installs the project into a folder Sub-Wars-Open-Sourced next to this file, then opens
rem the launcher, which sets the game up. Put this file where you want that folder, then double-click it.
rem Already installed: it opens the launcher, which updates itself.
setlocal
cd /d "%~dp0"
set "ZIP=Sub-Wars-Open-Sourced.zip"
if exist "Sub-Wars-Open-Sourced\subwars.py" (
    echo Sub Wars Open Sourced is already here: opening the launcher, which updates itself.
    goto launch
)
echo Downloading Sub Wars Open Sourced...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference = 'SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/gabrielb0x/Sub-Wars-Steel-Divers-Open-Sourced/releases/latest/download/Sub-Wars-Open-Sourced.zip' -OutFile '%ZIP%'"
if errorlevel 1 goto failed
echo Unpacking...
tar -xf "%ZIP%" 2>nul || powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '.' -Force"
if not exist "Sub-Wars-Open-Sourced\subwars.py" goto failed
del "%ZIP%"
:launch
call "Sub-Wars-Open-Sourced\launch-windows.bat" --setup
exit /b
:failed
if exist "%ZIP%" del "%ZIP%"
echo The download or the unpacking failed: check the Internet connection, then run this file again.
pause
exit /b 1
