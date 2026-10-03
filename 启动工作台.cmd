@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0mvp\Start-Workbench.ps1"
if errorlevel 1 pause
