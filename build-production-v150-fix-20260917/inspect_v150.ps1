$ErrorActionPreference='Stop'
$root=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$exe=Join-Path $root '生产测试工具/A300ProductionTester/bin/A300ProductionTester.exe'
$a=[Reflection.Assembly]::LoadFile($exe)
$ops=@{}
[Reflection.Emit.OpCodes].GetFields([Reflection.BindingFlags]'Public,Static')|ForEach-Object { $o=$_.GetValue($null);$key=([int]$o.Value -band 65535).ToString();$ops[$key]=$o }
foreach($pair in @(@('MainForm','TestSos'),@('FactoryMeasurements','TryParseSos'),@('FactoryMeasurements','TryParseGsensor'))) {
 $m=$a.GetType('A300ProductionTester.'+$pair[0]).GetMethod($pair[1],[Reflection.BindingFlags]'Public,NonPublic,Instance,Static')
 Write-Output ($pair -join '.')
 $bytes=$m.GetMethodBody().GetILAsByteArray()
 for($i=0;$i -lt $bytes.Length;) {
  $offset=$i;$code=[int]$bytes[$i++];if($code -eq 254){$code=65024+[int]$bytes[$i++]};$op=$ops[$code.ToString()];$size=0;$value=''
  if($null -eq $op){throw "Unknown opcode $code offset $offset next $i"}
  switch($op.OperandType.ToString()) {
   'InlineNone' {}
   'ShortInlineBrTarget' {$size=1}
   'ShortInlineI' {$size=1;$value=$bytes[$i]}
   'ShortInlineVar' {$size=1}
   'InlineVar' {$size=2}
   'InlineI8' {$size=8}
   'InlineR' {$size=8}
   'InlineSwitch' {$size=4+4*[BitConverter]::ToInt32($bytes,$i)}
   default {$size=4}
  }
  if($op.OperandType.ToString() -eq 'InlineString') {$value=$m.Module.ResolveString([BitConverter]::ToInt32($bytes,$i))}
  if($op.OperandType.ToString() -in @('InlineMethod','InlineField')) {$value=$m.Module.ResolveMember([BitConverter]::ToInt32($bytes,$i)).ToString()}
  if($pair[1] -eq 'TryParseSos') {Write-Output ('{0:X4} {1} {2}' -f $offset,$op.Name,$value)}
  $i+=$size
 }
}

