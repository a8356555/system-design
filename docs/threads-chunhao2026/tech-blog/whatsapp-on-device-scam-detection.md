# How We're Building Scam Alert on WhatsApp With End-to-End Encryption and Verifiability Guarantees
> 原文：https://engineering.fb.com/2026/08/12/security/how-were-building-scam-alert-whatsapp/ ｜ Meta Engineering（WhatsApp）/ 2026-08-12（Ronald Anthony、Shafin Anwarsha 等） ｜ Threads 解讀：https://www.threads.com/@chunhao2026/post/DctJ9xSj692（2026-08-31）

## 一句話重點
把 ML 推論整個搬到裝置端、遙測只送加噪的聚合統計並在 TEE 中處理、模型公開可驗證，讓「偵測詐騙」與「端對端加密」同時成立。

## 作者的解讀（貼文重點）
- 「E2EE」與「偵測詐騙訊息」看似矛盾，WhatsApp 的做法是把 ML 推論完全搬到用戶裝置。作者列出五層設計，抓到的貼文只含前三層：
  1. On-device inference：模型下載到本機執行，訊息內容不離開裝置，server 看不到明文。
  2. Differential privacy：連「警告觸發幾次」這種聚合數字，離開裝置前也加校準過的隨機雜訊，數學上無法由聚合反推個別行為。
  3. TEE：聚合遙測在硬體隔離環境處理，連 Meta 工程師也看不到原始資料，OS 也無法干預。
- 第 4、5 層未見於取得的貼文文字；注意作者的「五層」分法與原文的五層分法不同，原文如下。

## 原文重點
### 背景 / 問題
- 詐騙手法不斷演進（冒充、社交工程、AI 生成誘餌）；要保護用戶，同時維持 E2EE 並防止未授權的資料分享。
- 原則：只在裝置端處理；沒有用戶明確動作不自動回報；功能為用戶可控、可選。

### 架構（原文五層）
1. **On-device ML inference**：小型輕量模型在本機，對「非聯絡人」的來訊依對話結構與語言訊號做機率式分類。
2. **Privacy-preserving analytics**：只收最少遙測（警告次數、用戶動作次數），在 confidential computing（TEE）與 differential privacy 中處理，不傳原始資料。
3. **Confidential federated analytics pipeline**：
   - 資料最小化，寫死的 privacy guardrail 限制範圍與生命週期；
   - 裝置端先彙整成計數；
   - Remote attestation：client 驗證 TEE 程式碼與公開 transparency ledger 一致；
   - TEE 內 secure aggregation，只釋出加噪聚合；
   - 進行中的聚合以僅 TEE 持有的 key 加密做 checkpoint；
   - OHTTP relay 去除 client IP，避免針對特定用戶；
   - Anonymous credentials：驗證 client 合法但不識別身分；
   - Differential privacy：增減任一人的資料影響可忽略。
4. **Model distribution 與 non-targetability**：每個模型版本在部署前發布到第三方 append-only transparency ledger（Cloudflare）；經 OHTTP + anonymous credentials 匿名下載；client 以 SHA-256 manifest 對照 ledger 驗證；實驗分組在 client 端決定，防止 server 針對特定用戶派發模型；所有（含實驗）模型皆公開記錄。
5. **Transparency 與驗證**：公布模型權重供研究者獨立分析；App 內透明紀錄（Account > Request Info > Scam Alert Activity）顯示被標記訊息、分析結果、模型版本；bug bounty 涵蓋隱私架構與模型完整性。

### 取捨
- 只限非聯絡人訊息，沒有 server 端上下文 → 偵測能力受限。
- 只有聚合計數可用 → 難做細緻分析與模型迭代。
- 公開 ledger 與模型增加驗證負擔，所有部署公開可查。
- 用戶需自行處理警告（信任/封鎖），誤判需人工處理。

### 結果 / 狀態
- 截至 2026-08 為 limited beta，尚未正式上線；將擴大 bug bounty 並發布白皮書；基礎為 PAPAYA Federated Analytics Stack（USENIX NSDI 2025）。
- 原文未提供 precision / recall / 誤報率等量化數據。

## 面試怎麼用
- **E2EE 訊息系統題**（WhatsApp / Signal）：被問「如何做 abuse/spam 偵測而不破壞 E2EE」→ client-side classification，server 只拿聚合訊號。
- **Privacy-preserving telemetry**：device 預聚合 + differential privacy + TEE secure aggregation + OHTTP 去 IP，分層說明各自防什麼。
- **信任模型**：讓使用者不必信任營運方——remote attestation、transparency ledger、non-targetability，可用於任何「不能信 server」的設計題。
- **On-device ML 取捨**：模型小、更新靠分發、缺上下文；需說明如何評估成效（只有加噪聚合）。
- 注意誠實標示：此為 beta，無量化成效。

## 相關筆記
- [WhatsApp breakdown](../../hellointerview-breakdowns/whatsapp.md)
- [Notification System](../../hellointerview-breakdowns/notification-system.md)
