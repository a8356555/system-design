# Handling Large Blobs
> 🤖 **by agents**：原文為 Premium，僅公開介紹與章節大綱；除標「（原文）」的段落外，內容皆由 agents 依大綱撰寫／搜尋整理，非 Hello Interview 原文。
> 來源：https://www.hellointerview.com/learn/system-design/patterns/large-blobs ｜ 分類：patterns

## 一句話重點
大檔案不要經過 application server：用 presigned URL 讓 client 直傳 blob storage（S3）、經 CDN 下載；大檔用 multipart／resumable upload，並處理「blob 與 DB metadata 不同步」的狀態問題。

## 原文大綱（原文）
- 介紹（原文）：Large files like videos, images, and documents need special handling in distributed systems. Instead of shoving gigabytes through your servers, this pattern uses presigned URLs to let clients upload directly to blob storage and download from CDNs. You also get resumable uploads, parallel transfers, and progress tracking.
- The Problem（原文重點）：大檔案屬於 blob storage（如 S3）而非 DB；原文經驗法則：超過 10MB 且不需 SQL 查詢，應放 blob storage。S3 提供近乎無限容量與 11 個 9 的 durability。但標準做法讓 bytes 經過 application server（client → API server → blob storage），檔案一大就崩潰（圖：Server as a Proxy）。
- The Solution：Simple Direct Upload / Simple Direct Download / Resumable Uploads for Large Files / State Synchronization Challenges / Cloud Provider Terminology
- When to Use in Interviews：Common interview scenarios / When NOT to use it
- Common Deep Dives：「What if the upload fails at 99%?」「How do you prevent abuse?」「How do you handle metadata?」「How do you ensure downloads are fast?」
- Conclusion

## 內容（by agents）
### The Problem：伺服器當 proxy 的代價
- 2GB 上傳佔用 API server 的 connection、記憶體／頻寬，且上傳一次、轉傳一次，頻寬成本與延遲加倍。
- LB／API gateway 常有 body size 與 timeout 限制（例如 API Gateway 10MB payload 上限）。
- 擴縮 API 層變成擴頻寬而非擴運算，成本不對稱。

### Simple Direct Upload
1. Client 向 API 要上傳權限（帶 filename、size、content-type）。
2. API 驗證身分／配額，產生 **presigned URL**（短 TTL、綁定 key 與 content-type／size 上限）並在 DB 寫一筆 `status=pending` 的 metadata。
3. Client 以 HTTP PUT 直傳 S3。
4. S3 觸發事件（S3 Event → SQS/Lambda）通知後端，將 metadata 標為 `uploaded`，再觸發後處理（轉碼、縮圖、病毒掃描）。
取捨：多一次 round trip，換來 API 層零 bytes 流量。

### Simple Direct Download
- 公開／低敏感內容：blob 前面放 CDN，client 直接抓 CDN URL。
- 私有內容：API 授權後回傳短效 presigned GET URL 或 CDN signed URL／signed cookie。
- 以 `Content-Disposition`、Range request 支援下載與影片 seek。

### Resumable Uploads for Large Files
- **Multipart upload**（S3：每 part 5MB–5GB，最多 10,000 parts）：切 chunk、並行上傳、單 part 失敗只重傳該 part，最後 `CompleteMultipartUpload`。
- 每個 part 一個 presigned URL（或用 tus 協定／GCS resumable session URI）。
- Client 端以 checksum（ETag／MD5／SHA-256）驗證；進度條由已完成 part 數計算。
- 查詢進度：`ListParts`，斷線後 client 問「已經收到哪些」再續傳。
- 清理：設 lifecycle rule 自動 abort 未完成的 multipart，避免孤兒 part 持續計費。

### State Synchronization Challenges
blob 與 DB metadata 是兩個系統，無法單一交易：
- 上傳成功但 metadata 未更新（client 沒回報）→ 以 S3 event 為準（server-side 通知，不信任 client 回報）。
- Metadata 已建但從未上傳 → 定期 reconcile job 清除過期 `pending`。
- 刪除：先標記 soft-delete，再非同步刪 blob，避免 dangling reference。
- 原則：以 blob storage 事件為事實來源 + 冪等處理 + 對帳（reconciliation）。

### Cloud Provider Terminology
| 概念 | AWS | GCP | Azure |
|---|---|---|---|
| Blob store | S3 | Cloud Storage (GCS) | Blob Storage |
| 預簽 URL | Presigned URL | Signed URL | SAS token |
| 大檔上傳 | Multipart upload | Resumable upload | Block blob / Put Block |
| CDN | CloudFront | Cloud CDN | Azure CDN / Front Door |

## 常見深入題（by agents）
- **上傳到 99% 失敗？** 用 multipart/resumable，只重傳失敗 part；client 重連時 ListParts 取得進度；part 級 retry + 指數退避。
- **如何防濫用？** presigned URL 短 TTL、限制 content-length-range 與 content-type、每用戶配額與 rate limit、上傳後病毒／內容掃描再標為可用、CDN signed URL 防盜連。
- **Metadata 怎麼處理？** 放 DB（Postgres/DynamoDB）：owner、size、hash、status、storage key；blob key 用 UUID／content hash，不用使用者檔名；用 content hash 做去重。
- **下載如何快？** CDN 快取、Range request、分段並行下載、就近 region、影片用 HLS/DASH 切片自適應（見 youtube）。

## 面試怎麼用（by agents）
- 看到 Dropbox／YouTube／Instagram／附件／影像處理，第一時間說「bytes 不經過我的 server，用 presigned URL」。
- 不要用於：只有 KB 級資料、資料需要 SQL 查詢／交易、或題目重點不在檔案傳輸時（一句話帶過即可）。
- 主動提 metadata 與 blob 的一致性（pending/uploaded + 事件 + 對帳），這是區分資深答案的細節。

## 相關題目
- [dropbox](../../hellointerview-breakdowns/dropbox.md)
- [youtube](../../hellointerview-breakdowns/youtube.md)
- [instagram](../../hellointerview-breakdowns/instagram.md)

## 自測問題（by agents）
1. 為什麼不讓 API server proxy 檔案？答：浪費頻寬與連線、受 timeout／body 限制、擴縮成本高。
2. presigned URL 如何限制濫用？答：短 TTL、綁 key／content-type／大小上限、授權後才簽發。
3. 如何確認上傳完成？答：以 S3 event 通知後端，而非信任 client 回報。
4. 10GB 檔案如何可靠上傳？答：multipart 並行、per-part retry、ListParts 續傳、lifecycle 清理孤兒 part。
5. 孤兒 pending metadata 怎麼處理？答：定期 reconcile，過期未上傳者刪除。

## 參考來源
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/PresignedUrlUploadObject.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html （multipart upload）
- https://cloud.google.com/storage/docs/resumable-uploads
- https://tus.io/protocols/resumable-upload
- 註：以上為 agents 憑既有知識列出的公開文件；2026-10-19 已逐一確認連結可開啟（HTTP 200），但內容未逐條比對。
