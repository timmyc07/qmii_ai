param(
    [string]$Source = 'C:\Users\Yumai\Downloads\Comfy UI & Lora',
    [string]$ModelRoot = 'D:\AI\ComfyUI-Models'
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$catalog = Get-Content -LiteralPath (Join-Path $repoRoot 'config\creation_library.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$loraRoot = Join-Path $ModelRoot 'loras'
New-Item -ItemType Directory -Path $loraRoot -Force | Out-Null
foreach ($item in $catalog.loras | Where-Object { $_.workflow -ne 'wan_template' }) {
    if ($item.modes.Count -eq 0) { Write-Host "Excluded (unconfirmed Chroma compatibility): $($item.file)"; continue }
    $category = if ($item.workflow -eq 'flux') { 'CHROMA' } else { 'QWEN' }
    $origin = Join-Path (Join-Path $Source $category) $item.file
    $target = Join-Path $loraRoot $item.file
    if (-not (Test-Path -LiteralPath $origin -PathType Leaf)) { throw "Missing source: $origin" }
    $digest = (Get-FileHash -LiteralPath $origin -Algorithm SHA256).Hash
    if (Test-Path -LiteralPath $target) {
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $digest) { throw "Existing model differs: $target" }
    } else {
        Copy-Item -LiteralPath $origin -Destination $target
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $digest) { throw "Copy verification failed: $target" }
    }
    Write-Host "Verified: $($item.file)"
}
$archiveRoot = Join-Path $repoRoot '.runtime\creation_library'
New-Item -ItemType Directory -Path $archiveRoot -Force | Out-Null
foreach ($item in $catalog.templates | Where-Object { $_.id -like 'chroma_*' }) {
    $origin = Join-Path (Join-Path $Source 'CHROMA') $item.archive
    $target = Join-Path $archiveRoot $item.archive
    if (Test-Path -LiteralPath $target) {
        if ((Get-FileHash -LiteralPath $target).Hash -ne (Get-FileHash -LiteralPath $origin).Hash) { throw "Existing archive differs: $target" }
    } else { Copy-Item -LiteralPath $origin -Destination $target }
    Write-Host "Archived for dependency review: $($item.archive)"
}
