# Auto-generate a locale-independent ASCII build version before compiling.
$NOW = Get-Date
$INVARIANT_CULTURE = [System.Globalization.CultureInfo]::InvariantCulture
$BUILD_DATE = $NOW.ToString("yyyyMMdd", $INVARIANT_CULTURE)
$BUILD_TIME = $NOW.ToString("HHmmss", $INVARIANT_CULTURE)
$BUILD_DATETIME = $NOW.ToString("MMM dd yyyy - HH:mm:ss", $INVARIANT_CULTURE)
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$IDENTITY = Get-Content -Raw -LiteralPath (Join-Path $ROOT "release_identity.json") | ConvertFrom-Json
$FW_VERSION = $IDENTITY.firmware_version
$FW_VERSION_COUNTER = $IDENTITY.firmware_version_counter
if ((($FW_VERSION_COUNTER -isnot [Int32]) -and ($FW_VERSION_COUNTER -isnot [Int64])) -or
    $FW_VERSION_COUNTER -lt 1 -or $FW_VERSION_COUNTER -gt [UInt32]::MaxValue) {
    throw "release_identity.json firmware_version_counter must be a nonzero unsigned 32-bit integer"
}

$versionHeader = @"
/* Auto-generated build version - DO NOT EDIT */
#ifndef BUILD_VERSION_H
#define BUILD_VERSION_H

#define FW_BUILD_NUMBER  "$BUILD_DATE`_$BUILD_TIME"
#define FW_BUILD_DATE    "$BUILD_DATETIME"
#define FW_FULL_VERSION  "$FW_VERSION"
#define FW_VERSION_COUNTER  ${FW_VERSION_COUNTER}UL

#endif /* BUILD_VERSION_H */
"@

Set-Content -LiteralPath (Join-Path $ROOT "include/build_version.h") -Value $versionHeader -Encoding ASCII
Write-Host "Generated version: $FW_VERSION" -ForegroundColor Cyan
