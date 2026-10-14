$ErrorActionPreference = 'Stop'

$modelRoot = 'D:\AI\ComfyUI-Models'
$expected = @(
    @{ Path = 'diffusion_models\qwen_image_2.1_int8_convrot.safetensors'; Length = 7256783064; Hash = 'CB74113CB03FAECD79611B01FD7FD642F0AA60D6F0B95086ABEE214D75EAA57D' },
    @{ Path = 'text_encoders\qwen3vl_8b_int8_convrot.safetensors'; Length = 9350798360; Hash = '8BFD0F6E12ABF2D2D697ECC888E5E90B0D6741D6708F05799F53AFA560452E8F' },
    @{ Path = 'vae\qwen_image_2.1_vae_bf16.safetensors'; Length = 675509688; Hash = 'BB21F7473051E1AC368515DD3F2E15CD44D7A11748EE8823E1DDCA3E4876B7C9' },
    @{ Path = 'loras\qwen2_1-femaledVaginus-nsfw-v1_3-fine_L22-31.safetensors'; Length = 637587392; Hash = '4E1B8DB3EF339AAE3B5D2EF6D9B5C0261329559B6DA790481535EBBA9DE77685' },
    @{ Path = 'loras\qwen21-nsfw-image-edit.safetensors'; Length = 83943552; Hash = '9C143CBFE7B016EFDCE7499506C02D0BFA1842AE6524BB64E05888F2E325E67A' }
)

foreach ($item in $expected) {
    $path = Join-Path $modelRoot $item.Path
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing model: $path" }
    $file = Get-Item -LiteralPath $path
    if ($file.Length -ne $item.Length) { throw "Size mismatch: $path" }
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    if ($hash -ne $item.Hash) { throw "SHA-256 mismatch: $path" }
    Write-Host "OK $($item.Path)"
}

Write-Host 'All Qwen 2.1 model files verified.'
