$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$state = Join-Path $repoRoot '.runtime\mobile'
. (Join-Path $PSScriptRoot 'mobile-session.ps1')
$controlLock = Open-MobileControlLock $state
try {
$file = Join-Path $state 'processes.json'
if (-not (Test-Path -LiteralPath $file)) { Write-Host 'No registered mobile service.'; exit 0 }
$saved = Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json
$server = Get-RegisteredMobileProcess $saved.server
$tunnel = Get-RegisteredMobileProcess $saved.tunnel
if ($server) {
    $headers = @{ Origin = 'http://127.0.0.1:8787'; 'X-Qianmi-Control' = (Get-Content -LiteralPath (Join-Path $state 'access-code.txt') -Raw).Trim() }
    $null = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8787/api/control/drain' -Headers $headers -TimeoutSec 10
    while (-not $server.HasExited) {
        Write-Host 'Waiting for the mobile service and current GPU job to finish safely...'
        Start-Sleep -Seconds 2
        $server.Refresh()
    }
}
if ($tunnel) {
    # Drain may take minutes; recheck identity immediately before stopping.
    $tunnel = Get-RegisteredMobileProcess $saved.tunnel
    if ($tunnel) { Stop-Process -InputObject $tunnel }
}
Remove-Item -LiteralPath $file -Force
Write-Host 'Mobile service and its HTTPS tunnel stopped.'

} catch {
    Add-Content -LiteralPath (Join-Path $state 'desktop-control.log') -Value "$(Get-Date -Format o) stop failed: $($_.Exception.Message)" -Encoding UTF8
    throw
} finally { $controlLock.Dispose() }
