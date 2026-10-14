# 模型與雜湊

模型維持在 `D:\AI\ComfyUI-Models`，不搬入 repo、不提交 Git，也不打包進執行檔。下表於 2026-10-14 完成實檔雜湊驗證。

| 本機相對路徑 | Bytes | SHA-256 | 本次實際來源 |
| --- | ---: | --- | --- |
| `diffusion_models/qwen_image_2.1_int8_convrot.safetensors` | 7,256,783,064 | `CB74113CB03FAECD79611B01FD7FD642F0AA60D6F0B95086ABEE214D75EAA57D` | `Comfy-Org/Qwen-Image-2.1` |
| `text_encoders/qwen3vl_8b_int8_convrot.safetensors` | 9,350,798,360 | `8BFD0F6E12ABF2D2D697ECC888E5E90B0D6741D6708F05799F53AFA560452E8F` | `Comfy-Org/Qwen-Image-2.1` |
| `vae/qwen_image_2.1_vae_bf16.safetensors` | 675,509,688 | `BB21F7473051E1AC368515DD3F2E15CD44D7A11748EE8823E1DDCA3E4876B7C9` | `Comfy-Org/Qwen-Image-2.1` |
| `loras/qwen2_1-femaledVaginus-nsfw-v1_3-fine_L22-31.safetensors` | 637,587,392 | `4E1B8DB3EF339AAE3B5D2EF6D9B5C0261329559B6DA790481535EBBA9DE77685` | `mpasila/Qwen-Image-2.1-LoRAs` mirror |
| `loras/qwen21-nsfw-image-edit.safetensors` | 83,943,552 | `9C143CBFE7B016EFDCE7499506C02D0BFA1842AE6524BB64E05888F2E325E67A` | `mpasila/Qwen-Image-2.1-LoRAs` mirror（本機改名） |

LoRA mirror 並非原始受限下載端點；此表忠實記錄本次取得來源。重新安裝前應重新核對來源授權與雜湊。

來源頁面：

- 底模：<https://huggingface.co/Comfy-Org/Qwen-Image-2.1/tree/main>
- 本次 LoRA mirror：<https://huggingface.co/mpasila/Qwen-Image-2.1-LoRAs/tree/main>
- 工作流原始安裝說明：<https://github.com/Arekejoker/qwen21-nsfw-pose-skill/blob/4ca900d/install/setup.md>

模型與 LoRA 的授權以各來源頁面當下顯示的條款為準；本 repo 不授予第三方模型權利。
