@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\Restore-LeadHive.ps1" -BackupPath "%~1"
echo.
pause
