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
