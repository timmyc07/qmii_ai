$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$manifest = Join-Path $repoRoot 'src-tauri\Cargo.toml'
$release = Join-Path $repoRoot 'src-tauri\target\release\qianmi-ai.exe'
$dist = Join-Path $repoRoot 'dist'

cargo build --release --manifest-path $manifest
if ($LASTEXITCODE -ne 0) { throw 'Cargo release build failed.' }

New-Item -ItemType Directory -Path $dist -Force | Out-Null
Copy-Item -LiteralPath $release -Destination (Join-Path $dist '千迷AI.exe') -Force
$version = (Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\tauri.conf.json') -Raw | ConvertFrom-Json).version
$versioned = Join-Path $dist "千迷AI-$version.exe"
Copy-Item -LiteralPath $release -Destination $versioned -Force
$digest = (Get-FileHash -LiteralPath $versioned -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath (Join-Path $dist 'SHA256SUMS.txt') -Value "$digest  千迷AI-$version.exe" -Encoding utf8
Write-Host "Build artifacts: $dist"
