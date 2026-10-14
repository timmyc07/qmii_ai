# 發行流程

1. 執行 `tools\setup-workflow.ps1`、`tools\verify-models.ps1` 與必要 smoke tests。
2. 執行 `tools\build.ps1`，確認 `dist\千迷AI.exe` 與帶版本檔案存在。
3. 對版本檔執行 `Get-FileHash -Algorithm SHA256`，將結果保存為 `dist\SHA256SUMS.txt`。
4. 提交並推送原始碼，建立 `v0.2.4` tag。
5. 在 GitHub Release 上傳 `千迷AI-0.2.4.exe` 與 `SHA256SUMS.txt`。

`dist` 不提交 Git。這個 portable EXE 目前只支援文件記錄的本機環境；若日後改為通用安裝版，應使用 Tauri NSIS/MSI bundle 並移除硬編碼的本機 ComfyUI 路徑。
