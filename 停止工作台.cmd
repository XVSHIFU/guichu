@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0mvp\Stop-Workbench.ps1"
if errorlevel 1 pause
