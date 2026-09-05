@echo off
where gcc.exe >nul 2>&1
if not errorlevel 1 (
  gcc.exe %*
  exit /b %errorlevel%
)
if exist "%~dp0tools\w64devkit\w64devkit\bin\gcc.exe" (
  "%~dp0tools\w64devkit\w64devkit\bin\gcc.exe" %*
  exit /b %errorlevel%
)
echo host gcc tool not found. Install GCC or set PATH.
exit /b 9009
