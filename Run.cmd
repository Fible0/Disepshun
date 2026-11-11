@echo off
title Disepshun
color 2
cd /d "%~dp0"
rem Prefer Python 3.12, which the README requires; fall back to the default Python.
py -3.12 -c "" >nul 2>&1
if errorlevel 1 (py Main.py) else (py -3.12 Main.py)
pause