# YouTube
> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/youtube ｜ 難度：Medium ｜ 類別：Handling Large Blobs、Scaling Reads

## 一句話核心
上傳走 presigned URL + multipart 直傳 S3（可續傳），上傳後用 DAG pipeline 把影片切 segment、轉多種 format、產生 manifest；播放用 Adaptive Bitrate Streaming（client 依網路狀況逐段切換畫質），再用 CDN + metadata cache 撐讀取量。

## 需求
**Functional（Core）**
- 使用者可上傳影片
- 使用者可觀看（stream）影片

Out of scope：影片資訊（view count）、搜尋、留言、推薦、頻道管理、訂閱。

**Non-functional（Core）**
- 高可用（availability > consistency）
- 支援上傳與串流大影片（數十 GB）
- 低延遲串流，即使在低頻寬環境
- 規模：~1M 影片上傳/天、100M 影片觀看/天
- 支援 resumable upload

Out of scope：惡意內容防護、bot / 假帳號防護、monitoring / alerting。

原文強調：功能需求很少，所以非功能需求更重要，它們定義了「上傳」「觀看」這兩個看似簡單的互動的複雜度。

## Core Entities & API
Entities：User（上傳者/觀看者）、Video、VideoMetadata（上傳者、transcript URL 等）。

初版 API（之後會演進）：
```
POST /upload   { Video, VideoMetadata }
GET  /videos/{videoId} -> Video & VideoMetadata
```
演進後：
- 因為直傳 S3，`POST /upload` 改成 `POST /presigned_url`（payload 只有 metadata，不含影片檔）。
- `GET /videos/{id}` 只回 VideoMetadata，裡面含觀看所需的 URL（manifest）。
- 續傳進度更新：`PATCH /videos/{id}/chunks`。

## High-Level Design
```
Uploader --POST /presigned_url--> Video Service --> Video Metadata DB (Cassandra)
Uploader --multipart upload (presigned URL)--> S3 (原檔)
S3 --event notification--> Video Processing Service (DAG, workers)
   --> S3 (segments × formats + manifest files) ; update metadata
Viewer --GET /videos/{id}--> Video Service (metadata, manifest URL)
Viewer --manifest + segments--> CDN --> S3
```

### 背景知識：Video Streaming
- **Codec**：壓縮/解壓縮影片（H.264、H.265/HEVC、VP9、AV1、MPEG-2、MPEG-4）。取捨：壓縮耗時、平台支援度、壓縮效率、壓縮品質（lossy 與否）。
- **Container**：檔案格式，存影片/音訊與 metadata（如 transcript）；與 codec 不同（codec 管怎麼壓，container 管怎麼存）。各裝置/OS 支援不同。
- **Bitrate**：單位時間傳輸 bit 數（kbps / Mbps）；高解析度、高 FPS 位元率高。
- **Manifest files**：文字檔描述 stream。**Primary manifest** 列出所有版本（格式），指向各 **media manifest**；每個版本被切成數秒的 segment，media manifest 列出 segment 連結，是 player 的「索引」。
- 文中的「video format」= container + codec 的組合。

### 1) 上傳
- **Metadata 儲存**：~1M 影片/天 → 一年 ~365M 筆，選可水平分片的 **Cassandra**（高可用、可選 partition key）。以 videoId 為 partition key，因為只做單筆點查，不需批次存取。
- 補充論點（原文）：有些系統需要精細分區（讀取落在少數節點）、有些需要 scoped domain 內的一致性（如 Ticketmaster 以 concert ID shard 關聯式 DB）、有些根本不需精細分區（本題以 videoId 點查即可）。
- **影片資料**：直傳 S3，用 presigned URL + multipart upload（與 Dropbox 題重疊）。

