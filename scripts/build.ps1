$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

python -m PyInstaller `
  --noconfirm `
  --name dify-win-agent `
  --onefile `
  --windowed `
  --collect-all webview `
  --collect-all pythonnet `
  --collect-all clr_loader `
  --manifest build/agent.manifest `
  --paths src `
  src/main.py
