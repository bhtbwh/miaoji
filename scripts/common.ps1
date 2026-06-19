$ErrorActionPreference = "Stop"

function Get-ProjectRoot {
  return (Split-Path -Parent $PSScriptRoot)
}

function Get-ProjectPython {
  param([string]$Root)

  $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
  if (Test-Path $venvPython) {
    return $venvPython
  }
  return "python"
}

function Set-ProjectModelCache {
  param([string]$Root)

  $cacheDir = Join-Path $Root "data\modelscope_cache"
  New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
  $env:MIAOJI_MODELSCOPE_CACHE = $cacheDir
  $env:MODELSCOPE_CACHE = $cacheDir
  $env:MODELSCOPE_CACHE_HOME = $cacheDir
  return $cacheDir
}

function Get-LanIPv4 {
  $addresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
      $_.IPAddress -notlike "127.*" -and
      $_.IPAddress -notlike "169.254.*" -and
      $_.PrefixOrigin -ne "WellKnown"
    } |
    Sort-Object -Property InterfaceMetric, InterfaceIndex

  if ($addresses) {
    return $addresses[0].IPAddress
  }

  $ipconfig = ipconfig | Select-String -Pattern "IPv4"
  if ($ipconfig) {
    $match = [regex]::Match($ipconfig[0].ToString(), "(\d{1,3}\.){3}\d{1,3}")
    if ($match.Success) {
      return $match.Value
    }
  }

  return "127.0.0.1"
}

function Test-CommandAvailable {
  param([string]$Name)
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Write-Section {
  param([string]$Text)
  Write-Host ""
  Write-Host "== $Text ==" -ForegroundColor Cyan
}

function Write-AccessUrls {
  param(
    [int]$Port,
    [bool]$Https,
    [string]$LanIp
  )

  $scheme = if ($Https) { "https" } else { "http" }
  Write-Host ""
  Write-Host "Desktop URL: ${scheme}://localhost:$Port"
  Write-Host "Phone URL:   ${scheme}://${LanIp}:$Port"
  Write-Host ""
  if ($Https) {
    Write-Host "If iPhone refuses the certificate warning, install the local root CA:"
    Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-cert-download.ps1"
  } else {
    Write-Host "Note: phone browsers usually require HTTPS for microphone access."
  }
}