**儲存什麼？**
- **爛解：只存原始影片**。不同裝置需要不同格式，不可行。
- **好解：存多種格式**。S3 觸發事件通知 video processing service，轉出多種格式存回 S3 並更新 metadata URL。缺點：無法只下載「一部分」影片，而這對串流很關鍵。
- **最佳解：切 segment 再轉多種格式**。每個 segment 是數秒的可播放單元，再各自轉成不同格式。缺點：post-processing 變成 pipeline，且要妥善保存 segment 參考並供串流流程使用。

### 2) 觀看
- **爛解：整檔下載後播放**。10GB 影片在 100 Mbps 下要 13+ 分鐘；單一 HTTP 請求中斷則進度全失。
- **好解：增量下載 segment**。client 依裝置、頻寬、偏好選格式（如 HD → 1080p），載入第一個數秒 segment 即可開始播放，背景持續預載。缺點：複雜；且沒處理播放中網路變化（1080p 在網路變差時會 buffer）。
  - 原文澄清：這和單純「chunked download」不同——有些格式依序 chunk 不一定可播，切成可播放 segment 才明確。
- **最佳解：Adaptive Bitrate Streaming (ABR)**。依賴 segment + 多格式 + 上傳時產生的 manifest。流程：
  1. 取 VideoMetadata（含 manifest URL）
  2. 下載 manifest
  3. 依網路/設定選格式，從 manifest 取該 segment URL，下載第一段
  4. 播放並持續下載後續 segment
  5. 偵測網路變慢/變快就切換 segment 格式（變差時改抓壓縮率高、解析度低的）
  - 代價：最複雜，client 要更主動參與，且依賴上游的切段、多格式、manifest。

## Deep Dives

### 1) 如何處理影片後製以支援 ABR？
Pipeline 輸出：
- 各格式（codec + container）的 segment 檔，存 S3
- manifest（primary + 多個 media manifest），存 S3，media manifest 引用 S3 的 segment

步驟：
1. 用 ffmpeg 類工具把原檔切成 segment
2. 對每個 segment 轉碼（transcode），並處理音訊、transcript 生成等
3. 建立 manifest 引用各格式 segment
4. 標記上傳完成

重點：
- 這是一個 **DAG**（有 fan-out / fan-in，單向依賴）；segment 間無依賴，轉碼/音訊/轉錄可在不同 worker **平行**執行。
- 最貴的是 **segment transcoding**（CPU-bound），應最大化平行度。
- 用 orchestrator（如 **Temporal**，支援 media-processing workflow）建圖與分派 worker。
- 暫存資料（segment、audio）放 S3，worker 間傳 URL 不傳檔案。
- 不必畫出完整 DAG 細節，重點講清楚 input/output 與如何可擴展地處理。
- 優化：此設計假設整檔傳完才處理；可讓 client 切段上傳，邊傳邊處理（pipeline）。

### 2) 如何支援 resumable upload？
與 Dropbox 大檔上傳同構（實務上由 AWS multipart upload 處理，但面試要講清楚細節）：
- Client 將檔案切 chunk（~5-10MB），每個有 fingerprint hash。
- VideoMetadata 有 `chunks` 欄位（每個含 fingerprint 與 status）。
- Client 先 POST 更新 metadata，所有 chunk 為 `NotUploaded`。
- Client 逐 chunk 傳 S3；S3 回 part number 與 ETag；client 轉給後端（`PATCH /videos/{id}/chunks`），server 透過 S3 API 驗證 fingerprint/ETag 後將該 chunk 標為 `Uploaded`。
- Client 呼叫 CompleteMultipartUpload 後，S3 發出一次性的 object-level 通知（`ObjectCreated:CompleteMultipartUpload`），觸發下游處理；chunk 進度仍由 client 驅動。
- 中斷後 client 重新取 VideoMetadata，跳過已上傳 chunk。

