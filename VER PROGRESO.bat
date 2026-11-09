@echo off
title DeepScan - progreso del pipeline
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\ver_progreso.ps1"
pause
