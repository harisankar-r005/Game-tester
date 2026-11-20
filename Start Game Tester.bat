@echo off
title Game Tester - keep this window open
cd /d "%~dp0"
echo.
echo   Closing any Game Tester that is still open (so you start fresh)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'apkharness serve' -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo.
echo   Game Tester is starting...
echo   Your browser will open at http://127.0.0.1:8765/
echo.
echo   Keep this window OPEN while testing. Close it to stop the tester.
echo.
py -3 -m apkharness serve --open
if errorlevel 1 (
  echo.
  echo   The tester could not start. Is Python installed?
  pause
)
