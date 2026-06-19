param(
  [string]$Model = "paraformer-zh-streaming",
  [string]$Revision = "v2.0.4",
  [string]$Device = "cpu",
  [switch]$Refine,
  [string]$RefineModel = "paraformer-zh",
  [string]$VadModel = "fsmn-vad",
  [string]$PuncModel = "ct-punc",
  [switch]$Diarization
)

. "$PSScriptRoot\common.ps1"

$root = Get-ProjectRoot
Set-Location $root
$python = Get-ProjectPython -Root $root
$cacheDir = Join-Path $root "data\modelscope_cache"
New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
$env:MIAOJI_MODELSCOPE_CACHE = $cacheDir
$env:MODELSCOPE_CACHE = $cacheDir
$env:MODELSCOPE_CACHE_HOME = $cacheDir

Write-Section "Download and initialize FunASR model"
Write-Host "Model:    $Model"
Write-Host "Revision: $Revision"
Write-Host "Device:   $Device"
Write-Host "Cache:    $cacheDir"

$code = @"
from funasr import AutoModel

streaming_model = AutoModel(
    model="$Model",
    model_revision="$Revision",
    disable_update=True,
    device="$Device",
)
print("FunASR streaming model is ready.")

if "$Refine".lower() == "true":
    refine_model = AutoModel(
        model="$RefineModel",
        model_revision="$Revision",
        vad_model="$VadModel",
        punc_model="$PuncModel",
        disable_update=True,
        device="$Device",
    )
    print("FunASR offline refine model is ready.")
"@

$tempFile = Join-Path $env:TEMP "miaoji_download_model.py"
Set-Content -Path $tempFile -Value $code -Encoding UTF8
& $python $tempFile
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

if ($Diarization) {
  Write-Section "Speaker diarization"
  Write-Host "Speaker diarization uses an optional local 3D-Speaker command."
  Write-Host "Install 3D-Speaker separately, then set:"
  Write-Host '  $env:MIAOJI_DIARIZATION_COMMAND = "python C:\path\to\3D-Speaker\speakerlab\bin\infer_diarization.py --wav {wav} --out_dir {out_dir}"'
  Write-Host "If this is not configured, recording and transcription still work."
}
