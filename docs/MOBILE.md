# 千迷AI手機網頁與PWA

手機透過 HTTPS 網頁連接這台 Windows 電腦，由本機 GPU 執行 Turbo 或 Qwen 2.1。模型位置維持 `D:\AI`。本版本是單一擁有者的私人工作室，所有已配對的手機共用創作紀錄；正式商業卡密系統仍依 `LICENSING_PLAN.md` 另行實作。

## 桌面應用內使用（0.2.6 起）

1. 開啟千迷AI，點頂部「手機連線」。
2. 按「開啟手機連線」，等待手機服務與 HTTPS 通道啟動；首次需安裝 Python 套件，可能較久。
3. 複製網址到自己的手機瀏覽器，並輸入面板中的私人連線碼。連線碼預設隱藏，可按「顯示連線碼」或直接複製。
4. 不使用時按「停止連線」。若正在生成，面板會持續顯示停止中，等工作完成再關閉服務。

預設不自動啟動。關閉桌面視窗不會停止手機服務，可重新開啟桌面面板管理；操作進行中請等待完成後再關閉視窗。重啟會換新網址。面板每十秒更新一次，關閉面板即停止輪詢；頂部徽章在開啟應用、面板及完成操作時更新。顯示「已開啟」代表本機服務與通道程序已通過檢查，不代表已偵測到手機登入或保證外部網路可達。

狀態檢查會核對程序 PID、建立時間與本機 HTTP 回應，只有服務與通道有效時才提供網址及代碼。過期紀錄可按「重新連線」處理；若 PID 已被其他程序重用，會將原服務視為已結束並略過該程序，避免誤停其他工作。啟停具跨程序互斥鎖。操作事件在 `.runtime/mobile/desktop.log`，腳本錯誤在 `.runtime/mobile/desktop-control.log`，不記錄私人連線碼。

## 指令啟動與疑難排解

在 `D:\codes\qmii_ai` 執行：

```powershell
# 只在電腦本機測試
powershell -ExecutionPolicy Bypass -File tools\start-mobile.ps1

# 提供手機可連線的 HTTPS 網址
powershell -ExecutionPolicy Bypass -File tools\start-mobile.ps1 -Public
```

第一次啟動會建立 `.runtime\mobile-venv` 並安裝 `mobile\requirements.txt`。Python需3.12以上。公開模式需將官方 Windows amd64 `cloudflared.exe` 放在 `.runtime\cloudflared.exe`。

本次使用 Cloudflare 官方 `2026.10.0`：

- [官方下載](https://github.com/cloudflare/cloudflared/releases/download/2026.10.0/cloudflared-windows-amd64.exe)
- SHA-256：`86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c`

啟動後開啟 `.runtime\mobile\connection-info.txt`，將其中網址傳到自己的手機，輸入私人連線碼。請勿分享連線碼或這份檔案。

公開模式請一律使用 HTTPS 網址登入；其登入 Cookie 限制為 HTTPS 使用。電腦需保持開機、連網並避免休眠。

## 手機操作

1. 開啟 HTTPS 網址並輸入私人連線碼。
2. 輸入提示詞，或選擇最多四張圖片進行修改。
3. 選擇「快速生成」或「Qwen 2.1」。
4. 送出後可查看排隊及處理狀態；完成時下載圖片。

圖片修改訊息只顯示圖片，完整提示詞仍傳至電腦執行。固定提示詞可在手機本次開啟期間設定；常用按鈕讀取桌面版設定。

Android支援的瀏覽器可使用「加入主畫面」；iPhone可從Safari分享選單選擇「加入主畫面」。實際選單依瀏覽器版本而異。介面支援離線開啟，但生成、上傳與查看私人圖片需要連線。

## 停止與重新啟動

```powershell
powershell -ExecutionPolicy Bypass -File tools\stop-mobile.ps1
```

停止時先拒絕新任務，等待目前生成完成，再退出手機服務與專用HTTPS連線。尚未開始的排隊任務會保留，待下次啟動繼續。ComfyUI屬共享服務，不會被強制關閉。

若ComfyUI任務逾時，手機服務會只取消自己提交的任務並確認已停止，期間保留GPU鎖。無法確認停止時會繼續等待，以免兩個模型同時占用顯示卡；可在電腦查看ComfyUI狀態及日誌。

## 私人資料與限制

- 服務只監聽 `127.0.0.1:8787`，HTTPS Tunnel只代理這個入口，ComfyUI的8188不公開。
- 使用高熵私人連線碼、七天登入session、HttpOnly Cookie、Origin及CSRF檢查。
- 卡密計畫尚未實作；私人連線碼不具售卡、期限或裝置席次管理功能。
- 每張圖片最多12MiB、2000萬像素，最多四張；伺服器實際解碼並轉存PNG。
- 每日最多200張上傳、上傳暫存約2GiB上限、最多8個未完成任務；GPU一次只執行一項千迷AI工作。
- 桌面版0.2.5與手機服務共用 `.runtime\gpu-task.lock`。使用舊桌面版或直接操作ComfyUI不受此鎖管理，請避免同時生成。
- 圖片編輯提示詞不會出現在手機訊息或完成圖片metadata；執行期間會在本機任務資料庫暫存，成功完成後清除。
- 圖片與任務保留七天，於啟動、任務完成及空閒每小時清理。需要長期保存請下載；不會清理既有桌面版作品。
- 目前生成不能從手機取消；關閉手機頁面不會中斷電腦任務。
- 服務崩潰時，執行中的任務重啟後標記失敗；未執行任務保留。請先確認ComfyUI與Turbo沒有殘留工作再重啟。

## 本機路徑

- 程式碼：`mobile\`
- 前端：`mobile\static\`
- 登入碼、SQLite、日誌、程序紀錄：`.runtime\mobile\`
- 圖片上傳：`.runtime\mobile\uploads\`
- 完成圖片：`output\mobile\`
- 測試圖片：`output\mobile-quick-smoke.png`、`output\mobile-pose-smoke.png`

runtime、密碼、圖片、日誌與編譯產物均由Git排除。

## 驗證

新增桌面連線狀態與鎖測試：`powershell -NoProfile -ExecutionPolicy Bypass -File tools\test-mobile-session.ps1`。前端互動／responsive 測試：`node tools/test-mobile-ui.cjs`（測試環境需提供 Playwright 與 Edge，支援以 NODE_PATH 指向既有套件）。

```powershell
.runtime\mobile-venv\Scripts\python.exe -m unittest discover -s mobile\tests -v
node --check mobile\static\mobile.js
node --check mobile\static\sw.js
cargo test --manifest-path src-tauri\Cargo.toml

# 啟動服務後測試真實GPU生圖及登入保護下載
.runtime\mobile-venv\Scripts\python.exe tools\mobile-smoke.py --workflow quick
.runtime\mobile-venv\Scripts\python.exe tools\mobile-smoke.py --workflow pose --image output\mobile-quick-smoke.png
```

## 連線方式與未來正式部署

本次使用[Cloudflare Quick Tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)，每次重開會變更網址，適合私人試用且沒有可用性保證。固定網址需設定自己的Cloudflare帳號、網域與named tunnel。服務採短輪詢取得進度，符合Quick Tunnel不支援SSE的限制。

生成流程重用[ComfyUI官方API模式](https://github.com/Comfy-Org/ComfyUI/blob/master/script_examples/websockets_api_example.py)與已安裝的Qwen工作流，沒有將未授權上游程式碼提交至本repo。
