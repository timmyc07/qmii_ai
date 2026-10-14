$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'mobile-session.ps1')
$testState = Join-Path ([System.IO.Path]::GetTempPath()) ('qianmi-session-test-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $testState | Out-Null
try {
    $status = Get-MobileSession $testState
    if ($status.running -or $status.registered -or $status.code -or $status.url) { throw 'Empty state should be stopped.' }
    $stale = @{ server = @{ id = 2147483647; started = (Get-Date).ToUniversalTime().ToString('o') }; publicUrl = 'https://old.trycloudflare.com' }
    $stale | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $testState 'processes.json') -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $testState 'access-code.txt') -Value 'test-private-code'
    $status = Get-MobileSession $testState
    if ($status.running -or -not $status.registered -or $status.code -or $status.url) { throw 'Stale state must not expose connection details.' }
    $current = Get-Process -Id $PID
    $entry = @{ id = $PID; started = $current.StartTime.ToUniversalTime().ToString('o') }
    if ((Get-RegisteredMobileProcess $entry).Id -ne $PID) { throw 'Valid identity rejected.' }
    $entry.started = $current.StartTime.AddSeconds(-1).ToUniversalTime().ToString('o')
    if (Get-RegisteredMobileProcess $entry) { throw 'Reused PID must never be treated as our service.' }
    if (-not (Get-Process -Id $PID)) { throw 'Unrelated process must remain alive.' }
    $lock = Open-MobileControlLock $testState
    try {
        $rejected = $false
        try { $other = Open-MobileControlLock $testState; $other.Dispose() } catch { $rejected = $true }
        if (-not $rejected) { throw 'Concurrent lifecycle operation must be rejected.' }
    } finally { $lock.Dispose() }
    Write-Host 'Mobile session checks passed: empty/stale state, process identity, exclusive control.'
} finally {
    # Delete only the known fixture files inside this unique temporary directory.
    foreach ($name in @('processes.json', 'access-code.txt', 'control.lock')) {
        $file = Join-Path $testState $name
        if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
    }
    Remove-Item -LiteralPath $testState -Force
}
