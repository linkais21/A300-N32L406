# Auto-generate a locale-independent ASCII build version before compiling.
$NOW = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), "China Standard Time")
$INVARIANT_CULTURE = [System.Globalization.CultureInfo]::InvariantCulture
$BUILD_DATE = $NOW.ToString("yyyyMMdd", $INVARIANT_CULTURE)
$BUILD_TIME = $NOW.ToString("HHmm", $INVARIANT_CULTURE)
$BUILD_DATETIME = $NOW.ToString("MMM dd yyyy - HH:mm:ss", $INVARIANT_CULTURE)
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$IDENTITY = Get-Content -Raw -LiteralPath (Join-Path $ROOT "release_identity.json") | ConvertFrom-Json
$FW_VERSION = $IDENTITY.firmware_version
$FW_VERSION = $FW_VERSION -replace '_\d{14}(?=,V)', $NOW.ToString("_yyyyMMddHHmmss", $INVARIANT_CULTURE)
if ($FW_VERSION -notmatch '_\d{14},V\d+\.\d{3}$') {
    throw "firmware_version must contain a 14-digit creation timestamp and version"
}
$FW_VERSION_COUNTER = $IDENTITY.firmware_version_counter
if ((($FW_VERSION_COUNTER -isnot [Int32]) -and ($FW_VERSION_COUNTER -isnot [Int64])) -or
    $FW_VERSION_COUNTER -lt 1 -or $FW_VERSION_COUNTER -gt [UInt32]::MaxValue) {
    throw "release_identity.json firmware_version_counter must be a nonzero unsigned 32-bit integer"
}

$IDENTITY.firmware_version = $FW_VERSION
$PREFIX = $FW_VERSION.Substring(0, $FW_VERSION.LastIndexOf('.') + 1)
$IDENTITY | Add-Member -NotePropertyName firmware_version_prefix -NotePropertyValue $PREFIX -Force
$IDENTITY | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $ROOT "release_identity.json") -Encoding ASCII

$versionHeader = @"
/* Auto-generated build version - DO NOT EDIT */
#ifndef BUILD_VERSION_H
#define BUILD_VERSION_H

#define FW_BUILD_NUMBER  "$BUILD_DATE$BUILD_TIME"
#define FW_BUILD_DATE    "$BUILD_DATETIME"
#define FW_FULL_VERSION  "$FW_VERSION"
#define FW_VERSION_COUNTER  ${FW_VERSION_COUNTER}UL

#endif /* BUILD_VERSION_H */
"@

$CONFIG_PATH = Join-Path $ROOT "include/config.h"
if (Test-Path -LiteralPath $CONFIG_PATH) {
    $CONFIG_TEXT = [IO.File]::ReadAllText($CONFIG_PATH)
    $CONFIG_TEXT = [regex]::Replace($CONFIG_TEXT, '(?m)^(#define\s+FW_VERSION_STR\s+)"[^"\r\n]+"', '${1}"' + $FW_VERSION + '"')
    [IO.File]::WriteAllText($CONFIG_PATH, $CONFIG_TEXT, [Text.UTF8Encoding]::new($false))
}
Set-Content -LiteralPath (Join-Path $ROOT "include/build_version.h") -Value $versionHeader -Encoding ASCII
Write-Host "Generated version: $FW_VERSION" -ForegroundColor Cyan
