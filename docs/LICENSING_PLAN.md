# 千迷AI卡密系統與產品授權殼計畫

## 目標

為千迷AI增加正式產品授權機制：未啟用時只顯示卡密啟用畫面；有效卡密才能使用圖片生成與修改；管理員可以發碼、續期、停用及解除裝置；同時保留有限時間的離線使用能力。模型、提示詞、作品與現有功能不受影響。

## 建議架構

```text
千迷AI Tauri 桌面程式
        │ HTTPS
        ▼
Cloudflare Worker 授權 API
        │
        ▼
Cloudflare D1 授權資料庫
        │
        ├─ 卡密
        ├─ 啟用裝置
        ├─ 簽章租約
        └─ 操作紀錄

獨立管理後台
        │
        └─ 發碼／停用／續期／解綁
```

授權檢查必須設在 Rust 核心層，不能只在前端隱藏畫面。即使有人直接呼叫 `generate_images`，沒有有效授權仍要被拒絕。

## 預設授權規則

- 一張卡密允許一台電腦。
- 使用期限從第一次啟用開始計算。
- 支援永久、月卡、季卡、年卡及自訂天數。
- 網路中斷時可繼續使用 72 小時。
- 管理員可解除裝置綁定。
- 被停用或撤銷後，下次連線立即失效。
- 卡密不以明文保存，資料庫只保存前綴、末四碼及 HMAC。
- 完整卡密只在建立時顯示一次。
- 每次發出的授權租約均使用 Ed25519 私鑰簽章。

## 桌面程式改造

### 啟動畫面

新增響應式全頁授權殼，支援目前最小視窗 `360×420`：

- 千迷AI品牌與版本。
- 卡密輸入、貼上及顯示切換。
- 「啟用這台電腦」主要操作。
- 網路錯誤、卡密無效、過期、停用與裝置額滿狀態。
- 匿名化裝置識別資訊的使用說明。

### Rust授權核心

新增 `src-tauri/src/licensing.rs`，負責：

- 產生安裝裝置識別。
- 呼叫啟用與驗證 API。
- 驗證 Ed25519 授權簽章。
- 驗證產品、裝置、期限與功能權限。
- 管理離線寬限時間。
- 偵測明顯的系統時間回撥。
- 使用 Windows DPAPI 加密保存本機授權。
- 向前端只回傳去敏後的授權狀態。

### 核心功能閘門

以下功能必須在 Rust 層執行授權檢查：

- `generate_images`
- 啟動本機模型服務
- 快速生成
- Qwen 2.1 T2I
- Qwen 2.1 Edit
- 未來新增的付費功能

視窗控制、版本資訊與輸入卡密等功能維持未啟用時可用。

### 授權與版本介面

啟用後提供：

- 卡密末四碼。
- 授權方案與到期日期。
- 目前裝置與離線期限。
- 授權狀態與重新驗證。
- 解除本機授權。
- 軟體版本與更新狀態。

## 授權API

桌面端 API：

- `POST /v1/licenses/activate`
- `POST /v1/licenses/verify`
- `POST /v1/licenses/deactivate`
- `POST /v1/licenses/refresh`
- `GET /v1/releases/latest`

管理端 API：

- 建立單張或批次卡密。
- 搜尋、續期、停用、恢復及撤銷卡密。
- 查看與解除裝置。
- 查詢操作紀錄。
- 匯出 CSV。

所有 API 必須使用 HTTPS、請求格式驗證、rate limiting、防重放 nonce、原子化裝置席次分配及去敏日誌。管理端必須具備 MFA。

## 資料庫設計

- `products`：產品與版本設定。
- `license_plans`：方案、天數、裝置數與功能權限。
- `licenses`：卡密雜湊、狀態與期限。
- `activations`：裝置綁定。
- `leases`：短效授權租約。
- `releases`：最新版本與最低支援版本。
- `admin_users`：管理員與權限。
- `audit_events`：發碼、續期、停用、撤銷及解綁紀錄。

