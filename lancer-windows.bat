@echo off
rem Sub Wars Open Sourced : double-cliquez pour ouvrir le lanceur dans votre navigateur.
rem Il faut Python 3.11 ou plus recent (python.org), rien d'autre.
cd /d "%~dp0"
py -3 --version >nul 2>nul && (py -3 subwars.py & goto fin)
python --version >nul 2>nul && (python subwars.py & goto fin)
echo Il faut Python 3.11 ou plus recent : https://www.python.org/downloads/
echo Pendant l'installation, cochez "Add python.exe to PATH", puis relancez ce fichier.
start "" https://www.python.org/downloads/
:fin
pause
