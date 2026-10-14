# Third-party notices

千迷AI會在本機使用下列外部元件，但不把其模型或未授權原始碼提交到本 repository：

- ComfyUI / Comfy-Org Qwen-Image-2.1：依各上游授權使用。
- `Arekejoker/qwen21-nsfw-pose-skill` commit `4ca900d`：上游目前未附 LICENSE。本 repo 僅記錄相依來源；本機 `.runtime` 不進 Git。
- Qwen Image 模型與 LoRA：來源與雜湊列於 `docs/MODELS.md`，權利與使用條款依各模型上游頁面。
- 手機服務使用 FastAPI（MIT）、Uvicorn（BSD-3-Clause）、Pillow（MIT-CMU）與httpx（BSD-3-Clause），由Python套件安裝取得。
- HTTPS連線使用 Cloudflare cloudflared（Apache-2.0）官方執行檔，放於被Git排除的`.runtime`，版本與雜湊見`docs/MOBILE.md`。
