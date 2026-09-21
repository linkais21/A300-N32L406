# Compatibility wrapper. The Makefile is the single source of truth for
# compiler flags, source membership, dependency tracking and release gates.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $repoRoot
& make -B release-gate
if ($LASTEXITCODE -ne 0) { throw "Makefile release-gate failed ($LASTEXITCODE)" }
