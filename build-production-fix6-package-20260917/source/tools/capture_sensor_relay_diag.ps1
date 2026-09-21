param([string]$Port='COM12')
$ErrorActionPreference='Stop'
$folder=Join-Path $PSScriptRoot 'diagnostic-logs'
[void][IO.Directory]::CreateDirectory($folder)
$path=Join-Path $folder ('sensor-relay-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[guid]::NewGuid().ToString('N').Substring(0,8)+'.log')
$serial=New-Object IO.Ports.SerialPort($Port,115200,[IO.Ports.Parity]::None,8,[IO.Ports.StopBits]::One)
$serial.ReadTimeout=100
$serial.WriteTimeout=500
$serial.DtrEnable=$false
$serial.RtsEnable=$false
$writer=$null
try {
 $writer=New-Object IO.StreamWriter([IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read))
 $writer.AutoFlush=$true
 $serial.Open()
 $timer=[Diagnostics.Stopwatch]::StartNew()
 $next=0; $index=0; $phase=-1
 while($timer.ElapsedMilliseconds -lt 30000) {
  $ms=$timer.ElapsedMilliseconds
  $stage=[int][Math]::Floor($ms/10000)
  if($stage -ne $phase) {
   $phase=$stage
   $label=@('KEEP STILL for 10 seconds','SHAKE device for 10 seconds','KEEP STILL for 10 seconds')[$stage]
   Write-Host $label
   $writer.WriteLine("`r`n[HOST phase=$stage ms=$ms] $label")
  }
  if($ms -ge $next) {
   # Queries only: never switches relay or clears its state.
   $query=if($index % 10 -eq 9){'RELAYTEST,STATUS#'}else{'GSENSOR#'}
   $writer.WriteLine("`r`n[HOST tx ms=$ms] $query")
   $serial.Write($query+"`r`n")
   $index++; $next=$ms+300
  }
  try { $writer.Write([char]$serial.ReadChar()); $writer.Write($serial.ReadExisting()) } catch [TimeoutException] {}
 }
} finally {
 if($serial.IsOpen){$serial.Close()}
 $serial.Dispose()
 if($null -ne $writer){$writer.Dispose()}
 Write-Host ('Saved: '+$path)
}
