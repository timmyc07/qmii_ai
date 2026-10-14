$ErrorActionPreference = 'Stop'

function Open-MobileControlLock([string]$StateDirectory) {
    New-Item -ItemType Directory -Path $StateDirectory -Force | Out-Null
    try {
        return [System.IO.File]::Open((Join-Path $StateDirectory 'control.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    } catch {
        throw 'Another mobile start/stop operation is in progress. Please wait.'
    }
}

function Get-RegisteredMobileProcess($Entry) {
    if (-not $Entry) { return $null }
    if ([int]$Entry.id -le 0 -or -not $Entry.started) { throw 'Invalid saved mobile process identity.' }
    $process = Get-Process -Id $Entry.id -ErrorAction SilentlyContinue
    if ($process -and $process.StartTime.ToUniversalTime() -ne ([datetime]$Entry.started).ToUniversalTime()) {
        # The registered process is gone; this PID now belongs to somebody else.
        return $null
    }
    return $process
}

function Get-MobileSession([string]$StateDirectory) {
    $result = [ordered]@{ running = $false; registered = $false; url = ''; code = ''; message = '手機連線尚未開啟。' }
    $file = Join-Path $StateDirectory 'processes.json'
    if (-not (Test-Path -LiteralPath $file)) { return [pscustomobject]$result }
    $result.registered = $true
    $saved = Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json
    $server = Get-RegisteredMobileProcess $saved.server
    $tunnel = Get-RegisteredMobileProcess $saved.tunnel
    $result.message = '連線已中斷或只有本機服務，請按「重新連線」。'
    if (-not $server -or -not $tunnel) { return [pscustomobject]$result }
    $url = [string]$saved.publicUrl
    # Earlier releases only saved the public URL in the human-readable file.
    if (-not $url) {
        $info = Get-Content -LiteralPath (Join-Path $StateDirectory 'connection-info.txt') -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
        $url = [regex]::Match([string]$info, 'https://[a-z0-9-]+\.trycloudflare\.com').Value
    }
    if ($url -notmatch '^https://[a-z0-9-]+\.trycloudflare\.com$') { return [pscustomobject]$result }
    try {
        $response = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8787/' -TimeoutSec 3
        if ($response.StatusCode -ne 200 -or $response.Content -notmatch '千迷AI') { return [pscustomobject]$result }
    } catch { return [pscustomobject]$result }
    $code = (Get-Content -LiteralPath (Join-Path $StateDirectory 'access-code.txt') -Raw -Encoding UTF8).Trim()
    if (-not $code) { throw 'The mobile connection code is missing.' }
    $result.running = $true
    $result.url = $url
    $result.code = $code
    $result.message = '手機服務與 HTTPS 通道已啟動。'
    return [pscustomobject]$result
}
