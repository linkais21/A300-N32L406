@echo off
where mingw32-make.exe >nul 2>&1
if not errorlevel 1 (
  mingw32-make.exe %*
  exit /b %errorlevel%
)
where make.exe >nul 2>&1
if not errorlevel 1 (
  make.exe %*
  exit /b %errorlevel%
)
if exist "%~dp0tools\w64devkit\w64devkit\bin\make.exe" (
  "%~dp0tools\w64devkit\w64devkit\bin\make.exe" %*
  exit /b %errorlevel%
)
echo make tool not found. Install mingw32-make or set PATH.
exit /b 9009
