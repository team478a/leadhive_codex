@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Run-Live-Input.ps1" %*
pause
