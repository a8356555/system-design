# Dropbox
> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/dropbox ｜ 難度 easy ｜ 類別：Handling Large Blobs（作者 Evan King）

## 一句話核心
Dropbox = 「control plane（metadata + presigned URL）」與「data plane（檔案 bytes 直接走 S3/CDN）」分離。真正的重點是 50GB 大檔：client 端 chunking + multipart upload + fingerprint 實現進度顯示、斷點續傳、平行上傳與 delta sync。

## 需求（Functional / Non-functional / 規模數字）
**Functional（Core）**
- 任何裝置上傳檔案
- 任何裝置下載檔案
- 分享檔案給其他使用者，並能看到被分享給自己的檔案
- 跨裝置自動 sync

**Below the line**：編輯檔案、不下載直接預覽。（Blob Storage 本身的設計是另一題，不在範圍。）

**Non-functional（Core）**
- 高可用（availability > consistency）
- 支援最大 50GB 檔案
- 安全可靠，檔案遺失或損毀可恢復
- 上傳/下載/sync 盡可能快（低延遲）

**Below the line**：每人儲存上限、版本控管、病毒/惡意軟體掃描。

CAP 提醒：只有「每次讀都必須看到最新寫入」才選 consistency（例：股票交易）。檔案儲存德國使用者上傳後美國使用者幾秒後才看到是可接受的，所以選 availability。

## Core Entities & API
**Entities**：File（raw bytes）、FileMetadata（name、size、mimeType、uploadedBy…）、User。

**API**（使用者資訊走 header 的 session token / JWT，不放 request body，避免被竄改）
```
POST /files                      { File, FileMetadata }              (初版，後續演進)
GET  /files/{fileId} -> File & FileMetadata
POST /files/{fileId}/share       { User[] }
GET  /files/changes?since={timestamp} -> ChangeEvent[]   (fileId、變更類型 created/updated/deleted、新 metadata)
```
演進後：
```
POST /files/presigned-url -> PresignedUrl   { FileMetadata }     # 上傳
GET  /files/{fileId}/presigned-url -> PresignedUrl               # 下載
PATCH /files/{fileId}/chunks  { chunks:[{id,status}] }            # 回報 chunk 狀態
```

## High-Level Design（元件與資料流）
```
Client(Uploader/Downloader, sync agent)
   |  1.request presigned URL     +------------------+
   +----------------------------> | LB + API Gateway | -> File Service -> File Metadata DB (DynamoDB / Postgres)
   |                              +------------------+            (+ SharedFiles table)
   |  2.PUT bytes directly                                 ^
   +--------------------------------> S3  --notification---+ (status: uploading -> uploaded)
   |  3.GET via signed URL
   +--------------------------------> CDN (CloudFront) -> S3 (cache miss)
```
**元件**
- File Service：只管 metadata 讀寫與用 S3 SDK 產生 presigned URL（純本地簽章運算，不呼叫 S3）；不經手檔案內容，是 control plane。
- Metadata DB：原文選 DynamoDB（鬆散結構、少 relation、主要依 user 查詢），但 Postgres 一樣可行，不必糾結。範例 doc：`{id,name,size,mimeType,uploadedBy}`。
- S3：存實際檔案。CDN：下載時 File Service 簽發 CDN signed URL，miss 時回源 S3。
- LB & API Gateway：SSL termination、rate limit、request 驗證、路由。

**上傳演進**
- 爛：上傳到單一 File Service server 的本地檔案系統（無法擴展、server 掛了就失去檔案）。
- 好：存 Blob Storage（S3/GCS），無限擴展且可靠；但檔案要傳兩次（client -> backend -> S3），且 metadata 與檔案可能不一致（需處理一邊成功另一邊失敗）。
- 最佳：presigned URL 直傳 S3。三步：(1) 向 backend 要 presigned URL，並存 metadata status = "uploading"；(2) client PUT 到 presigned URL；(3) S3 Notification 通知 backend，更新 status = "uploaded"。

**下載演進**
- 爛：S3 -> backend -> client（傳兩次，又慢又貴）。
- 好：presigned download URL 直接從 S3 下載（有時效）；缺點是 S3 在單一 region，遠端使用者慢。
- 最佳：CDN 快取在離使用者近的邊緣，使用時效 signed URL。CDN 貴，要用 cache-control header 與 invalidation 策略性地只快取熱門檔案。