資料庫不得保存完整卡密、原始 Machine GUID、提示詞或生成圖片。

## 管理後台

管理後台應獨立部署，不包入千迷AI EXE：

- 有效卡密、即將到期與啟用裝置儀表板。
- 單張及批量發卡。
- 永久卡、月卡、季卡、年卡及自訂方案。
- 卡密搜尋、篩選、續期、停用與撤銷。
- 裝置查看及解除綁定。
- 操作紀錄與 CSV 匯出。
- 管理員 MFA 與分級權限。
- 資料庫備份、還原演練及簽章私鑰離線備份。

服務端密鑰與 Ed25519 私鑰只能存放在 Cloudflare Secrets，不得出現在原始碼、GitHub或桌面程式。

## 安全策略

- EXE 只內建驗簽公鑰與產品 ID。
- 授權資料使用 Windows DPAPI Current User 保存。
- 明確停用、過期或裝置移除時不得回退到舊租約。
- 只有逾時、DNS 或伺服器 5xx 才能進入離線寬限。
- 防止透過前端 JavaScript 或直接 IPC 繞過授權。
- 縮小 Tauri Asset Protocol 權限並移除不必要的 `unsafe-inline` CSP。
- 正式版使用 Authenticode 與 Tauri 更新簽章。
- 日誌不得記錄完整卡密、租約、私鑰或原始裝置識別碼。

本機模型仍可被技術使用者直接呼叫，因此卡密主要保護正式程式體驗、更新、售後服務與合理裝置管理，不能視為不可破解的 DRM。若未來需要保護核心推論能力，必須將高價值功能移至受控伺服器。

## 驗證計畫

### 授權測試

- 正確與錯誤卡密。
- 過期、停用及撤銷。
- 裝置數超限及重複啟用。
- 解綁、換機與續期刷新。
- 離線 72 小時及超過期限。
- 系統時間回撥。
- 租約內容或簽章遭竄改。

### 防繞過測試

- 未啟用時直接呼叫 `generate_images` 必須失敗。
- 未啟用時不得啟動本機模型服務。
- 修改前端 HTML 或 JavaScript 後仍無法生成。
- 將本機授權檔複製到另一台電腦時必須驗證失敗。
- 日誌與網路封包不得包含完整卡密、租約或原始裝置識別碼。

### 發行測試

- Rust、JavaScript與Python檢查。
- T2I與Edit端到端測試。
- NSIS／MSI安裝、升級及移除。
- 有效與無效更新簽章。
- `360×420` 與 `1280×820` 介面測試。
- GitHub secrets與大型檔案掃描。

## 實作階段

1. 建立 Cloudflare Worker、D1 schema、migration與Secrets。
2. 完成卡密、裝置席次、租約簽章及稽核API。
3. 建立獨立管理後台與管理員MFA。
4. 在Tauri Rust層完成DPAPI、驗簽、狀態機及功能閘門。
5. 完成啟用殼、授權與版本介面及錯誤狀態。
6. 加入正式更新、安裝包簽章與發行流程。
7. 完成自動化、安全、離線、安裝及回滾測試。
8. 更新文件，建立release，提交並推送原始碼。

## 預計交付內容

- 千迷AI卡密啟用殼。
- Rust授權核心與功能閘門。
- Cloudflare Workers授權API。
- D1資料庫與migration。
- 卡密管理後台。
- DPAPI本機授權儲存。
- Ed25519離線租約驗證。
- 管理員操作紀錄。
- 安裝、部署、備份及客服解綁文件。
- 自動化測試與新版編譯檔。

## 參考資料

- [Cloudflare Workers定價](https://developers.cloudflare.com/workers/platform/pricing/)
- [Cloudflare D1定價](https://developers.cloudflare.com/d1/platform/pricing/)
- [Keygen裝置啟用模型](https://keygen.sh/docs/activating-machines/)
- [Tauri安全模型](https://v2.tauri.app/security/)
- [Windows DPAPI CryptProtectData](https://learn.microsoft.com/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)
