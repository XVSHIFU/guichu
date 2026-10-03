@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0app\Transfer-Workbench.ps1" -Action import
if errorlevel 1 pause