**分享演進**
- 爛：metadata 內放 sharelist；列出「分享給我的檔案」要掃描每個檔案的 sharelist。
- 好：額外加反向 mapping 快取（`user1:[fileId1,fileId2]`），但需與 sharelist 同步，最好同 DB 以 transaction 一起更新。
- 最佳：獨立 SharedFiles 表（userId = partition key，fileId = sort key，composite PK），完全正規化，不需維護兩份資料同步；代價是查詢走索引而非單純 key-value lookup，稍慢但值得。

**Sync（兩個方向）**
- Local -> Remote：client sync agent 用 OS 檔案系統事件（Windows FileSystemWatcher / macOS FSEvents）監控本機資料夾，偵測變更後排入上傳佇列，經上傳 API 送出新檔案與 metadata。衝突以 last write wins 處理。remote 為 source of truth。版本管理不在範圍，但實務上不會覆寫唯一檔案，而是新增檔案（或 chunk）並更新 version 指標。
- Remote -> Local：Polling（簡單但偵測慢、浪費頻寬）vs WebSocket/SSE（即時但較複雜）。採混合：每個裝置/session 一條連線（不是每檔一條）做 active 推播，再加上定期（例如每幾分鐘）`GET /files/changes?since=` polling 作為安全網，確保連線中斷漏訊息時最終一致。

## Deep Dives

### 1) 如何支援大檔案（50GB）？（本題重點）
UX 兩大洞察：進度顯示、可暫停/續傳。

單一 POST 上傳的限制：
- Timeout：50GB * 8 bits / 100Mbps = 4000 秒 ≈ 1.11 小時，期間無回應。
- 瀏覽器/伺服器 payload 限制：Amazon API Gateway 硬限制只有 10MB，無法提高。
- 網路中斷要從頭開始；使用者看不到進度。

解法：**client 端 chunking**，切成 5-10MB 小塊，可循序或平行上傳。常見錯誤是在 server 端切塊，這樣仍需先整份上傳，失去意義。有了 chunk 就能顯示進度條。

續傳需記錄各 chunk 狀態，把 `chunks` 欄位（id + status：uploaded / uploading / not-uploaded）放進 FileMetadata。如何保持同步：

- **好解：client PATCH 回報**：client 傳完 chunk 到 S3 後，PATCH `/files/{fileId}/chunks`。缺點：信任 client，惡意使用者可把全部標為 uploaded（只會損壞自己的檔案，但造成難以除錯的不一致狀態）。
- **最佳：server-side chunk verification（trust but verify）**：S3 event notification 不會為 multipart 的單一 part 觸發，只在整個物件完成時觸發。所以讓 client 在 PATCH 時附上每個 chunk 的 ETag，backend 用 S3 `ListParts` API 驗證後才更新 chunks，並在全部驗證完才標記整體 "uploaded"。

**Fingerprint**：不能用檔名識別（不同使用者可同名），要用內容雜湊（如 SHA-256）。整檔 fingerprint 用於去重與判斷是否可續傳；每個 chunk 也算 fingerprint 以精確判斷哪些已傳。fileId 應為 UUID，fingerprint 是獨立欄位（兩個使用者傳同樣內容會有相同 fingerprint）。

完整上傳流程：
1. client 切 5-10MB 並算每塊與整檔 fingerprint
2. 查詢該 fingerprint 是否已存在；若 status = uploading，取回 chunk 狀態續傳
3. 否則 POST 啟動 multipart upload：backend 呼叫 S3 `CreateMultipartUpload` 取得 uploadId，為每個 part 產生 presigned URL，metadata 存 "uploading"，回傳 uploadId 與各 chunk URL
4. client 逐塊 PUT，每塊後 PATCH 狀態與 ETag；backend 用 `ListParts` 驗證後更新
5. 全部 uploaded 後 backend 呼叫 `CompleteMultipartUpload`（part numbers + ETags）組裝；S3 確認成功才把 metadata 設為 "uploaded"

說明：這就是 S3 Multipart Upload，實務上直接用；但面試不能只說「用 S3 multipart API」，要能講解其運作與自己如何實作。

下載不需要 chunk：Complete 之後就是單一物件，用一個 presigned/CDN URL 下載；超大檔可用 HTTP Range requests 平行下載或續傳，client 不需知道原本 chunk 邊界。

