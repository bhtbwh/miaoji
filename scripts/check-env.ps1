param(
  [int]$Port = 8765
)

. "$PSScriptRoot\common.ps1"

$root = Get-ProjectRoot
Set-Location $root
$cacheDir = Set-ProjectModelCache -Root $root
$python = Get-ProjectPython -Root $root
$lanIp = Get-LanIPv4

$checks = @()

function Add-Check {
  param(
    [string]$Name,
    [bool]$Ok,
    [string]$Detail
  )
  $script:checks += [pscustomobject]@{
    Name = $Name
    Ok = $Ok
    Detail = $Detail
  }
}

$hasPython = Test-CommandAvailable -Name "python"
Add-Check "Python" $hasPython ((python --version) 2>&1 | Out-String).Trim()
Add-Check "VirtualEnv" (Test-Path ".venv\Scripts\python.exe") ".venv\Scripts\python.exe"
$projectPythonOk = if ($python -eq "python") { Test-CommandAvailable -Name "python" } else { Test-Path $python -PathType Leaf }
Add-Check "ProjectPython" $projectPythonOk $python
$hasOpenSsl = Test-CommandAvailable -Name "openssl"
Add-Check "OpenSSL" $hasOpenSsl "Needed for phone HTTPS certificate"
Add-Check "Certificate" ((Test-Path "certs\localhost.pem") -and (Test-Path "certs\localhost-key.pem")) "certs\localhost.pem"
Add-Check "PhoneRootCA" (Test-Path "certs\miaoji-root-ca.cer") "certs\miaoji-root-ca.cer"
Add-Check "LAN IP" ($lanIp -ne "127.0.0.1") $lanIp
Add-Check "ModelCache" (Test-Path $cacheDir) $cacheDir
Add-Check "SummaryEnabled" ($env:MIAOJI_SUMMARY_ENABLED -in @("1", "true", "yes", "on")) "MIAOJI_SUMMARY_ENABLED=$env:MIAOJI_SUMMARY_ENABLED"
Add-Check "SummaryAPIKey" (-not [string]::IsNullOrWhiteSpace($env:MIAOJI_SUMMARY_API_KEY)) "MIAOJI_SUMMARY_API_KEY is only needed when realtime summary is enabled"
Add-Check "SummaryBaseURL" (-not [string]::IsNullOrWhiteSpace($env:MIAOJI_SUMMARY_BASE_URL)) ($(if ($env:MIAOJI_SUMMARY_BASE_URL) { $env:MIAOJI_SUMMARY_BASE_URL } else { "default: https://ark.cn-beijing.volces.com/api/coding/v3" }))
Add-Check "SummaryModel" (-not [string]::IsNullOrWhiteSpace($env:MIAOJI_SUMMARY_MODEL)) ($(if ($env:MIAOJI_SUMMARY_MODEL) { $env:MIAOJI_SUMMARY_MODEL } else { "default: doubao-seed-2.0-lite" }))
Add-Check "DiarizationCommand" (-not [string]::IsNullOrWhiteSpace($env:MIAOJI_DIARIZATION_COMMAND)) "Optional 3D-Speaker command; mock mode uses MIAOJI_DIARIZATION_MOCK=1"

$oldErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"

$importCheck = & $python -c "import fastapi, uvicorn, numpy, websockets; print('ok')" 2>&1
Add-Check "CoreDeps" ($LASTEXITCODE -eq 0) (($importCheck | Out-String).Trim())

$funasrCheck = & $python -c "import funasr; print('ok')" 2>&1
Add-Check "FunASR" ($LASTEXITCODE -eq 0) (($funasrCheck | Out-String).Trim())

$ErrorActionPreference = $oldErrorActionPreference

Write-Section "Environment check"
$checks | Format-Table -AutoSize

Write-AccessUrls -Port $Port -Https ((Test-Path "certs\localhost.pem") -and (Test-Path "certs\localhost-key.pem")) -LanIp $lanIp

$failedRequiredChecks = $checks | Where-Object { (-not $_.Ok) -and $_.Name -in @("Python", "CoreDeps") }
if ($failedRequiredChecks) {
  exit 1
}
