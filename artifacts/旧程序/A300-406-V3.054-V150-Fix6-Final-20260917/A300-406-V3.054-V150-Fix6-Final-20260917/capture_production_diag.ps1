param([string]$Port = 'COM12', [string]$OutputDirectory = (Join-Path $PSScriptRoot 'diagnostic-logs'))
$ErrorActionPreference = 'Stop'
# Disconnect the production tester first. Read-only queries; no actuator commands.
[void][IO.Directory]::CreateDirectory($OutputDirectory)
$path = Join-Path $OutputDirectory ('A300-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8) + '.log')
$serial = New-Object IO.Ports.SerialPort($Port,115200,[IO.Ports.Parity]::None,8,[IO.Ports.StopBits]::One)
$serial.ReadTimeout = 300
$serial.WriteTimeout = 500
$serial.DtrEnable = $false
$serial.RtsEnable = $false
$file = $null
try {
    $file = [IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    $serial.Open()
    Write-Host 'Capturing 15 seconds. Hold SOS LOW during capture. Tester must be disconnected.'
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $next = 0
    $rawSent = $false
    $queryIndex = 0
    $queries = @('GNSSDIAG#','GNSSSTAT#','SOSSTAT#')
    $buffer = New-Object byte[] 4096
    while ($timer.ElapsedMilliseconds -lt 15000) {
        if ($timer.ElapsedMilliseconds -ge $next) {
            if (!$rawSent -and $timer.ElapsedMilliseconds -ge 2000) {
                $serial.Write("GNSSRAW#`r`n")
                $rawSent = $true
            } else {
                $serial.Write($queries[$queryIndex % $queries.Length] + "`r`n")
                $queryIndex++
            }
            $next = $timer.ElapsedMilliseconds + 1000
        }
        try {
            $count = $serial.Read($buffer,0,$buffer.Length)
            if ($count -gt 0) { $file.Write($buffer,0,$count); $file.Flush() }
        } catch [TimeoutException] { }
    }
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
    if ($null -ne $file) { $file.Dispose() }
    Write-Host ('Saved raw received bytes: ' + $path)
}