### 2) 如何讓上傳、下載、sync 盡可能快？
- 下載：CDN。
- 上傳：chunk 平行傳輸，並依網路狀況調整 chunk 大小（頻寬固定，但可把頻寬用滿）。
- Sync：只同步改變的 chunk（delta sync）。細節：固定大小 chunk 在檔案開頭插入 1 byte 會讓之後所有 chunk 邊界位移、fingerprint 全變，delta sync 幾乎無效。解法 **Content-Defined Chunking (CDC)**：用 rolling hash（如 Rabin fingerprinting）依內容決定邊界，小修改只影響附近 chunk。這是 Dropbox 實務上達成高效 delta sync 的方式。
- **壓縮**：因為直傳 S3，壓縮完全在 client 完成，S3 存壓縮後資料，下載後 client 解壓。是否壓縮要看檔案型別（圖片/影片壓縮比低不值得；文字檔值得，例如 5GB 文字檔可壓到 1GB 或更少）、大小與網路條件，由 client 決策。演算法：Gzip（最普及）、Brotli（比 Gzip 好，特別是文字，現代瀏覽器皆支援）、Zstandard（速度與壓縮比平衡佳，client 端壓縮的好選擇）。若需加密，**先壓縮再加密**，因為加密產生隨機性使資料難以壓縮。

### 3) 如何確保檔案安全？
- 傳輸加密：HTTPS。
- 靜態加密：S3 server-side encryption（每個檔案獨立 key，key 與檔案分開存放）。
- Access Control：sharelist / SharedFiles 表即 ACL，只對授權使用者發下載連結。
- 連結外流問題：授權使用者可能把連結貼到公開論壇 -> 使用短時效 signed URL（例如 5 分鐘）。注意 signed URL 是 bearer token，持有未過期連結者皆可下載；短時效降低風險但不能完全杜絕，高安全需求可加 IP binding 或搭配認證 cookie。
- CloudFront signed URL：server 以 private key 簽發（含路徑、過期時間、可選限制如 IP）；CDN 用已註冊的 public key 驗證簽章與過期時間，通過才回內容。

## 關鍵數字與 back-of-envelope
- 50GB 檔案、100Mbps：4000 秒 ≈ 1.11 小時。
- Chunk 大小 5-10MB。
- Amazon API Gateway payload 限制 10MB。
- Signed URL 有效期範例 5 分鐘。
- 5GB 文字檔可能壓到 1GB 以下。
- 原文沒有 user 數/QPS/總儲存量的估算。

## 面試官期待（Mid / Senior / Staff）
- **Mid（E4）**：80/20。API 與 data model 清楚，HLD 涵蓋上傳/下載/分享。不期待知道 presigned URL 或 chunking，但被追問「檔案傳了兩次怎麼辦」「如何顯示進度又能續傳」時能經由討論推導出來。
- **Senior（E5）**：60/40。快速帶過 HLD，把時間花在大檔上傳，主動比較多種方案；熟悉 blob storage、CDN，最好有 multipart upload 實戰經驗。
- **Staff+**：40/60。每個主題深入，甚至主導話題方向；對各方案取捨清楚並以 peer 方式與面試官對談。

## 可遷移的 pattern
1. **Control plane / data plane 分離 + presigned URL 直傳直下**：大檔不經 app server，適用影片、圖片、附件上傳、備份。
2. **Client-side chunking + resumable（multipart）+ 狀態表**：進度、續傳、平行；適用任何大型傳輸。
3. **Trust but verify**：client 回報進度可用於 UX，但完成與正確性由 server 側驗證（ETag/ListParts）。
4. **Push + poll 混合同步**：WebSocket/SSE 做即時，`since=timestamp` polling 做兜底保證最終一致；適用 chat、協作、通知。
5. **關聯用獨立正規化表（SharedFiles）取代內嵌 list**：避免掃描與雙寫同步；內容雜湊 fingerprint 做去重與識別；CDC rolling hash 做 delta。

## 常見追問
1. **為何不在 server 端 chunk？** 還是得先整份上傳到 server，失去 chunking 對 timeout/續傳的好處；必須 client 端切。
2. **S3 event 能追蹤每個 part 嗎？** 不能，只在整個 multipart 完成時觸發；追蹤 part 需用 ListParts + ETag。
3. **為何用 fingerprint 而非檔名？** 檔名可重複；內容雜湊能去重並判斷是否可續傳同一份檔案。
4. **固定大小 chunk 的 delta sync 問題？** 插入一個 byte 使後續邊界全變；用 content-defined chunking（rolling hash）。
5. **下載連結被轉貼給未授權者怎麼辦？** 短時效 signed URL（bearer token，無法完全防止），高安全加 IP binding 或 cookie。
6. **衝突如何處理？** 原文採 last write wins；版本管理屬範圍外，實務上新增版本而非覆寫。
