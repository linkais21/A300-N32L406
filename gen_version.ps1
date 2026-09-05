# Auto-generate a locale-independent ASCII build version before compiling.
$NOW = Get-Date
$INVARIANT_CULTURE = [System.Globalization.CultureInfo]::InvariantCulture
$BUILD_DATE = $NOW.ToString("yyyyMMdd", $INVARIANT_CULTURE)
$BUILD_TIME = $NOW.ToString("HHmmss", $INVARIANT_CULTURE)
$BUILD_DATETIME = $NOW.ToString("MMM dd yyyy - HH:mm:ss", $INVARIANT_CULTURE)
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

Set-Content -Path "include/build_version.h" -Value $versionHeader -Encoding ASCII
Write-Host "Generated version: $FW_VERSION" -ForegroundColor Cyan
