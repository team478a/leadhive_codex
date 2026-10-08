@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\Import-LeadHiveBackup.ps1" -BackupPath "%~1"
pause
