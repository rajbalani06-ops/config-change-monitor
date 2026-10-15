$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$keyLine = docker compose exec -T api printenv API_KEYS
if ($LASTEXITCODE -ne 0) { throw 'Could not read API key configuration from the API container.' }
$apiKey = (($keyLine -split ',')[0] -split ':')[0]
$headers = @{ 'x-api-key' = $apiKey }
$testName = 'codex-live-' + [guid]::NewGuid().ToString('N') + '.json'
$hostFile = Join-Path $root "watched\$testName"
$containerPath = "/watched/$testName"
$watchId = $null
$testFileId = $null
$eventIds = [System.Collections.Generic.List[string]]::new()
$results = [System.Collections.Generic.List[object]]::new()

function Invoke-Api {
    param([string]$Method, [string]$Path, [hashtable]$RequestHeaders = @{}, [string]$JsonBody = $null)
    $params = @{ Uri = "http://localhost:8080$Path"; Method = $Method; Headers = $RequestHeaders; TimeoutSec = 15; SkipHttpErrorCheck = $true }
    if ($null -ne $JsonBody) { $params.ContentType = 'application/json'; $params.Body = $JsonBody }
    $response = Invoke-WebRequest @params
    $data = $null
    if ($response.Content) {
        try { $data = $response.Content | ConvertFrom-Json -AsHashtable } catch { $data = $response.Content }
    }
    return @{ Status = [int]$response.StatusCode; Data = $data }
}

function Add-Result([string]$Name, [int]$Status, [bool]$Passed, [string]$Detail) {
    $results.Add([pscustomobject]@{ Check = $Name; Status = $Status; Passed = $Passed; Detail = $Detail })
    Write-Host ("{0}: {1} (HTTP {2})" -f $Name, $(if ($Passed) { 'PASS' } else { 'FAIL' }), $Status)
}

