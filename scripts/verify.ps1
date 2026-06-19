. "$PSScriptRoot\common.ps1"

$root = Get-ProjectRoot
Set-Location $root
$python = Get-ProjectPython -Root $root

Write-Section "Architecture guard"
& $python scripts\guard-architecture.py
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

Write-Section "Python compile"
& $python -m compileall server
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

Write-Section "Unit tests"
& $python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

Write-Section "Frontend syntax"
$hasNode = Test-CommandAvailable -Name "node"
if ($hasNode) {
  & node "--check" "web\app.js"
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
}

if (!$hasNode) {
  Write-Host "node was not found; skipped JS syntax check."
}

Write-Section "Done"
Write-Host "All checks passed."
