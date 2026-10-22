param(
    [string]$Name = "om2usc",
    [string]$IconIco = "icon\om2usc.ico"
)

$ErrorActionPreference = "Stop"
$UvExecutable = (Get-Command uv -ErrorAction Stop).Source
$OriginalPath = $env:PATH

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $ProjectRoot
try {
    if (-not (Test-Path -LiteralPath $IconIco)) {
        throw "Icon not found: $IconIco"
    }

    # Keep unrelated applications' DLLs out of PyInstaller's dependency search.
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    & $UvExecutable run pyinstaller `
        --noconfirm `
        --clean `
        --windowed `
        --name $Name `
        --icon $IconIco `
        --add-data "engine.scp;." `
        --add-data "engine_next_sekai.scp;." `
        --add-data "LICENSE;." `
        --add-data "THIRD_PARTY_NOTICES.md;." `
        --add-data "icon;icon" `
        om2usc_gui.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
}
finally {
    $env:PATH = $OriginalPath
    Pop-Location
}
