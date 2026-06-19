param(
  [int]$Port = 8765,
  [switch]$MockAsr,
  [switch]$Https,
  [string]$CertFile = "certs\localhost.pem",
  [string]$KeyFile = "certs\localhost-key.pem"
)

$params = @{
  Port = $Port
  MockAsr = $MockAsr
  Http = (-not $Https)
}

if ($Https -and ((-not (Test-Path $CertFile)) -or (-not (Test-Path $KeyFile)))) {
  throw "Missing certificate files. Run scripts\create-local-cert.ps1 first."
}

& "$PSScriptRoot\start.ps1" @params
