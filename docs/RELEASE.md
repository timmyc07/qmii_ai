# 發行流程

1. 執行 Python、桌面與手機 UI 測試，以及 `cargo check --manifest-path src-tauri\Cargo.toml`。
2. 執行 `tools\build.ps1`。
3. 確認 `dist\千迷AI.exe`、`dist\千迷AI-0.4.1.exe` 與 `dist\SHA256SUMS.txt` 存在。
4. 提交並推送原始碼；需要公開發行時再建立 tag 與 GitHub Release。

`dist`、模型、runtime、日誌與生成圖片不提交 Git。目前 portable EXE 依賴本機 `D:\AI\Qwen-Image-2.1-Turbo`。

## 0.4.1

- 移除 ComfyUI、Chroma、FLUX、Wan、Qwen Pose 工作流與全部 LoRA 整合。
- 只保留 Qwen Image 2.1 Turbo 的快速生成、逐張修改與多圖參考。
