@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0app\Transfer-Workbench.ps1" -Action export
if errorlevel 1 pause
