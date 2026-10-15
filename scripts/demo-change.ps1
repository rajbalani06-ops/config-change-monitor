$ErrorActionPreference = "Stop"
$api = "http://localhost:8080"
$key = "dev-admin-key"
$headers = @{ "X-API-Key" = $key; "Content-Type" = "application/json" }

Write-Host "Health:"
Invoke-RestMethod "$api/health" | ConvertTo-Json -Depth 5

$path = "/watched/app.yaml"
Write-Host "Register $path"
try {
  Invoke-RestMethod -Method Post -Uri "$api/watch" -Headers $headers -Body (@{ path = $path } | ConvertTo-Json)
} catch {
  Write-Host "Registration may already exist: $($_.Exception.Message)"
}

Write-Host "Files:"
Invoke-RestMethod -Uri "$api/files" -Headers @{ "X-API-Key" = $key } | ConvertTo-Json -Depth 6

$local = Join-Path (Split-Path -Parent $PSScriptRoot) "watched\app.yaml"
$stamp = Get-Date -Format "o"
@(
  "db:"
  "  host: prod-db"
  "  port: 5432"
  "  password: change-me"
  "logging:"
  "  level: debug"
  "featureFlags:"
  "  newUI: true"
  "cache:"
  "  enabled: false"
  "changedAt: $stamp"
) | Set-Content -Path $local -Encoding utf8

Write-Host "Modified $local ; waiting for debounce/stable-file/outbox..."
Start-Sleep -Seconds 6

Write-Host "Events:"
Invoke-RestMethod -Uri "$api/events?limit=5" -Headers @{ "X-API-Key" = $key } | ConvertTo-Json -Depth 8
Write-Host "Deliveries:"
Invoke-RestMethod -Uri "$api/deliveries?limit=5" -Headers @{ "X-API-Key" = $key } | ConvertTo-Json -Depth 6
