[CmdletBinding()]
param(
    [string]$SourceRoot = $null,
    [string]$DestinationRoot = $null,
    [switch]$VerifyOnly
)

# Default source of truth: the in-repo source tree the build reads, derived
# from this script's location. No legacy Downloads tree is involved.
if (-not $SourceRoot) {
    $scriptPath = $MyInvocation.MyCommand.Path
    if ($scriptPath) { $SourceRoot = Join-Path (Split-Path (Split-Path $scriptPath -Parent) -Parent) 'source\DrippyFX' }
}
if (-not $SourceRoot) {
    throw 'Corvus source root cannot be derived from the script path; pass -SourceRoot <repo>\source\DrippyFX'
}

$relativePaths = @(
    'CMakeLists.txt',
    'PluginProcessor.h',
    'PluginProcessor.cpp',
    'PluginEditor.h',
    'PluginEditor.cpp',
    'CMakePresets.json',
    'dsp\CorvusEffects.h',
    'instrument\CorvusInstrumentEditor.cpp',
    'instrument\CorvusInstrumentEditor.h',
    'instrument\CorvusInstrumentPresets.h',
    'instrument\CorvusInstrumentProcessor.cpp',
    'instrument\CorvusInstrumentProcessor.h',
    'instrument\CorvusSynthEngine.h',
    'instrument\CorvusVoice.h',
    'instrument\WavetableOscillator.h',
    'tests\CorvusDspTests.cpp',
    'tests\CorvusFxStateTests.cpp'
)

if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) {
    throw "Corvus source root does not exist: $SourceRoot"
}

$resolvedSourceRoot = (Resolve-Path -LiteralPath $SourceRoot).Path
$compareWithDestination = -not [string]::IsNullOrWhiteSpace($DestinationRoot)

if ($compareWithDestination) {
    if (-not (Test-Path -LiteralPath $DestinationRoot -PathType Container)) {
        throw "Corvus destination root does not exist: $DestinationRoot"
    }
    $resolvedDestinationRoot = (Resolve-Path -LiteralPath $DestinationRoot).Path
}

# The map must stay complete for shared DSP: every file under dsp\ has to be
# listed explicitly above. This is a listing check only; nothing is copied.
$dspDirectory = Join-Path $resolvedSourceRoot 'dsp'
if (Test-Path -LiteralPath $dspDirectory -PathType Container) {
    $mappedDspFiles = @($relativePaths | Where-Object { $_ -like 'dsp\*' })
    foreach ($dspFile in @(Get-ChildItem -LiteralPath $dspDirectory -File)) {
        $relativeDspPath = 'dsp\' + $dspFile.Name
        if ($mappedDspFiles -notcontains $relativeDspPath) {
            throw ('Corvus sync map is missing shared-DSP file: {0} (add it to $relativePaths)' -f $relativeDspPath)
        }
    }
}

$results = @()

foreach ($relativePath in $relativePaths) {
    $sourcePath = Join-Path $resolvedSourceRoot $relativePath

    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Required Corvus source file is missing: $sourcePath"
    }

    try {
        $sourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256 -ErrorAction Stop).Hash
    }
    catch {
        throw "Required Corvus source file is not readable: $sourcePath ($($_.Exception.Message))"
    }

    if ($compareWithDestination) {
        $destinationPath = Join-Path $resolvedDestinationRoot $relativePath

        if (-not $VerifyOnly) {
            $destinationDirectory = Split-Path $destinationPath -Parent
            if (-not (Test-Path -LiteralPath $destinationDirectory -PathType Container)) {
                New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
            }
            Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
        }

        if (-not (Test-Path -LiteralPath $destinationPath -PathType Leaf)) {
            throw "Required Corvus destination file is missing: $destinationPath"
        }

        $destinationHash = (Get-FileHash -LiteralPath $destinationPath -Algorithm SHA256).Hash
        if ($sourceHash -ne $destinationHash) {
            throw "Corvus source verification failed for $relativePath (source $sourceHash, destination $destinationHash)"
        }

        $mode = if ($VerifyOnly) { 'verified-against-destination' } else { 'copied-and-verified' }
    }
    else {
        $mode = 'verified-in-repo'
    }

    $results += [pscustomobject]@{
        Path = $relativePath
        Sha256 = $sourceHash
        Mode = $mode
    }
}

$results | Format-Table -AutoSize

if ($compareWithDestination) {
    Write-Output ('Corvus verification OK: {0} mapped files match {1}' -f $results.Count, $resolvedDestinationRoot)
}
else {
    Write-Output ('Corvus in-repo verification OK: {0} mapped files present, readable and hashed in {1} (nothing copied; pass -DestinationRoot to compare a copy)' -f $results.Count, $resolvedSourceRoot)
}
