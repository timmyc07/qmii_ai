param(
    [string]$Source = 'C:\Users\Yumai\Downloads\Comfy UI & Lora',
    [string]$ModelRoot = 'D:\AI\ComfyUI-Models'
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$checkpoint = Join-Path $Source 'flux1-dev-fp8.safetensors'
$expectedHash = '8e91b68084b53a7fc44ed2a3756d821e355ac1a7b6fe29be760c1db532f3d88a'
if (-not (Test-Path -LiteralPath $checkpoint -PathType Leaf)) { throw "Missing checkpoint: $checkpoint" }
if ((Get-Item -LiteralPath $checkpoint).Length -ne 17246524772 -or
    (Get-FileHash -LiteralPath $checkpoint -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
    throw 'FLUX checkpoint is incomplete or differs from the official Comfy-Org release.'
}
$files = @(@{ Source = $checkpoint; Folder = 'checkpoints'; File = 'flux1-dev-fp8.safetensors'; Hash = $expectedHash })
$catalog = Get-Content -LiteralPath (Join-Path $repoRoot 'config\creation_library.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($item in $catalog.loras | Where-Object { $_.workflow -eq 'flux' }) {
    $origin = Join-Path (Join-Path $Source 'CHROMA') $item.file
    if (-not (Test-Path -LiteralPath $origin -PathType Leaf) -or (Get-Item -LiteralPath $origin).Length -eq 0) { throw "Missing LoRA: $origin" }
    $files += @{ Source = $origin; Folder = 'loras'; File = $item.file; Hash = (Get-FileHash -LiteralPath $origin -Algorithm SHA256).Hash.ToLowerInvariant() }
}
foreach ($item in $files) {
    $folder = Join-Path $ModelRoot $item.Folder
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    $target = Join-Path $folder $item.File
    if (Test-Path -LiteralPath $target) {
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.Hash) { throw "Existing model differs: $target" }
    } else {
        Copy-Item -LiteralPath $item.Source -Destination $target
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.Hash) { throw "Copy verification failed: $target" }
    }
    Write-Host "Verified: $($item.File)"
}
