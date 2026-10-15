$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "=== Python unit tests ==="
Push-Location "$root\python-worker"
python -m pip install -q -r requirements-dev.txt
python -m pytest tests
Pop-Location

Write-Host "=== PHP tests ==="
Push-Location "$root\php-api"
if (Get-Command composer -ErrorAction SilentlyContinue) {
  composer install --no-interaction
  if (Test-Path .\vendor\bin\phpunit) {
    .\vendor\bin\phpunit
  } else {
    php tests\run.php
  }
} else {
  php tests\run.php
}
Pop-Location
