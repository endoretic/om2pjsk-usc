param(
    [string]$Name = "om2usc",
    [string]$IconIco = "icon\om2usc.ico"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $ProjectRoot
try {
    if (-not (Test-Path -LiteralPath $IconIco)) {
        throw "Icon not found: $IconIco"
    }

    python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --name $Name `
        --icon $IconIco `
        --add-data "engine.scp;." `
        --add-data "icon;icon" `
        om2usc_gui.py
}
finally {
    Pop-Location
}