try {
    $unauth = Invoke-Api GET '/files'
    Add-Result 'GET /files unauthenticated' $unauth.Status ($unauth.Status -eq 401) 'API key required'

    $health = Invoke-Api GET '/health'
    Add-Result 'GET /health' $health.Status ($health.Status -eq 200) ($health.Data | ConvertTo-Json -Compress -Depth 5)

    $metrics = Invoke-Api GET '/metrics'
    Add-Result 'GET /metrics' $metrics.Status ($metrics.Status -eq 200) 'Prometheus text endpoint'

    foreach ($route in @('/files','/events','/deliveries','/dead-letters','/destinations','/status')) {
        $r = Invoke-Api GET $route $headers
        Add-Result "GET $route" $r.Status ($r.Status -eq 200) 'authenticated response'
    }
    $dashboard = Invoke-Api GET '/dashboard'
    Add-Result 'GET /dashboard' $dashboard.Status ($dashboard.Status -eq 200) 'dashboard HTML'

    $badMissing = Invoke-Api POST '/watch' $headers '{}'
    Add-Result 'POST /watch missing path' $badMissing.Status ($badMissing.Status -eq 400) 'validation response'
    $badJson = Invoke-Api POST '/watch' $headers '{'
    Add-Result 'POST /watch malformed JSON' $badJson.Status ($badJson.Status -eq 400) 'validation response'
    $badExt = Invoke-Api POST '/watch' $headers ('{"path":"/watched/nope.txt"}')
    Add-Result 'POST /watch unsupported extension' $badExt.Status ($badExt.Status -eq 400) 'validation response'
    $badRoot = Invoke-Api POST '/watch' $headers ('{"path":"/etc/passwd"}')
    Add-Result 'POST /watch outside allowlist' $badRoot.Status ($badRoot.Status -eq 400) 'validation response'

    $missingId = [guid]::NewGuid().ToString()
    $notFoundDelete = Invoke-Api DELETE "/watch/$missingId" $headers
    Add-Result 'DELETE /watch/:file nonexistent' $notFoundDelete.Status ($notFoundDelete.Status -eq 404) 'not found response'
    $unknownEvent = Invoke-Api GET "/events/$missingId" $headers
    Add-Result 'GET /events/:id nonexistent' $unknownEvent.Status ($unknownEvent.Status -eq 404) 'not found response'
    $unknownReplay = Invoke-Api POST "/events/$missingId/replay" $headers '{}'
    Add-Result 'POST /events/:id/replay nonexistent' $unknownReplay.Status ($unknownReplay.Status -eq 404) 'not found response'

    Set-Content -LiteralPath $hostFile -Value '{"database":{"host":"db-a","pool":{"size":4}},"feature":true}' -NoNewline
    $watch = Invoke-Api POST '/watch' $headers (@{ path = $containerPath } | ConvertTo-Json -Compress)
    Add-Result 'POST /watch valid config' $watch.Status ($watch.Status -eq 201) 'watch registered'
    if ($watch.Status -ne 201) { throw "Watch registration failed: $($watch.Data | ConvertTo-Json -Compress -Depth 5)" }
    $watchId = $watch.Data.data.id
    $testFileId = [string]$watchId

    $leaseHealth = $null
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        $leaseHealth = (Invoke-Api GET '/health').Data
        if ($leaseHealth.dependencies.workers -eq 'ok' -and $leaseHealth.active_leases -gt 0) { break }
    }
    Add-Result 'Health worker lease' 200 ($leaseHealth.dependencies.workers -eq 'ok' -and $leaseHealth.active_leases -gt 0) ($leaseHealth | ConvertTo-Json -Compress -Depth 5)

    $baselineReady = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        $listed = Invoke-Api GET '/files' $headers
        $file = @($listed.Data.data | Where-Object { $_.id -eq $watchId } | Select-Object -First 1)[0]
        if ($file -and $file.snapshot_valid) { $baselineReady = $true; break }
    }
    Add-Result 'Initial file snapshot' 200 $baselineReady 'worker persisted baseline before modification'
    if (-not $baselineReady) { throw 'Worker did not persist the baseline snapshot in time.' }

    Start-Sleep -Seconds 1
    Set-Content -LiteralPath $hostFile -Value '{"database":{"host":"db-b","pool":{"size":8,"timeout":30}},"feature":false}' -NoNewline
    $changeEvent = $null
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 2
        $listed = Invoke-Api GET "/events?file_id=$watchId&limit=100" $headers
        $changeEvent = @($listed.Data.data | Where-Object { $_.operation -eq 'modified' } | Select-Object -First 1)[0]
        if ($changeEvent) { break }
    }
    $foundChange = $null -ne $changeEvent
    Add-Result 'File modification event' 200 $foundChange 'worker detected a nested JSON change'
    if ($foundChange) {
        $eventIds.Add([string]$changeEvent.id)
        $detail = Invoke-Api GET "/events/$($changeEvent.id)" $headers
        Add-Result 'GET /events/:id' $detail.Status ($detail.Status -eq 200) 'persisted event retrieved'
        $changes = $detail.Data.data.payload.changes
        $nestedDiff = $null -ne $changes.updated.'database.host' -and $null -ne $changes.updated.'database.pool.size' -and $null -ne $changes.added.'database.pool.timeout'
        Add-Result 'Nested JSON diff' $detail.Status $nestedDiff 'nested updated, added paths persisted'
        $replay = Invoke-Api POST "/events/$($changeEvent.id)/replay" $headers '{}'
        Add-Result 'POST /events/:id/replay' $replay.Status ($replay.Status -eq 202) 'replay accepted'

        $delivery = $null
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 2
            $deliveries = Invoke-Api GET "/deliveries?event_id=$($changeEvent.id)" $headers
            $delivery = @($deliveries.Data.data | Where-Object { $_.status -eq 'success' } | Select-Object -First 1)[0]
            if ($delivery) { break }
        }
        Add-Result 'Mock webhook delivery' 200 ($null -ne $delivery) 'delivery attempt persisted as delivered'
    }

    Remove-Item -LiteralPath $hostFile -Force
    $deleted = $null
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 2
        $listed = Invoke-Api GET "/events?file_id=$watchId&limit=100" $headers
        $deleted = @($listed.Data.data | Where-Object { $_.operation -eq 'deleted' } | Select-Object -First 1)[0]
        if ($deleted) { break }
    }
    $deletedFound = $null -ne $deleted
    Add-Result 'File deletion event' 200 $deletedFound 'worker detected deletion'
    if ($deletedFound) { $eventIds.Add([string]$deleted.id) }

    Set-Content -LiteralPath $hostFile -Value '{"database":{"host":"db-c"},"feature":true}' -NoNewline
    $recreated = $null
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 2
        $listed = Invoke-Api GET "/events?file_id=$watchId&limit=100" $headers
        $recreated = @($listed.Data.data | Where-Object { $_.operation -in @('created','created_after_delete') } | Select-Object -First 1)[0]
        if ($recreated) { break }
    }
    $recreatedFound = $null -ne $recreated
    Add-Result 'File recreation event' 200 $recreatedFound 'worker detected recreation'
    if ($recreatedFound) { $eventIds.Add([string]$recreated.id) }

    $deleteWatch = Invoke-Api DELETE "/watch/$watchId" $headers
    Add-Result 'DELETE /watch/:file existing' $deleteWatch.Status ($deleteWatch.Status -eq 200) 'watch removed'
    $watchId = $null
} finally {
    if ($watchId) { try { Invoke-Api DELETE "/watch/$watchId" $headers | Out-Null } catch {} }
    if (Test-Path -LiteralPath $hostFile) { Remove-Item -LiteralPath $hostFile -Force }
    if ($eventIds.Count -gt 0 -or $testFileId) {
        $eventClause = ($eventIds | ForEach-Object { "'$_'::uuid" }) -join ','
        $cleanupSql = if ($eventClause) { "DELETE FROM delivery_attempts WHERE event_id IN ($eventClause); DELETE FROM dead_letter_events WHERE event_id IN ($eventClause);" } else { '' }
        if ($testFileId) { $cleanupSql += " DELETE FROM audit_log WHERE target='$testFileId';" }
        if ($cleanupSql) { docker compose exec -T postgres psql -U ccm -d ccm -c $cleanupSql | Out-Null }
    }
}

$results | Format-Table -AutoSize | Out-String -Width 240 | Write-Output
if (@($results | Where-Object { -not $_.Passed }).Count -gt 0) { exit 1 }
