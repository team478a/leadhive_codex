@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\Stop-LeadHiveOutbound.ps1"
if errorlevel 1 pause
