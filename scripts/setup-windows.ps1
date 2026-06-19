param(
  [switch]$SkipInstall,
  [switch]$SkipCert
)

. "$PSScriptRoot\common.ps1"

$root = Get-ProjectRoot
Set-Location $root
$cacheDir = Set-ProjectModelCache -Root $root

Write-Section "Check Python"
$hasPython = Test-CommandAvailable -Name "python"
if (-not $hasPython) {
  throw "python was not found. Install Python 3.11, then rerun this script."
}

$pythonVersion = python -c 'import sys; print(".".join(map(str, sys.version_info[:3])))'
Write-Host "Python: $pythonVersion"

Write-Section "Create virtual environment"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  python -m venv .venv
  Write-Host "Created .venv"
} else {
  Write-Host ".venv already exists"
}

$python = Get-ProjectPython -Root $root

if (-not $SkipInstall) {
  Write-Section "Install dependencies"
  & $python -m pip install --upgrade pip
  & $python -m pip install -r requirements.txt
} else {
  Write-Host "Skipped dependency install"
}

Write-Section "Check OpenSSL"
$hasOpenSsl = Test-CommandAvailable -Name "openssl"
if (-not $hasOpenSsl) {
  Write-Host "openssl was not found. Certificate generation will be skipped."
  $SkipCert = $true
} else {
  Write-Host "OpenSSL is available"
}

$lanIp = Get-LanIPv4
Write-Host "Detected LAN IP: $lanIp"
Write-Host "Model cache: $cacheDir"

if (-not $SkipCert) {
  Write-Section "Generate local HTTPS certificate"
  & "$PSScriptRoot\create-local-cert.ps1" -IpAddress $lanIp
}

Write-Section "Done"
Write-Host "Mock ASR start: .\scripts\start-mock.ps1"
Write-Host "Real ASR start: .\scripts\start.ps1"
$httpsReady = -not $SkipCert
Write-AccessUrls -Port 8765 -Https $httpsReady -LanIp $lanIp
