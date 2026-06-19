param(
  [int]$Port = 8765,
  [switch]$Http
)

& "$PSScriptRoot\start.ps1" -Port $Port -Http:$Http -MockAsr
