# 模型

千迷AI使用 `D:\AI\Qwen-Image-2.1-Turbo` 與 `D:\AI\QwenImage21SuperDuper`；模型不搬入 repository、不提交 Git，也不打包進 EXE。

必要檔案：

- `sd-cli.exe`
- `models\Qwen-Image-2.1-Turbo-AD-Q4_K.gguf`
- `models\Qwen-Image-2.1-Turbo-Abliterated-Uncensored-AD-Q4_K.gguf`
- `models\qwen_image_2.1_vae_bf16.safetensors`
- 圖片修改與多圖參考另需 `models\mmproj-Qwen-Image-2.1-Turbo-Abliterated-Uncensored-BF16.gguf`

SuperDuper 使用官方最新版 ComfyUI Portable、Impact Pack、Impact Subpack、工作流指定的 Qwen 2.1 模型與偵測模型，以及使用者提供的 `pussyV2.safetensors`、`qwen2.1_penisV01_000004956.safetensors`。執行 `tools\install-superduper.ps1` 可安裝或補齊；基礎 INT8 模型使用固定版本的 Hugging Face 鏡像，SHA256 為 `30532b445eabd4b84b108168b6b3fe720535ef400f6bf9d68bd551817d3531a3`，不需要 token。工作流原本引用但未提供的 `NSFW Qwen by TheseAlpacas V2.safetensors` 不會自動加入。第三方模型權利仍以來源條款為準。

NSFW Adv 群組共用同一套 ComfyUI，但使用獨立的 Qwen Image FP8、Qwen 2.5 VL text encoder、Qwen Image VAE、`qwen-image_nsfw_adv_v1.0.safetensors`、Lightning 8-step V2 與 RES4LYF。預設依作者建議為 10 steps、CFG 1、LoKr 1.0、Lightning 0.45、`res_2s` + `bong_tangent`。

安裝器保留局部細修 LoRA 原檔，另產生 `_comfy.safetensors` 版本；將合併的 `gate_up` LoRA 投影等價拆為 `gate_layer`／`proj`，供 ComfyUI 完整載入。可使用 portable Python 執行 `tools\test_qwen_lora.py` 驗證拆分前後的投影等價性。

精準模式的生成規範整理自使用者模板，由程式直接附加，不再依賴 PE T2I／I2I text encoder 或本機模板檔。已下載的 PE 模型保留在本機，但程式不再載入，也不再自動下載。模型、LoRA、LoKr 與 ComfyUI runtime 只保存在 `D:\AI\QwenImage21SuperDuper`，不提交 Git。
