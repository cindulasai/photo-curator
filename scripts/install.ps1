# scripts/install.ps1 — irm <raw-url>/scripts/install.ps1 | iex
$repo = "cindulasai/photo-curator"
$asset = "photo-curator-windows-x86_64.exe"
$rel = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest"
$url = ($rel.assets | Where-Object name -eq $asset).browser_download_url
if (-not $url) { throw "no binary $asset in latest release" }
$dest = "$env:LOCALAPPDATA\photo-curator"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Invoke-WebRequest $url -OutFile "$dest\photo-curator.exe"
Write-Host "Installed to $dest\photo-curator.exe - add $dest to your PATH."
