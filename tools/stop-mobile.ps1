$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$state = Join-Path $repoRoot '.runtime\mobile'
$file = Join-Path $state 'processes.json'
if (-not (Test-Path -LiteralPath $file)) { Write-Host 'No registered mobile service.'; exit 0 }
$saved = Get-Content -LiteralPath $file -Raw | ConvertFrom-Json
$server = Get-Process -Id $saved.server.id -ErrorAction SilentlyContinue
if ($server -and $server.StartTime.ToUniversalTime() -ne ([datetime]$saved.server.started).ToUniversalTime()) {
    throw 'Saved server identity does not match the running process. No process was stopped.'
}
if ($server) {
    $headers = @{ Origin = 'http://127.0.0.1:8787'; 'X-Qianmi-Control' = (Get-Content -LiteralPath (Join-Path $state 'access-code.txt') -Raw).Trim() }
    $null = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8787/api/control/drain' -Headers $headers -TimeoutSec 10
    while (-not $server.HasExited) {
        Write-Host 'Waiting for the mobile service and current GPU job to finish safely...'
        Start-Sleep -Seconds 2
        $server.Refresh()
    }
}
foreach ($name in @('tunnel')) {
    $entry = $saved.$name
    if ($entry) {
        $process = Get-Process -Id $entry.id -ErrorAction SilentlyContinue
        if ($process -and $process.StartTime.ToUniversalTime() -ne ([datetime]$entry.started).ToUniversalTime()) {
            throw 'Saved tunnel identity does not match the running process. No process was stopped.'
        }
        if ($process) {
            Stop-Process -Id $process.Id
        }
    }
}
Remove-Item -LiteralPath $file -Force
Write-Host 'Mobile service and its HTTPS tunnel stopped.'
