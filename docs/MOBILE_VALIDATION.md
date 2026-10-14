# 手機版驗證紀錄

驗證日期：2026-10-14，Windows本機環境。

- 手機API測試：登入、Origin、CSRF、受保護圖片、上傳格式與大小限制、單工佇列、重複請求冪等、重啟恢復、安全停止。
- 模型錯誤測試：ComfyUI成功空回應、逾時只取消自己的任務。
- HTTPS登入測試：在本機TestClient驗證Secure與HttpOnly Cookie。
- Rust與Python跨程序鎖互斥測試通過。
- JavaScript語法、Rust fmt與clippy檢查通過。
- 真實Turbo生成與Qwen圖片Edit均經手機API生成並成功下載PNG。
- 曾經透過前一個臨時HTTPS網址完成登入、生成與下載；最後安全重啟會取得新網址。
- 瀏覽器確認390px與360px寬度無水平溢出；圖片修改訊息沒有提示詞文字。
- 最後重啟後的新網址僅驗證未登入的公開首頁。再次透過Cloudflare傳送私人連線碼的自動驗證被安全審核拒絕，須取得使用者對該傳輸的明確授權後再進行。
- 尚未使用真實Android或iPhone硬體驗證加入主畫面，亦未建立固定Cloudflare網域。

本版本的私人連線碼用於個人手機與自己的電腦配對；商業卡密系統仍只有計畫。

## 0.2.6 桌面手機面板（2026-10-14）

- 實作前完成 GitHub 深層程式搜尋及三個獨立 agent 的官方文件、程式／部署、專案慣例審查；重用現有背景程序與手機啟停流程，不新增執行期套件。
- `cargo test`：跨 Rust/Python GPU 鎖測試通過；`cargo clippy --all-targets -- -D warnings`、`cargo fmt --check` 與 JavaScript 語法檢查通過。
- 手機既有 Python 測試共 9 項通過，包含登入、HTTPS Cookie、Origin/CSRF、單工佇列與 drain。
- `tools/test-mobile-session.ps1` 通過：無服務、過期紀錄不洩露資訊、有效程序身分、重用 PID 略過、跨程序啟停鎖。
- `tools/test-mobile-ui.cjs` 使用模擬 Tauri 的 Edge/Playwright 測試通過：啟動中關閉／重開面板、代碼預設隱藏、1280/390/360px 無面板水平溢出、安全停止狀態、過期紀錄、狀態錯誤與恢復。執行需測試環境可取得 Playwright（可透過 NODE_PATH）；不需要雲端或登入憑證。
- 真實 PowerShell start/status/stop 流程通過；本機狀態確認程序、HTTPS 網址格式與私人碼存在，未輸出私人碼。公開 HTTPS 首頁回傳 200，未傳送私人碼。
- 0.2.6 真實桌面 EXE 已開啟並檢查面板，Tauri 啟動／安全停止按鈕與實際服務狀態一致，操作日誌未含私人碼。
- release 建置完成，產生 `dist/千迷AI.exe`、`dist/千迷AI-0.2.6.exe` 與 SHA256SUMS；修正既有 build.ps1 的 Windows PowerShell UTF-8 BOM／設定讀取編碼，使中文檔名可正確建置。
- 本次未重跑 GPU 生圖 smoke（生成程式未更動），未使用實體手機驗證，也未透過公開通道傳送私人連線碼。Quick Tunnel 仍為暫時網址。

- 真實桌面測試發現並修正 Windows 子程序繼承 capture pipe 導致啟動一直等待的問題：啟停命令改為 null stdio + status 等待；只有狀態查詢捕獲 JSON。
- 修正後再次從最終 EXE 按「開啟手機連線」，確認命令完成、等待狀態解除並顯示 HTTPS 網址與遮蔽代碼；安全停止亦由桌面按鈕實測。
