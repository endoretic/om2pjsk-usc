param(
    [string]$Name = "om2usc"
)

$ErrorActionPreference = "Stop"

python -m PyInstaller `
    --noconfirm `
    --windowed `
    --name $Name `
    --add-data "engine.scp;." `
    om2usc_gui.py
