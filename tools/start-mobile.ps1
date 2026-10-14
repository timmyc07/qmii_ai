param([switch]$Public)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.runtime\mobile-venv\Scripts\python.exe'
$state = Join-Path $repoRoot '.runtime\mobile'
New-Item -ItemType Directory -Path $state -Force | Out-Null
if (Test-Path -LiteralPath (Join-Path $state 'processes.json')) {
    throw 'A mobile session is already registered. Run tools\stop-mobile.ps1 first.'
}
if (-not (Test-Path -LiteralPath $python)) {
    python -m venv (Join-Path $repoRoot '.runtime\mobile-venv')
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create Python environment.' }
}
& $python -m pip install -r (Join-Path $repoRoot 'mobile\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Unable to install mobile dependencies.' }
$tunnel = $null
$server = $null
$publicUrl = ''
try {
    if ($Public) {
        $cloudflared = Join-Path $repoRoot '.runtime\cloudflared.exe'
        if (-not (Test-Path -LiteralPath $cloudflared)) {
            throw 'Install the official cloudflared executable at .runtime\cloudflared.exe. See docs\MOBILE.md.'
        }
        $tunnelLog = Join-Path $state 'tunnel.log'
        $tunnel = Start-Process -FilePath $cloudflared -ArgumentList @('tunnel','--no-autoupdate','--url','http://127.0.0.1:8787','--protocol','http2') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $state 'tunnel.stdout.log') -RedirectStandardError $tunnelLog -PassThru
        $deadline = (Get-Date).AddSeconds(60)
        do {
            Start-Sleep -Milliseconds 500
            $match = [regex]::Match((Get-Content -LiteralPath $tunnelLog -Raw -ErrorAction SilentlyContinue), 'https://[a-z0-9-]+\.trycloudflare\.com')
            if ($match.Success) { $publicUrl = $match.Value; break }
            if ($tunnel.HasExited) { throw 'HTTPS tunnel failed. See .runtime\mobile\tunnel.log.' }
        } while ((Get-Date) -lt $deadline)
        if (-not $publicUrl) { throw 'HTTPS tunnel startup timed out.' }
    }
    $env:QIANMI_PUBLIC_URL = $publicUrl
    $server = Start-Process -FilePath $python -ArgumentList @('-m','mobile.server') -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $state 'server.stdout.log') -RedirectStandardError (Join-Path $state 'server.stderr.log') -PassThru
    $deadline = (Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 500
        if ($server.HasExited) { throw 'Mobile service failed. See .runtime\mobile\server.stderr.log.' }
        try { $ready = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8787/' -TimeoutSec 2 } catch { $ready = $null }
        if ($ready -and $ready.StatusCode -eq 200) { break }
    } while ((Get-Date) -lt $deadline)
    if (-not $ready) { throw 'Mobile service startup timed out.' }
    $processes = @{ server = @{ id = $server.Id; started = $server.StartTime.ToUniversalTime().ToString('o') } }
    if ($tunnel) { $processes.tunnel = @{ id = $tunnel.Id; started = $tunnel.StartTime.ToUniversalTime().ToString('o') } }
    $processes | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $state 'processes.json') -Encoding utf8
    $url = if ($publicUrl) { $publicUrl } else { 'http://127.0.0.1:8787' }
    $code = Get-Content -LiteralPath (Join-Path $state 'access-code.txt') -Raw
    "千迷AI手機連線`r`n網址：$url`r`n私人連線碼：$($code.Trim())`r`n請勿分享此檔案或連線碼。`r`n停止：tools\stop-mobile.ps1" | Set-Content -LiteralPath (Join-Path $state 'connection-info.txt') -Encoding utf8
    Write-Host "Mobile URL: $url"
    Write-Host "Connection code: $state\connection-info.txt"
} catch {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id }
    if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id }
    throw
} finally {
    Remove-Item Env:\QIANMI_PUBLIC_URL -ErrorAction SilentlyContinue
}
