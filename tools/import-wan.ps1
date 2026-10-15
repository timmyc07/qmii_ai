param(
    [string]$Source = 'C:\Users\Yumai\Downloads\Wan 2.2 Comfy UI & Lora',
    [string]$ModelRoot = 'D:\AI\ComfyUI-Models'
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$files = @(
    @{ Name = 'NSFW-22-H-e8.safetensors'; Folder = 'loras' },
    @{ Name = 'X-ray_creampie_high.safetensors'; Folder = 'loras' },
    @{ Name = 'wan22EnhancedNSFWSVICamera_nsfwFASTMOVEV2Q8H.gguf'; Folder = 'unet' },
    @{ Name = 'wan22NSFWI2VWorkflowOrSFW_v10.zip'; Folder = '' }
)
foreach ($item in $files) {
    $origin = Join-Path $Source $item.Name
    if (-not (Test-Path -LiteralPath $origin -PathType Leaf)) { throw "Missing download: $origin" }
    $folder = if ($item.Folder) { Join-Path $ModelRoot $item.Folder } else { Join-Path $repoRoot '.runtime\creation_library' }
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    $target = Join-Path $folder $item.Name
    if (-not (Test-Path -LiteralPath $target)) { Copy-Item -LiteralPath $origin -Destination $target }
    if ((Get-FileHash -LiteralPath $origin -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash) {
        throw "Imported file does not match download: $target"
    }
    Write-Host "Verified: $($item.Name)"
}
Write-Host 'Wan 5B is ready with the installed models. The 14B recipe additionally requires its low-noise GGUF, Wan 2.1 VAE and CLIP Vision H; see docs/WAN.md.'
