@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\Stop-Workbench.ps1"
if errorlevel 1 pause
