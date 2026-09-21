# Compatibility wrapper. Release builds must use the canonical Makefile
# contract instead of relinking a partial or stale object set.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $repoRoot
& make -B release-gate
if ($LASTEXITCODE -ne 0) { throw "Makefile release-gate failed ($LASTEXITCODE)" }