### 3) 如何擴展到大量上傳/觀看？
逐元件分析：
- **Video Service**：stateless，水平擴展 + load balancer。
- **Video Metadata（Cassandra）**：leaderless replication + consistent hashing，依 videoId 均勻分布；風險是熱門影片所在節點變 **hot**。
- **Video Processing Service**：內部有 queue 吸收突發上傳，queue 長度可作為彈性擴展 worker 的觸發條件。
- **S3**：擴展性極佳，但 bucket 在單一 region（region 內自動跨 AZ 複製），跨 region 副本或外部 CDN 才能 geo 分散；遠端使用者初始載入慢或 buffer。

改善：
- **Hot video**：Cassandra 調整成複製到多個節點分擔查詢；加上分散式 **cache**（LRU、依 videoId 分區）存熱門 metadata。
- **遠距離串流**：**CDN** 快取熱門影片檔（segment + manifest），邊緣伺服器靠近使用者；若 manifest 與 segment 都在 CDN，串流過程完全不需碰 backend。

### 額外可談的 deep dive（原文列舉）
- **加速上傳**：client 切段上傳 + 後端立即處理（pipeline）；缺點是 client 要參與處理、未完成上傳可能留下「垃圾」segment。
- **接續上次觀看位置**：每個 user 每支影片多存資料。
- **View count**：精確 vs 估算，可獨立成一個 deep dive。

## 關鍵數字與 back-of-envelope
- 上傳 ~1M 影片/天 → ~365M metadata 筆/年
- 觀看 100M 影片/天
- 10GB 影片在 100 Mbps 下載 13+ 分鐘
- Chunk 大小 ~5-10MB
- Segment 長度：數秒
- 影片大小：數十 GB
（原文沒有給儲存總量與頻寬的估算，面試時可自行補算。）

## 面試官期待
- **Mid（80% breadth / 20% depth）**：清楚定義 API 與資料模型，做出功能完整的上傳/播放 HLD；不要求深入串流知識，但應收斂到 multipart upload 與 segment-based streaming，理解需直接與 S3 互動；能對一個 deep dive 主題釐清。
- **Senior（60/40）**：快速走完 HLD，把時間花在後製與上傳細節；知道 multipart upload 如何做 resumable；知道如何有效後製出支援 ABR 的檔案；能清楚闡述取捨。
- **Staff+（40/60）**：深入上述各複雜場景，甚至主導話題到自己擅長的方向；能把面試官當 peer 清楚說明各方案取捨；用實務經驗佐證技術選擇。

## 可遷移的 pattern
1. **Handling Large Blobs**：大檔繞過 app server，presigned URL 直傳物件儲存 + multipart / chunk fingerprint 實現續傳；套用於 Dropbox、Instagram、備份服務。
2. **Object-store event → 非同步 pipeline**：上傳完成事件觸發後製，用 queue 吸收突發、queue 長度驅動 autoscale。
3. **DAG + orchestrator（Temporal）**：可平行的 CPU-bound 工作拆成 fan-out/fan-in 圖，worker 間用 S3 URL 傳遞資料。
4. **Scaling Reads 階梯**：metadata cache（LRU）+ DB replication 應對 hot key，內容走 CDN，把串流所需檔案全放 CDN 讓 backend 不在串流熱路徑。
5. **Client 主動參與（manifest / ABR）**：把「選哪個版本」的決策推給 client，server 只提供索引與靜態檔。

## 常見追問
- **為什麼 metadata 用 Cassandra、partition key 為何選 videoId？** 365M+ 筆需水平分片，只做單筆點查，不需批次存取，高可用優先。熱門影片可能造成 hot partition，用多節點複製與 cache 緩解。
- **為什麼要切 segment 而不是整檔下載？** 可快速起播、中斷不丟進度、並是 ABR 的基礎。
- **ABR 如何運作？** Client 讀 manifest，依當下網路選格式下載 segment，網路變差就切低 bitrate segment。
- **上傳到一半斷線怎麼辦？** Chunk 級進度記在 VideoMetadata，重連後跳過已 Uploaded 的 chunk，由 S3 multipart 完成。
- **如何加速上傳到可播放的時間？** Client 切段上傳，後端立即平行處理，代價是 client 複雜度與垃圾 segment。
