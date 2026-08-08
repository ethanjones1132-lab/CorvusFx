[CmdletBinding()]
param(
    [string]$SourceRoot = (Join-Path (Split-Path $PSScriptRoot -Parent) 'source\DrippyFX'),
    [string]$DestinationRoot = 'C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\DrippyFX',
    [switch]$VerifyOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$relativePaths = @(
    'CMakeLists.txt',
    'PluginProcessor.h',
    'dsp\CorvusEffects.h',
    'instrument\CorvusInstrumentEditor.cpp',
    'instrument\CorvusInstrumentEditor.h',
    'instrument\CorvusInstrumentProcessor.cpp',
    'instrument\CorvusInstrumentProcessor.h',
    'instrument\CorvusSynthEngine.h',
    'instrument\CorvusVoice.h',
    'instrument\WavetableOscillator.h',
    'tests\CorvusDspTests.cpp'
)

if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) {
    throw "Corvus source root does not exist: $SourceRoot"
}

if (-not (Test-Path -LiteralPath $DestinationRoot -PathType Container)) {
    throw "Corvus destination root does not exist: $DestinationRoot"
}

$resolvedSourceRoot = (Resolve-Path -LiteralPath $SourceRoot).Path
$resolvedDestinationRoot = (Resolve-Path -LiteralPath $DestinationRoot).Path
$results = @()

foreach ($relativePath in $relativePaths) {
    $sourcePath = Join-Path $resolvedSourceRoot $relativePath
    $destinationPath = Join-Path $resolvedDestinationRoot $relativePath

    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Required Corvus source file is missing: $sourcePath"
    }

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

    $sourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
    $destinationHash = (Get-FileHash -LiteralPath $destinationPath -Algorithm SHA256).Hash
    if ($sourceHash -ne $destinationHash) {
        throw "Corvus source verification failed for $relativePath"
    }

    $results += [pscustomobject]@{
        Path = $relativePath
        Sha256 = $sourceHash
        Mode = if ($VerifyOnly) { 'verified' } else { 'copied-and-verified' }
    }
}

$results | Format-Table -AutoSize
