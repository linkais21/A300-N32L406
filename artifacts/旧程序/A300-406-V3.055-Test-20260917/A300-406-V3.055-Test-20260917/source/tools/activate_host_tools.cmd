@echo off
set "A300_HOST_TOOLS=%~dp0..\..\tools\w64devkit\w64devkit\bin"
if exist "%A300_HOST_TOOLS%\gcc.exe" (
  set "PATH=%A300_HOST_TOOLS%;%PATH%"
  echo A300 bundled host tools active: %A300_HOST_TOOLS%
  exit /b 0
)
where gcc.exe >nul 2>&1
if errorlevel 1 (
  echo Host GCC not found on PATH.
  exit /b 1
)
where mingw32-make.exe >nul 2>&1
if errorlevel 1 (
  echo mingw32-make not found on PATH.
  exit /b 1
)
echo System host tools active: GCC and mingw32-make found on PATH.
exit /b 0
