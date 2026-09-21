param(
    [Parameter(Mandatory=$true)][string]$CombinedPath,
    [Parameter(Mandatory=$true)][string]$Port,
    [string]$ProgrammerPath,
    [ValidateRange(30,600)][int]$TimeoutSeconds = 180,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$FactoryOffset = 0x5800
$AppOffset = 0x6000
$ExpectedMarker = [uint32[]]@(
    0x494E4946, 0x001C0001, 0x00000001, 0x0000000F,
    2937699498, 0x52455144, 4294967295
)

function Test-AppVectors([byte[]]$Bytes) {
    if ($Bytes.Length -lt ($AppOffset + 8)) { return $false }
    $msp = [BitConverter]::ToUInt32($Bytes, $AppOffset)
    $reset = [BitConverter]::ToUInt32($Bytes, $AppOffset + 4)
    return $msp -ge 0x20000000 -and $msp -le 0x20006000 -and
           ($msp % 8) -eq 0 -and $reset -ge 0x08006001 -and
           $reset -lt 0x08020000 -and ($reset -band 1) -eq 1
}

function Invoke-Programmer([string[]]$Arguments, [string]$Stage) {
    Write-Output "[PRODUCTION] $Stage"
    if ($DryRun) { return }
    & $ProgrammerPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "programmer failed during $Stage (exit $LASTEXITCODE)"
    }
}

$resolvedCombined = (Resolve-Path -LiteralPath $CombinedPath).Path
$bytes = [IO.File]::ReadAllBytes($resolvedCombined)
if ($bytes.Length -lt ($FactoryOffset + 28)) {
    throw "Combined image is missing the factory-init request"
}
for ($index = 0; $index -lt $ExpectedMarker.Length; $index++) {
    if ([BitConverter]::ToUInt32($bytes, $FactoryOffset + 4 * $index) -ne $ExpectedMarker[$index]) {
        throw "Combined image has an invalid or already-completed factory-init request"
    }
}
if (-not (Test-AppVectors $bytes)) { throw "Combined image has invalid App vectors" }
Write-Output "[PRODUCTION] VALIDATE"

if (-not $DryRun) {
    if (-not $ProgrammerPath) { $ProgrammerPath = $env:PROG_CLI }
    if (-not $ProgrammerPath) { throw "set PROG_CLI or pass -ProgrammerPath" }
    $ProgrammerPath = (Resolve-Path -LiteralPath $ProgrammerPath).Path
}

$capturePath = $null
$serial = $null
try {
    Invoke-Programmer @("-c", "port=SWD", "-e", "all") "ERASE"
    Invoke-Programmer @("-c", "port=SWD", "-w", $resolvedCombined, "0x08000000", "-v") "WRITE_VERIFY"

    if (-not $DryRun) {
        $capturePath = [IO.Path]::GetTempFileName()
        $serial = [System.IO.Ports.SerialPort]::new(
            $Port, 115200, [System.IO.Ports.Parity]::None, 8,
            [System.IO.Ports.StopBits]::One
        )
        $serial.DataBits = 8
        $serial.DtrEnable = $false
        $serial.RtsEnable = $false
        $serial.ReadTimeout = 200
        $serial.Open()
    }
    Invoke-Programmer @("-c", "port=SWD", "-rst") "RESET"
    Write-Output "[PRODUCTION] SELFTEST"

    if ($DryRun) { exit 0 }
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $writer = [IO.StreamWriter]::new($capturePath, $false, [Text.Encoding]::UTF8)
    try {
        while ([DateTime]::UtcNow -lt $deadline) {
            try {
                $chunk = $serial.ReadExisting()
                if ($chunk.Length -gt 0) { $writer.Write($chunk); $writer.Flush() }
            } catch [TimeoutException] { }
            Start-Sleep -Milliseconds 50
        }
    } finally {
        $writer.Dispose()
    }

    & python (Join-Path $PSScriptRoot "production_selftest.py") $capturePath
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    exit 0
} finally {
    if ($serial -ne $null) {
        if ($serial.IsOpen) { $serial.Close() }
        $serial.Dispose()
    }
    if ($capturePath -and (Test-Path -LiteralPath $capturePath)) {
        Remove-Item -LiteralPath $capturePath -Force
    }
}
