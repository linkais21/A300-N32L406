# Auto-generate build version before compiling
$BUILD_DATE = Get-Date -Format "yyyyMMdd"
$BUILD_TIME = Get-Date -Format "HHmmss"
$BUILD_DATETIME = Get-Date -Format "MMM dd yyyy - HH:mm:ss"
$FW_VERSION = "T360-A300_406_20260823000000,V3.000"

$versionHeader = @"
/* Auto-generated build version - DO NOT EDIT */
#ifndef BUILD_VERSION_H
#define BUILD_VERSION_H

#define FW_BUILD_NUMBER  "$BUILD_DATE`_$BUILD_TIME"
#define FW_BUILD_DATE    "$BUILD_DATETIME"
#define FW_FULL_VERSION  "$FW_VERSION"

#endif /* BUILD_VERSION_H */
"@

Set-Content -Path "include/build_version.h" -Value $versionHeader -Encoding UTF8
Write-Host "Generated version: $FW_VERSION" -ForegroundColor Cyan
