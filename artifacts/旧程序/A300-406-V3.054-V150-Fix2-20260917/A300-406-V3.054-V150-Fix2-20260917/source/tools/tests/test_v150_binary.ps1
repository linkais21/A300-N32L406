param([Parameter(Mandatory=$true)][string]$FirmwareReplies)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$exe=Join-Path (Split-Path -Parent $root) '生产测试工具/A300ProductionTester/bin/A300ProductionTester.exe'
$hash=[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([IO.File]::ReadAllBytes($exe))).Replace('-','')
if ($hash -ne 'C11CD59373BEC11C1B46CA29E6DDE9B0510AD66CADF717AD185BFEEBEC6FFC15') { throw 'Unexpected V1.5.0 binary' }
# Load metadata and pure parsing methods only: no forms, serial or network.
$assembly=[Reflection.Assembly]::LoadFile($exe)
$form=$assembly.GetType('A300ProductionTester.MainForm',$true)
$flags=[Reflection.BindingFlags]'NonPublic,Static'
$parse=$form.GetMethod('ParseParam',$flags)
$wire=[IO.File]::ReadAllText((Resolve-Path -LiteralPath $FirmwareReplies))
$protocol=$assembly.GetType('A300ProductionTester.ProductionReply',$true)
$correlate=$protocol.GetMethod('IsCorrelatedComplete',[Reflection.BindingFlags]'Public,Static')
$paramLine=($wire -split "`r?`n")[0]
if(-not $correlate.Invoke($null,[object[]]@('PARAM#',$paramLine))) {throw 'Original V1.5.0 discards PARAM line before parsing'}
if($correlate.Invoke($null,[object[]]@('PARAM#',('MODEL[x]'+$paramLine)))) {throw 'Negative prefix fixture accepted'}
$framerType=$assembly.GetType('A300ProductionTester.ResponseFramer',$true)
$push=$framerType.GetMethod('Push')
foreach($chunkSize in @(1,7,64,4096)) {
    $framer=[Activator]::CreateInstance($framerType,[object[]]@([int]4096))
    $stream="[LOG] unrelated`r`n"+$wire
    $matched=''
    for($offset=0;$offset -lt $stream.Length;$offset+=$chunkSize) {
        $chunk=$stream.Substring($offset,[Math]::Min($chunkSize,$stream.Length-$offset))
        $lines=$push.Invoke($framer,[object[]]@($chunk))
        foreach($line in $lines) {
            if($matched.Length -eq 0 -and $correlate.Invoke($null,[object[]]@('PARAM#',$line))) {$matched=$line}
        }
    }
    if($matched -ne $paramLine) {throw 'Original EXE framing/correlation lost PARAM or accepted partial line'}
}
$fields=$parse.Invoke($null,[object[]]@($wire))
foreach($pair in @(@('MODEL','A300_406'),@('FIX','1'),@('HDOP','1.2'),@('CNSAT','8'),@('CNAVG','38'),@('CNMAX','44'),@('FORCE','60:300'))) {
    if($fields[$pair[0]] -ne $pair[1]) { throw ('V1.5.0 PARAM mismatch: '+$pair[0]) }
}
$success=$form.GetMethod('IsSuccess',$flags)
if(-not $success.Invoke($null,[object[]]@('APN=Success!'))) {throw 'V1.5.0 rejected setter acknowledgment'}
if($wire.IndexOf('APN,CMIOT,,=Success',[StringComparison]::OrdinalIgnoreCase) -lt 0) {throw 'APN readback mismatch'}
Write-Output 'V1.5.0 original EXE hash / ResponseFramer chunks / IsCorrelatedComplete / ParseParam / IsSuccess + APN: PASS (no GUI/HIL)'
