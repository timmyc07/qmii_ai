$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
. (Join-Path $PSScriptRoot 'mobile-session.ps1')
$state = Join-Path (Split-Path -Parent $PSScriptRoot) '.runtime\mobile'
try {
    Get-MobileSession $state | ConvertTo-Json -Compress
} catch {
    Add-Content -LiteralPath (Join-Path $state 'desktop-control.log') -Value "$(Get-Date -Format o) status failed: $($_.Exception.Message)" -Encoding UTF8
    throw
}
