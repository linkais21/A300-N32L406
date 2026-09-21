param(
    [string] $OutputDirectory
)

$ErrorActionPreference = 'Stop'
$fixedCoffTimestamp = [uint32]1788912000

function Get-Sha256Hex([string] $Path) {
    $stream = $null
    $sha256 = $null
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        return ([System.BitConverter]::ToString($sha256.ComputeHash($stream))).Replace('-', '')
    }
    finally {
        if ($sha256 -ne $null) { $sha256.Dispose() }
        if ($stream -ne $null) { $stream.Dispose() }
    }
}

function Assert-NoReparsePoint([string] $Path, [string] $Description) {
    $current = [System.IO.Path]::GetFullPath($Path)
    while (-not [string]::IsNullOrWhiteSpace($current)) {
        if (Test-Path -LiteralPath $current) {
            $attributes = [System.IO.File]::GetAttributes($current)
            if (($attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Description contains a filesystem reparse point: $current"
            }
        }
        $parent = [System.IO.Directory]::GetParent($current)
        if ($parent -eq $null) {
            break
        }
        $parentPath = $parent.FullName
        if ([string]::Equals($parentPath, $current,
            [System.StringComparison]::OrdinalIgnoreCase)) {
            break
        }
        $current = $parentPath
    }
}

function Find-ByteSequence([byte[]] $Data, [byte[]] $Sequence) {
    if ($Sequence.Length -eq 0) {
        throw 'Cannot search for an empty byte sequence.'
    }
    $offsets = New-Object System.Collections.Generic.List[int]
    for ($i = 0; $i -le $Data.Length - $Sequence.Length; $i++) {
        $matches = $true
        for ($j = 0; $j -lt $Sequence.Length; $j++) {
            if ($Data[$i + $j] -ne $Sequence[$j]) {
                $matches = $false
                break
            }
        }
        if ($matches) {
            $offsets.Add($i)
        }
    }
    return $offsets.ToArray()
}

function Replace-SingleByteSequence(
    [byte[]] $Data,
    [byte[]] $Original,
    [byte[]] $Replacement,
    [string] $Description
) {
    if ($Original.Length -ne $Replacement.Length) {
        throw "$Description replacement length mismatch."
    }
    $offsets = @(Find-ByteSequence $Data $Original)
    if ($offsets.Count -ne 1) {
        throw "$Description must occur exactly once; found $($offsets.Count)."
    }
    [System.Array]::Copy($Replacement, 0, $Data, $offsets[0], $Replacement.Length)
}

function Get-DeterministicGuid(
    [string[]] $InputFiles,
    [string[]] $FixedCompilerArguments,
    [string] $CompilerPath
) {
    $manifest = New-Object System.Collections.Generic.List[string]
    $manifest.Add('A300ProductionTester deterministic PE normalization v1')
    $manifest.Add("compiler_sha256=$(Get-Sha256Hex $CompilerPath)")
    foreach ($argument in $FixedCompilerArguments) {
        $manifest.Add("argument=$argument")
    }
    foreach ($inputFile in $InputFiles) {
        $manifest.Add("input=$inputFile;sha256=$(Get-Sha256Hex $inputFile)")
    }
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $seed = [System.Text.Encoding]::UTF8.GetBytes(
            [string]::Join("`n", $manifest.ToArray()))
        $hex = ([System.BitConverter]::ToString($sha256.ComputeHash($seed))).Replace('-', '')
    }
    finally {
        $sha256.Dispose()
    }
    $guidText = '{0}-{1}-5{2}-8{3}-{4}' -f `
        $hex.Substring(0, 8), $hex.Substring(8, 4),
        $hex.Substring(13, 3), $hex.Substring(17, 3), $hex.Substring(20, 12)
    return [System.Guid]::Parse($guidText)
}

function Normalize-ManagedExecutable(
    [string] $Path,
    [System.Guid] $DeterministicGuid,
    [uint32] $CoffTimestamp
) {
    [byte[]] $data = [System.IO.File]::ReadAllBytes($Path)
    if (($data.Length -lt 256) -or ($data[0] -ne 0x4D) -or ($data[1] -ne 0x5A)) {
        throw 'Compiled executable does not contain a valid DOS header.'
    }
    $peOffset = [System.BitConverter]::ToInt32($data, 0x3C)
    if (($peOffset -lt 0x40) -or ($peOffset -gt $data.Length - 24) -or
        ($data[$peOffset] -ne 0x50) -or ($data[$peOffset + 1] -ne 0x45) -or
        ($data[$peOffset + 2] -ne 0) -or ($data[$peOffset + 3] -ne 0)) {
        throw 'Compiled executable does not contain a valid PE signature.'
    }

    $assembly = [System.Reflection.Assembly]::Load($data)
    $originalMvid = $assembly.ManifestModule.ModuleVersionId
    $privateTypes = @($assembly.GetTypes() | Where-Object {
        $_.FullName -match '^<PrivateImplementationDetails>\{[0-9A-Fa-f-]{36}\}$'
    })
    if ($privateTypes.Count -ne 1) {
        throw "Expected one root PrivateImplementationDetails GUID type; found $($privateTypes.Count)."
    }
    $privateTypeName = $privateTypes[0].FullName
    if ($privateTypeName -notmatch '^<PrivateImplementationDetails>\{([0-9A-Fa-f-]{36})\}$') {
        throw 'PrivateImplementationDetails type name has an invalid GUID.'
    }
    $privateGuid = [System.Guid]::Parse($Matches[1])
    if ($privateGuid -ne $originalMvid) {
        throw 'PrivateImplementationDetails GUID does not match the module MVID.'
    }

    [byte[]] $timestampBytes = [System.BitConverter]::GetBytes($CoffTimestamp)
    [System.Array]::Copy($timestampBytes, 0, $data, $peOffset + 8, 4)
    Replace-SingleByteSequence $data $originalMvid.ToByteArray() `
        $DeterministicGuid.ToByteArray() 'raw module MVID'
    [byte[]] $originalAscii = [System.Text.Encoding]::ASCII.GetBytes(
        $originalMvid.ToString('D').ToUpperInvariant())
    [byte[]] $replacementAscii = [System.Text.Encoding]::ASCII.GetBytes(
        $DeterministicGuid.ToString('D').ToUpperInvariant())
    Replace-SingleByteSequence $data $originalAscii $replacementAscii `
        'PrivateImplementationDetails ASCII GUID'

    if (@(Find-ByteSequence $data $DeterministicGuid.ToByteArray()).Count -ne 1 -or
        @(Find-ByteSequence $data $replacementAscii).Count -ne 1) {
        throw 'Deterministic GUID normalization verification failed.'
    }
    [System.IO.File]::WriteAllBytes($Path, $data)
    $validatedName = [System.Reflection.AssemblyName]::GetAssemblyName($Path)
    if (($validatedName.Name -ne 'A300ProductionTester') -or
        ($validatedName.Version.ToString() -ne '1.5.0.0')) {
        throw 'Normalized executable failed AssemblyName identity validation.'
    }
}

$root = [System.IO.Path]::GetFullPath(
    (Split-Path -Parent $MyInvocation.MyCommand.Path))
Set-Location -LiteralPath $root
[System.Environment]::CurrentDirectory = $root
$canonicalBin = [System.IO.Path]::GetFullPath((Join-Path $root 'bin'))
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $output = $canonicalBin
}
elseif ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $output = [System.IO.Path]::GetFullPath($OutputDirectory)
}
else {
    $output = [System.IO.Path]::GetFullPath((Join-Path $root $OutputDirectory))
}
$pathComparison = [System.StringComparison]::OrdinalIgnoreCase
$isCanonicalBin = [string]::Equals($output.TrimEnd('\'),
    $canonicalBin.TrimEnd('\'), $pathComparison)
if (-not $isCanonicalBin) {
    $temporaryRoot = [System.IO.Path]::GetFullPath(
        [System.IO.Path]::GetTempPath()).TrimEnd('\')
    $temporaryPrefix = $temporaryRoot + '\'
    if (-not $output.StartsWith($temporaryPrefix, $pathComparison)) {
        throw 'OutputDirectory must be canonical bin or a controlled temporary release path.'
    }
    $relativeOutput = $output.Substring($temporaryPrefix.Length)
    $separatorIndex = $relativeOutput.IndexOf('\')
    $releaseRootName = if ($separatorIndex -lt 0) {
        $relativeOutput
    }
    else {
        $relativeOutput.Substring(0, $separatorIndex)
    }
    $releasePrefix = 'a300-tester-release-'
    if (($releaseRootName.Length -le $releasePrefix.Length) -or
        (-not $releaseRootName.StartsWith($releasePrefix, $pathComparison))) {
        throw 'Temporary OutputDirectory must be inside an a300-tester-release-* run root.'
    }
}
$outputParent = Split-Path -Parent $output
$outputLeaf = Split-Path -Leaf $output
if ([string]::IsNullOrWhiteSpace($outputParent) -or
    [string]::IsNullOrWhiteSpace($outputLeaf)) {
    throw 'OutputDirectory must identify a child directory, not a filesystem root.'
}
$protectedPaths = @($root, $canonicalBin, $outputParent, $output)
foreach ($protectedPath in $protectedPaths) {
    Assert-NoReparsePoint $protectedPath 'Release output path'
}
New-Item -ItemType Directory -Force -Path $outputParent | Out-Null
$nonce = [System.Guid]::NewGuid().ToString('N')
$staging = Join-Path $outputParent ('.' + $outputLeaf + '.staging-' + $nonce)
$backup = Join-Path $outputParent ('.' + $outputLeaf + '.backup-' + $nonce)
$mutablePaths = $protectedPaths + @($staging, $backup)

$repoRoot = (& git -C $root rev-parse --show-toplevel).Trim()
if (($LASTEXITCODE -ne 0) -or (-not (Test-Path -LiteralPath $repoRoot -PathType Container))) {
    throw 'Unable to determine the source repository root.'
}
$gitCommit = (& git -C $repoRoot rev-parse HEAD).Trim()
if (($LASTEXITCODE -ne 0) -or ($gitCommit -notmatch '^[0-9a-f]{40}$')) {
    throw 'Unable to determine the source Git commit.'
}
$gitStatus = & git -c core.excludesFile= -C $repoRoot status --porcelain `
    --untracked-files=normal -- . `
    ':(top,exclude)app/tools/A300ProductionTester/bin/**'
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to determine the source worktree status.'
}
$worktreeState = if ($gitStatus) { 'dirty' } else { 'clean' }

$windowsDir = if ($env:WINDIR) { $env:WINDIR } else { 'C:\Windows' }
$csc = Join-Path $windowsDir 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $csc)) {
    $csc = Join-Path $windowsDir 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
if (-not (Test-Path -LiteralPath $csc)) {
    throw 'The .NET Framework C# compiler was not found.'
}
$compilerInputs = @('src\ProductionProtocol.cs', 'src\A300ProductionTester.cs')
$fixedCompilerArguments = @(
    '/noconfig', '/nologo', '/target:winexe', '/platform:anycpu', '/optimize+',
    '/warnaserror+',
    '/out:A300ProductionTester.exe', '/reference:System.dll',
    '/reference:System.Core.dll', '/reference:System.Drawing.dll',
    '/reference:System.Windows.Forms.dll', '/reference:System.Xml.dll',
    '/reference:System.IO.Compression.dll',
    '/reference:System.IO.Compression.FileSystem.dll'
) + $compilerInputs
$deterministicGuid = Get-DeterministicGuid $compilerInputs `
    $fixedCompilerArguments $csc

$installed = $false
$backupCreated = $false
try {
    foreach ($mutablePath in $mutablePaths) {
        Assert-NoReparsePoint $mutablePath 'Release output path'
    }
    New-Item -ItemType Directory -Path $staging | Out-Null
    $stagedExe = Join-Path $staging 'A300ProductionTester.exe'
    $compilerArguments = @(
        '/noconfig', '/nologo', '/target:winexe', '/platform:anycpu', '/optimize+',
        '/warnaserror+',
        "/out:$stagedExe", '/reference:System.dll', '/reference:System.Core.dll',
        '/reference:System.Drawing.dll', '/reference:System.Windows.Forms.dll',
        '/reference:System.Xml.dll', '/reference:System.IO.Compression.dll',
        '/reference:System.IO.Compression.FileSystem.dll'
    ) + $compilerInputs
    & $csc $compilerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "C# compiler failed with exit code $LASTEXITCODE."
    }
    Normalize-ManagedExecutable $stagedExe $deterministicGuid $fixedCoffTimestamp

    $stagedConfig = Join-Path $staging 'config'
    New-Item -ItemType Directory -Path $stagedConfig | Out-Null
    Copy-Item -LiteralPath 'config\a300_tester.ini' `
        -Destination (Join-Path $stagedConfig 'a300_tester.ini')
    Copy-Item -LiteralPath 'README.md' `
        -Destination (Join-Path $staging 'README.md')

    $stagedTemplates = Join-Path $staging 'templates'
    New-Item -ItemType Directory -Path $stagedTemplates | Out-Null
    $canonicalTemplates = @(Get-ChildItem -LiteralPath 'templates' -File `
        -Filter '*.xlsx' | Sort-Object -Property Name)
    $canonicalTemplates | Copy-Item -Destination $stagedTemplates

    $revisionPath = Join-Path $staging 'SOURCE_REVISION.txt'
    @("git_commit=$gitCommit", "git_worktree=$worktreeState") |
        Set-Content -LiteralPath $revisionPath -Encoding Ascii
    $releaseFiles = @(
        @{ Path = $stagedExe; Relative = 'A300ProductionTester.exe' }
        @{ Path = (Join-Path $stagedConfig 'a300_tester.ini'); Relative = 'config/a300_tester.ini' }
        @{ Path = (Join-Path $staging 'README.md'); Relative = 'README.md' }
        @{ Path = $revisionPath; Relative = 'SOURCE_REVISION.txt' }
    )
    foreach ($template in $canonicalTemplates) {
        $releaseFiles += @{
            Path = (Join-Path $stagedTemplates $template.Name)
            Relative = ('templates/' + $template.Name)
        }
    }
    $hashLines = @($releaseFiles | ForEach-Object {
        '{0}  {1}' -f (Get-Sha256Hex $_.Path), $_.Relative
    })
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines(
        (Join-Path $staging 'SHA256SUMS.txt'), $hashLines, $utf8NoBom)
    if ($isCanonicalBin) {
        $canonicalGitkeep = Join-Path $output '.gitkeep'
        if (Test-Path -LiteralPath $canonicalGitkeep -PathType Leaf) {
            Copy-Item -LiteralPath $canonicalGitkeep `
                -Destination (Join-Path $staging '.gitkeep')
        }
        else {
            [System.IO.File]::WriteAllBytes(
                (Join-Path $staging '.gitkeep'), [byte[]]@())
        }
    }

    if (Test-Path -LiteralPath $output) {
        foreach ($mutablePath in $mutablePaths) {
            Assert-NoReparsePoint $mutablePath 'Release output path'
        }
        Move-Item -LiteralPath $output -Destination $backup
        $backupCreated = $true
    }
    try {
        foreach ($mutablePath in $mutablePaths) {
            Assert-NoReparsePoint $mutablePath 'Release output path'
        }
        Move-Item -LiteralPath $staging -Destination $output
        $installed = $true
    }
    catch {
        if ($backupCreated -and (-not (Test-Path -LiteralPath $output))) {
            foreach ($mutablePath in $mutablePaths) {
                Assert-NoReparsePoint $mutablePath 'Release output path'
            }
            Move-Item -LiteralPath $backup -Destination $output
            $backupCreated = $false
        }
        throw
    }
    if ($backupCreated) {
        foreach ($mutablePath in $mutablePaths) {
            Assert-NoReparsePoint $mutablePath 'Release output path'
        }
        Remove-Item -LiteralPath $backup -Recurse -Force
        $backupCreated = $false
    }
}
finally {
    if ((-not $installed) -and (Test-Path -LiteralPath $staging)) {
        foreach ($mutablePath in $mutablePaths) {
            Assert-NoReparsePoint $mutablePath 'Release output path'
        }
        Remove-Item -LiteralPath $staging -Recurse -Force
    }
}

Write-Host ('Build OK: ' + (Join-Path $output 'A300ProductionTester.exe'))
