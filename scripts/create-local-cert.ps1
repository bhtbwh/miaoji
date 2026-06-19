param(
  [string]$HostName = "localhost",
  [string]$IpAddress = "127.0.0.1",
  [string]$OutputName = "localhost"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$certDir = Join-Path $root "certs"
New-Item -ItemType Directory -Force -Path $certDir | Out-Null

$configPath = Join-Path $certDir "openssl-san.cnf"
$certPath = Join-Path $certDir "$OutputName.pem"
$keyPath = Join-Path $certDir "$OutputName-key.pem"

$ipLines = @("IP.1 = 127.0.0.1")
if ($IpAddress -and $IpAddress -ne "127.0.0.1") {
  $ipLines += "IP.2 = $IpAddress"
}
$ipSan = $ipLines -join "`n"

@"
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_req

[dn]
CN = $HostName

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = $HostName
$ipSan
"@ | Set-Content -Path $configPath -Encoding ascii

openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout $keyPath -out $certPath -config $configPath

Write-Host "Created:"
Write-Host "  $certPath"
Write-Host "  $keyPath"
Write-Host ""
Write-Host "For phone testing, use your computer LAN IP, for example:"
Write-Host "  .\scripts\create-local-cert.ps1 -IpAddress 192.168.1.23"
