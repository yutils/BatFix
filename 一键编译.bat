@echo off
cd /d "%~dp0"
echo Starting BatFix build...
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" -Arch both
echo.
if not defined BATFIX_NOPAUSE pause
