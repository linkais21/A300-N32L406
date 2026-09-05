@echo off
where mingw32-make.exe >nul 2>&1
if not errorlevel 1 (
  mingw32-make.exe %*
  exit /b %errorlevel%
)
if exist "%~dp0tools\w64devkit\w64devkit\bin\mingw32-make.exe" (
  "%~dp0tools\w64devkit\w64devkit\bin\mingw32-make.exe" %*
  exit /b %errorlevel%
)
echo mingw32-make tool not found. Install it or set PATH.
exit /b 9009
