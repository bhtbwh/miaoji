param(
  [string]$HostName = "localhost",
  [string]$IpAddress = "127.0.0.1",
  [string]$OutputName = "localhost",
  [switch]$RotateRoot
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$certDir = Join-Path $root "certs"
New-Item -ItemType Directory -Force -Path $certDir | Out-Null

$caConfigPath = Join-Path $certDir "miaoji-root-ca.cnf"
$caKeyPath = Join-Path $certDir "miaoji-root-ca-key.pem"
$caCertPath = Join-Path $certDir "miaoji-root-ca.pem"
$caDerPath = Join-Path $certDir "miaoji-root-ca.cer"
$configPath = Join-Path $certDir "openssl-server-san.cnf"
$csrPath = Join-Path $certDir "$OutputName.csr"
$certPath = Join-Path $certDir "$OutputName.pem"
$keyPath = Join-Path $certDir "$OutputName-key.pem"

function Invoke-OpenSsl {
  param([string[]]$Arguments)

  & openssl @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "openssl failed: openssl $($Arguments -join ' ')"
  }
}

$ipLines = @("IP.1 = 127.0.0.1")
if ($IpAddress -and $IpAddress -ne "127.0.0.1") {
  $ipLines += "IP.2 = $IpAddress"
}
$ipSan = $ipLines -join "`n"

if ($RotateRoot -or (-not (Test-Path $caKeyPath)) -or (-not (Test-Path $caCertPath))) {
@"
[req]
default_bits = 4096
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_ca

[dn]
CN = Miaoji Local Root CA

[v3_ca]
basicConstraints = critical, CA:true
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
"@ | Set-Content -Path $caConfigPath -Encoding ascii

  Invoke-OpenSsl @(
    "req", "-x509", "-new", "-nodes", "-days", "3650", "-sha256",
    "-keyout", $caKeyPath,
    "-out", $caCertPath,
    "-config", $caConfigPath
  )
} else {
  Write-Host "Reusing existing local root CA:"
  Write-Host "  $caCertPath"
}

@"
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = v3_req

[dn]
CN = $HostName

[v3_req]
subjectAltName = @alt_names
basicConstraints = CA:false
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth

[alt_names]
DNS.1 = $HostName
$ipSan
"@ | Set-Content -Path $configPath -Encoding ascii

Invoke-OpenSsl @(
  "req", "-new", "-nodes", "-newkey", "rsa:2048",
  "-keyout", $keyPath,
  "-out", $csrPath,
  "-config", $configPath
)

Invoke-OpenSsl @(
  "x509", "-req",
  "-in", $csrPath,
  "-CA", $caCertPath,
  "-CAkey", $caKeyPath,
  "-CAcreateserial",
  "-out", $certPath,
  "-days", "825",
  "-sha256",
  "-extfile", $configPath,
  "-extensions", "v3_req"
)

Invoke-OpenSsl @(
  "x509", "-in", $caCertPath, "-outform", "der", "-out", $caDerPath
)

Write-Host "Created:"
Write-Host "  $caDerPath"
Write-Host "  $caCertPath"
Write-Host "  $certPath"
Write-Host "  $keyPath"
Write-Host ""
Write-Host "Install and fully trust the root CA on iPhone before opening the HTTPS phone URL."
Write-Host "To serve the certificate over LAN:"
Write-Host "  .\scripts\start-cert-download.ps1"
