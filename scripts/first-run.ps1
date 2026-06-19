param(
  [switch]$Mock,
  [switch]$SkipModelDownload,
  [switch]$Http,
  [int]$Port = 8765
)

. "$PSScriptRoot\common.ps1"

$root = Get-ProjectRoot
Set-Location $root
Set-ProjectModelCache -Root $root | Out-Null

Write-Section "First run setup"
& "$PSScriptRoot\setup-windows.ps1"
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

if ($Mock) {
  Write-Section "Start mock ASR"
  & "$PSScriptRoot\start-mock.ps1" -Port $Port -Http:$Http
  exit $LASTEXITCODE
}

if (-not $SkipModelDownload) {
  Write-Section "Prepare real ASR model"
  & "$PSScriptRoot\download-model.ps1"
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
}

Write-Section "Start real ASR"
& "$PSScriptRoot\start.ps1" -Port $Port -Http:$Http
