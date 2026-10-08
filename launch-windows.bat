@echo off
rem Sub Wars Open Sourced: double-click to open the launcher in your web browser. It needs Python 3.11 or newer:
rem the one of this computer, else a portable Python downloaded once into build\python\ (python.org, 11 MB).
cd /d "%~dp0"
set "PY="
for %%v in (3.14 3.13 3.12 3.11) do if not defined PY py -%%v -c "import sys" >nul 2>nul && set "PY=py -%%v"
if not defined PY python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PY=python"
if not defined PY if exist "build\python\python.exe" set "PY=build\python\python.exe"
if not defined PY call :portable
if not defined PY goto nopython
rem One line: an update of the launcher may rewrite this file while Python runs.
%PY% subwars.py %* & pause & exit /b

:portable
echo Python 3.11 or newer was not found: downloading a portable Python for this project (once, 11 MB)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference = 'SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; New-Item -ItemType Directory -Force build | Out-Null; $f = 'build\python.zip'; Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.13.15/python-3.13.15-embed-amd64.zip' -OutFile $f; if ((Get-FileHash $f -Algorithm SHA256).Hash -ne 'D1F04D990AEE1253D8569E8E5104E30FA9F5FA830899F14843448872D936A2CF') { Remove-Item $f; exit 1 }; if (Test-Path build\python) { Remove-Item -Recurse -Force build\python }; Expand-Archive $f build\python -Force; Remove-Item $f; Remove-Item build\python\python313._pth; exit 0" && set "PY=build\python\python.exe"
exit /b

:nopython
echo Python 3.11 or newer is needed: https://www.python.org/downloads/
echo During the installation, tick "Add python.exe to PATH", then run this file again.
start "" https://www.python.org/downloads/
pause
exit /b 1
