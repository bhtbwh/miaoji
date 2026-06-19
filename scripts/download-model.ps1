param(
  [string]$Model = "paraformer-zh-streaming",
  [string]$Revision = "v2.0.4",
  [string]$Device = "cpu"
)

. "$PSScriptRoot\common.ps1"

$root = Get-ProjectRoot
Set-Location $root
$python = Get-ProjectPython -Root $root

Write-Section "Download and initialize FunASR model"
Write-Host "Model:    $Model"
Write-Host "Revision: $Revision"
Write-Host "Device:   $Device"

$code = @"
from funasr import AutoModel

model = AutoModel(
    model="$Model",
    model_revision="$Revision",
    disable_update=True,
    device="$Device",
)
print("FunASR model is ready.")
"@

$tempFile = Join-Path $env:TEMP "miaoji_download_model.py"
Set-Content -Path $tempFile -Value $code -Encoding UTF8
& $python $tempFile
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
