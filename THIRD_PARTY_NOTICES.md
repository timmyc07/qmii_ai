# Third-party notices

Wan 影片使用 ComfyUI 官方 Wan 節點與既有 ComfyUI-GGUF；補齊模型來自 QuantStack/Wan2.2-I2V-A14B-GGUF 與 Comfy-Org/Wan_2.1_ComfyUI_repackaged，依上游模型授權使用。使用者下載的範本與 LoRA 保留本機，其來源、適配限制與整合差異見 `docs/WAN.md`，不隨 EXE 或 Git 分發。

千迷AI會在本機使用下列外部元件，但不把其模型或未授權原始碼提交到本 repository：

- ComfyUI / Comfy-Org Qwen-Image-2.1：依各上游授權使用。
- `Arekejoker/qwen21-nsfw-pose-skill` commit `4ca900d`：上游目前未附 LICENSE。本 repo 僅記錄相依來源；本機 `.runtime` 不進 Git。
- Qwen Image 模型與 LoRA：來源與雜湊列於 `docs/MODELS.md`，權利與使用條款依各模型上游頁面。
- 手機服務使用 FastAPI（MIT）、Uvicorn（BSD-3-Clause）、Pillow（MIT-CMU）與httpx（BSD-3-Clause），由Python套件安裝取得。
- HTTPS連線使用 Cloudflare cloudflared（Apache-2.0）官方執行檔，放於被Git排除的`.runtime`，版本與雜湊見`docs/MOBILE.md`。
- Chroma 範本使用 ComfyUI-GGUF（Apache-2.0）、ComfyUI-KJNodes（GPL-3.0）、Impact Pack（GPL-3.0）、Impact Subpack（AGPL-3.0）、Ultimate SD Upscale（GPL-3.0）、ControlNet Aux（Apache-2.0）與 Sigmoid Offset Scheduler（MIT）；原始節點及 LICENSE 保留在本機 `.runtime/chroma/nodes`，固定 commit 見 `config/chroma_dependencies.json`。
- Eses Image Effect Curves 採上游自訂的 "My ComfyUI Nodes License"；授權原文保留在該節點的 `LICENSE.txt`。上述第三方節點原始碼與模型不包入本 repository 或桌面 EXE。
- Velvet Chroma、FLAN-T5、Chroma Hyper Flash、Union ControlNet、OpenPose、SAM、YOLO 與放大模型依各上游模型授權使用；下載來源與雜湊見 `config/chroma_dependencies.json`，Velvet 匯入雜湊見 `docs/STUDIO.md`。依賴安裝不代表模型授權相同。
