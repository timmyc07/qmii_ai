param([string]$ModelRoot = 'D:\AI\ComfyUI-Models')
$ErrorActionPreference = 'Stop'

# Published Hugging Face LFS SHA256 values; only verified files become visible to ComfyUI.
$files = @(
    @{ Repo = 'silveroxides/Chroma1-HD-fp8-scaled'; File = 'Chroma1-HD-fp8_scaled_defaultloader_hybrid_large_rev2.safetensors'; Folder = 'diffusion_models'; Size = 9193371409; Hash = 'f8df6efac8f9c4e778ec07b9c9362d43612cd6874271d602df90b34f72552931' },
    @{ Repo = 'comfyanonymous/flux_text_encoders'; File = 't5xxl_fp8_e4m3fn_scaled.safetensors'; Folder = 'text_encoders'; Size = 5157348688; Hash = 'a498f0485dc9536735258018417c3fd7758dc3bccc0a645feaa472b34955557a' },
    @{ Repo = 'lodestones/Chroma'; File = 'ae.safetensors'; Folder = 'vae'; Size = 335304388; Hash = 'afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38' }
)
foreach ($item in $files) {
    $folder = Join-Path $ModelRoot $item.Folder
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    $target = Join-Path $folder $item.File
    if (Test-Path -LiteralPath $target) {
        if ((Get-Item -LiteralPath $target).Length -eq $item.Size -and (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -eq $item.Hash) {
            Write-Host "Verified: $target"
            continue
        }
        throw "Existing file failed verification: $target"
    }
    $partial = "$target.part"
    if (Test-Path -LiteralPath "$partial.aria2") { throw "aria2 download is incomplete; finish it before installing: $partial" }
    if (-not (Test-Path -LiteralPath $partial) -or (Get-Item -LiteralPath $partial).Length -ne $item.Size) {
        Write-Host "Downloading: $($item.File)"
        curl.exe --fail --location --retry 5 --retry-delay 3 --continue-at - --output $partial "https://huggingface.co/$($item.Repo)/resolve/main/$($item.File)"
        if ($LASTEXITCODE -ne 0) { throw "Download failed; rerun to resume: $partial" }
    }
    if ((Get-Item -LiteralPath $partial).Length -ne $item.Size -or (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.Hash) {
        throw "Download failed size/SHA256 verification: $partial"
    }
    Move-Item -LiteralPath $partial -Destination $target
    Write-Host "Installed and verified: $target"
}
