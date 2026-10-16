param(
    [string]$WorkflowSource = (Join-Path $env:USERPROFILE 'Downloads\qwenImage21SuperDuper_v2.json'),
    [string]$LoraSource = (Join-Path $env:USERPROFILE 'Downloads\pussyV2.safetensors'),
    [string]$PenisLoraSource = (Join-Path $env:USERPROFILE 'Downloads\qwen2.1_penisV01_000004956.safetensors'),
    [string]$LokrSource = (Join-Path $env:USERPROFILE 'Downloads\qwen-image_nsfw_adv_v1.0.safetensors')
)

$ErrorActionPreference = 'Stop'

$runtime = 'D:\AI\QwenImage21SuperDuper'
$portable = Join-Path $runtime 'ComfyUI_windows_portable'
$comfy = Join-Path $portable 'ComfyUI'
$python = Join-Path $portable 'python_embeded\python.exe'
$archive = Join-Path $runtime 'ComfyUI_windows_portable_nvidia.7z'

function Get-RemoteFile([string]$Url, [string]$Destination) {
    if (Test-Path -LiteralPath $Destination) {
        Write-Host "Already present: $Destination"
        return
    }
    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    & curl.exe -L --fail --retry 5 --retry-delay 3 -C - -o "$Destination.part" $Url
    if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url" }
    Move-Item -LiteralPath "$Destination.part" -Destination $Destination
}

if (-not (Test-Path -LiteralPath $WorkflowSource)) { throw "Workflow not found: $WorkflowSource" }
if (-not (Test-Path -LiteralPath $LoraSource)) { throw "LoRA not found: $LoraSource" }
if (-not (Test-Path -LiteralPath $PenisLoraSource)) { throw "LoRA not found: $PenisLoraSource" }
if (-not (Test-Path -LiteralPath $LokrSource)) { throw "LoKr not found: $LokrSource" }
$lokrHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $LokrSource).Hash
if ($lokrHash -ne '210E840D99F8152D503665C7AD43724EDDDD4CE3FDF11FA15839E8146C96F018') {
    throw "LoKr SHA256 mismatch: $lokrHash"
}
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

if (-not (Test-Path -LiteralPath $python)) {
    Get-RemoteFile 'https://github.com/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia.7z' $archive
    & tar.exe -xf $archive -C $runtime
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $python)) { throw 'ComfyUI Portable extraction failed.' }
}

Copy-Item -LiteralPath $WorkflowSource -Destination (Join-Path $runtime 'qwenImage21SuperDuper_v2.json') -Force
New-Item -ItemType Directory -Force -Path (Join-Path $comfy 'models\loras') | Out-Null
Copy-Item -LiteralPath $LoraSource -Destination (Join-Path $comfy 'models\loras\pussyV2.safetensors') -Force
Copy-Item -LiteralPath $PenisLoraSource -Destination (Join-Path $comfy 'models\loras\qwen2.1_penisV01_000004956.safetensors') -Force
& $python -s (Join-Path $PSScriptRoot 'prepare_qwen_lora.py') $PenisLoraSource (Join-Path $comfy 'models\loras\qwen2.1_penisV01_000004956_comfy.safetensors')
if ($LASTEXITCODE -ne 0) { throw 'SuperDuper LoRA preparation failed.' }
Copy-Item -LiteralPath $LokrSource -Destination (Join-Path $comfy 'models\loras\qwen-image_nsfw_adv_v1.0.safetensors') -Force

$vaeTarget = Join-Path $comfy 'models\vae\qwen_image_2.1_vae_bf16.safetensors'
$vaeSource = 'D:\AI\Qwen-Image-2.1-Turbo\models\qwen_image_2.1_vae_bf16.safetensors'
if (-not (Test-Path -LiteralPath $vaeTarget)) {
    if (-not (Test-Path -LiteralPath $vaeSource)) { throw "Turbo VAE not found: $vaeSource" }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $vaeTarget) | Out-Null
    New-Item -ItemType HardLink -Path $vaeTarget -Target $vaeSource | Out-Null
}

$customNodes = Join-Path $comfy 'custom_nodes'
$impact = Join-Path $customNodes 'ComfyUI-Impact-Pack'
$subpack = Join-Path $customNodes 'ComfyUI-Impact-Subpack'
$res4lyf = Join-Path $customNodes 'RES4LYF'
if (-not (Test-Path -LiteralPath (Join-Path $impact '.git'))) {
    & git clone --depth 1 https://github.com/ltdrdata/ComfyUI-Impact-Pack $impact
    if ($LASTEXITCODE -ne 0) { throw 'Impact Pack clone failed.' }
}
if (-not (Test-Path -LiteralPath (Join-Path $subpack '.git'))) {
    & git clone --depth 1 https://github.com/ltdrdata/ComfyUI-Impact-Subpack $subpack
    if ($LASTEXITCODE -ne 0) { throw 'Impact Subpack clone failed.' }
}
if (-not (Test-Path -LiteralPath (Join-Path $res4lyf '.git'))) {
    & git clone --depth 1 https://github.com/ClownsharkBatwing/RES4LYF $res4lyf
    if ($LASTEXITCODE -ne 0) { throw 'RES4LYF clone failed.' }
}
New-Item -ItemType File -Force -Path (Join-Path $impact 'skip_download_model') | Out-Null
foreach ($node in @($impact, $subpack, $res4lyf)) {
    $requirements = Join-Path $node 'requirements.txt'
    if (Test-Path -LiteralPath $requirements) {
        & $python -s -m pip install -r $requirements
        if ($LASTEXITCODE -ne 0) { throw "Custom node requirements failed: $node" }
    }
}
$impactInstaller = Join-Path $impact 'install.py'
if (Test-Path -LiteralPath $impactInstaller) {
    & $python -s $impactInstaller
    if ($LASTEXITCODE -ne 0) { throw 'Impact Pack install.py failed.' }
}

