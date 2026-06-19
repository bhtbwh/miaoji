param(
  [int]$Port = 8765
)

. "$PSScriptRoot\common.ps1"

$root = Get-ProjectRoot
Set-Location $root
$python = Get-ProjectPython -Root $root
$lanIp = Get-LanIPv4
$caCert = "certs\miaoji-root-ca.cer"
$publicDir = Join-Path $root "data\public-cert"
$publicCert = Join-Path $publicDir "miaoji-root-ca.cer"

if (-not (Test-Path $caCert)) {
  Write-Section "Generate phone trust certificate"
  & "$PSScriptRoot\create-local-cert.ps1" -IpAddress $lanIp
}

New-Item -ItemType Directory -Force -Path $publicDir | Out-Null
Copy-Item -Path $caCert -Destination $publicCert -Force

Write-Section "Phone certificate download"
Write-Host "Temporarily serving the local root certificate over HTTP."
Write-Host "If Miaoji is already using port $Port, stop it first, then rerun this script."
Write-Host ""
Write-Host "Open this on iPhone Safari:"
Write-Host "  http://${lanIp}:$Port/miaoji-root-ca.cer"
Write-Host ""
Write-Host "Then install it:"
Write-Host "  Settings -> General -> VPN & Device Management -> Miaoji Local Root CA -> Install"
Write-Host "  Settings -> General -> About -> Certificate Trust Settings -> enable Miaoji Local Root CA"
Write-Host ""
Write-Host "After the certificate is installed, press Ctrl+C here and run:"
Write-Host "  .\scripts\start.ps1"
Write-Host ""

& $python -m http.server $Port --bind 0.0.0.0 --directory $publicDir
