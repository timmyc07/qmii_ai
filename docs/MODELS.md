# 模型

千迷AI使用 `D:\AI\Qwen-Image-2.1-Turbo` 與 `D:\AI\QwenImage21SuperDuper`；模型不搬入 repository、不提交 Git，也不打包進 EXE。

必要檔案：

- `sd-cli.exe`
- `models\Qwen-Image-2.1-Turbo-AD-Q4_K.gguf`
- `models\Qwen-Image-2.1-Turbo-Abliterated-Uncensored-AD-Q4_K.gguf`
- `models\qwen_image_2.1_vae_bf16.safetensors`
- 圖片修改與多圖參考另需 `models\mmproj-Qwen-Image-2.1-Turbo-Abliterated-Uncensored-BF16.gguf`

SuperDuper 使用官方最新版 ComfyUI Portable、Impact Pack、Impact Subpack、工作流指定的 Qwen 2.1 模型與偵測模型，以及使用者提供的 `pussyV2.safetensors`、`qwen2.1_penisV01_000004956.safetensors`。執行 `tools\install-superduper.ps1 -CivitaiToken <本機 token>` 可安裝或補齊；Civitai token 只作為程序參數，不會儲存。工作流原本引用但未提供的 `NSFW Qwen by TheseAlpacas V2.safetensors` 不會自動加入。第三方模型權利仍以來源條款為準。

NSFW Adv 群組共用同一套 ComfyUI，但使用獨立的 Qwen Image FP8、Qwen 2.5 VL text encoder、Qwen Image VAE、`qwen-image_nsfw_adv_v1.0.safetensors`、Lightning 8-step V2 與 RES4LYF。預設依作者建議為 10 steps、CFG 1、LoKr 1.0、Lightning 0.45、`res_2s` + `bong_tangent`。

精準模式使用官方 Qwen Image 2.1 PE T2I／I2I text encoder 與本機 `precision_prompt.md`。模型、LoRA、LoKr、模板與 ComfyUI runtime 都只保存在 `D:\AI\QwenImage21SuperDuper`，不提交 Git。