$baseUrl = 'https://huggingface.co/Kutches/Qwen/resolve/2e407eb8da4172512aacef61be1fe5aa84a12f1d/redqw21UNLOCKEDV2TI2I_redqw21UNLOCKEDV2_3258922.safetensors'
$downloads = @(
    @('https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_fp8_e4m3fn.safetensors', 'models\diffusion_models\qwen_image_fp8_e4m3fn.safetensors'),
    @('https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors', 'models\text_encoders\qwen_2.5_vl_7b_fp8_scaled.safetensors'),
    @('https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors', 'models\vae\qwen_image_vae.safetensors'),
    @('https://huggingface.co/lightx2v/Qwen-Image-Lightning/resolve/main/Qwen-Image-Lightning-8steps-V2.0-bf16.safetensors', 'models\loras\Qwen-Image-Lightning-8steps-V2.0-bf16.safetensors'),
    @('https://huggingface.co/abenzerps/Qwen-Image-2.1-Uncensored-GGUF/resolve/main/text_encoders/qwen3vl_8b_int8_convrot.safetensors', 'models\text_encoders\qwen3vl_8b_int8_convrot.safetensors'),
    @('https://huggingface.co/Outimus/Adetailer/resolve/main/face_yolov8m.pt', 'models\ultralytics\bbox\face_yolov8m.pt'),
    @('https://huggingface.co/Bryan32/Adetailer/resolve/main/female-breast-v4.7.pt', 'models\ultralytics\bbox\female-breast-v4.7.pt'),
    @('https://huggingface.co/Dhivimhotep/adetailer/resolve/main/pussyV2.pt', 'models\ultralytics\bbox\pussyV2.pt'),
    @('https://huggingface.co/ThirdTimesTheCiarc/misc/resolve/main/301092/2947933/cockAndBallDetection_v20.pt', 'models\ultralytics\segm\cockAndBallDetection_v20.pt'),
    @('https://huggingface.co/datasets/Gourieff/ReActor/resolve/main/models/sams/sam_vit_b_01ec64.pth', 'models\sams\sam_vit_b_01ec64.pth'),
    @($baseUrl, 'models\diffusion_models\redqw21UNLOCKEDV2TI2I_redqw21UNLOCKEDV2_int8.safetensors')
)
foreach ($item in $downloads) { Get-RemoteFile $item[0] (Join-Path $comfy $item[1]) }

$superDuperBase = Join-Path $comfy 'models\diffusion_models\redqw21UNLOCKEDV2TI2I_redqw21UNLOCKEDV2_int8.safetensors'
$superDuperHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $superDuperBase).Hash
if ($superDuperHash -ne '30532B445EABD4B84B108168B6B3FE720535EF400F6BF9D68BD551817D3531A3') {
    throw "SuperDuper base SHA256 mismatch: $superDuperHash"
}

$required = @(
    'main.py',
    'models\diffusion_models\redqw21UNLOCKEDV2TI2I_redqw21UNLOCKEDV2_int8.safetensors',
    'models\text_encoders\qwen3vl_8b_int8_convrot.safetensors',
    'models\vae\qwen_image_2.1_vae_bf16.safetensors',
    'models\loras\pussyV2.safetensors',
    'models\loras\qwen2.1_penisV01_000004956.safetensors',
    'models\loras\qwen2.1_penisV01_000004956_comfy.safetensors',
    'models\diffusion_models\qwen_image_fp8_e4m3fn.safetensors',
    'models\text_encoders\qwen_2.5_vl_7b_fp8_scaled.safetensors',
    'models\vae\qwen_image_vae.safetensors',
    'models\loras\Qwen-Image-Lightning-8steps-V2.0-bf16.safetensors',
    'models\loras\qwen-image_nsfw_adv_v1.0.safetensors',
    'models\ultralytics\bbox\face_yolov8m.pt',
    'models\ultralytics\bbox\female-breast-v4.7.pt',
    'models\ultralytics\bbox\pussyV2.pt',
    'models\ultralytics\segm\cockAndBallDetection_v20.pt',
    'models\sams\sam_vit_b_01ec64.pth'
)
foreach ($relative in $required) {
    $path = Join-Path $comfy $relative
    if (-not (Test-Path -LiteralPath $path) -or (Get-Item -LiteralPath $path).Length -eq 0) { throw "Missing file: $path" }
}
Write-Host "ComfyUI SuperDuper runtime ready: $portable"
