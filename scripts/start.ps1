param(
  [int]$Port = 8765,
  [switch]$Http,
  [switch]$MockAsr
)

. "$PSScriptRoot\common.ps1"

$root = Get-ProjectRoot
Set-Location $root

$python = Get-ProjectPython -Root $root
$lanIp = Get-LanIPv4
$certFile = "certs\localhost.pem"
$keyFile = "certs\localhost-key.pem"
$useHttps = -not $Http

if ($useHttps -and ((-not (Test-Path $certFile)) -or (-not (Test-Path $keyFile)))) {
  $hasOpenSsl = Test-CommandAvailable -Name "openssl"
  if (-not $hasOpenSsl) {
    Write-Host "openssl was not found. Starting with HTTP; phone microphone access may fail."
    $useHttps = $false
  } else {
    Write-Host "Certificate missing. Generating a self-signed certificate for $lanIp..."
    & "$PSScriptRoot\create-local-cert.ps1" -IpAddress $lanIp
  }
}

if ($MockAsr) {
  $env:MIAOJI_MOCK_ASR = "1"
} else {
  Remove-Item Env:\MIAOJI_MOCK_ASR -ErrorAction SilentlyContinue
}

Write-Section "Start Miaoji"
Write-AccessUrls -Port $Port -Https $useHttps -LanIp $lanIp

$argsList = @("-m", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "$Port")
if ($useHttps) {
  $argsList += @("--ssl-certfile", $certFile, "--ssl-keyfile", $keyFile)
}

& $python @argsList
