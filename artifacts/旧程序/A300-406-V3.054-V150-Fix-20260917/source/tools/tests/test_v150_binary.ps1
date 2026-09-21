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
$fields=$parse.Invoke($null,[object[]]@($wire))
foreach($pair in @(@('MODEL','A300_406'),@('FIX','1'),@('HDOP','1.2'),@('CNSAT','8'),@('CNAVG','38'),@('CNMAX','44'),@('FORCE','60:300'))) {
    if($fields[$pair[0]] -ne $pair[1]) { throw ('V1.5.0 PARAM mismatch: '+$pair[0]) }
}
$success=$form.GetMethod('IsSuccess',$flags)
if(-not $success.Invoke($null,[object[]]@('APN=Success!'))) {throw 'V1.5.0 rejected setter acknowledgment'}
if($wire.IndexOf('APN,CMIOT,,=Success',[StringComparison]::OrdinalIgnoreCase) -lt 0) {throw 'APN readback mismatch'}
Write-Output 'V1.5.0 original EXE hash / actual ParseParam / IsSuccess + legacy APN readback: PASS (no GUI/HIL)'
