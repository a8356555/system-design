# Notification System
> ⚠️ Premium 文章，原文僅公開需求與大綱；設計細節為整理者補充。

> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/notification-system ｜ 難度：medium ｜ 類別：Multi-step Processes、Scaling Writes ｜ 作者 Evan King

## 一句話核心
（原文）內部平台，替其他團隊透過 push/email/SMS 發訊息；平均流量很低，但 campaign 造成約 50x 的突發尖峰，設計重心是不丟訊息、高優先級不被擠壓、去重。

## 需求（Functional / Non-functional / 規模數字）
**Functional（原文）**
- 上游服務可對用戶透過 push/email/SMS 發通知，立即或排程
- 可發 campaign（同訊息發給整個 segment），立即或排程
- 用戶可設定偏好（channel opt-out、quiet hours）
- Out of scope：模板管理與內容編輯、投遞分析儀表板、App 內通知 feed/badge、跨類型 frequency capping

**Non-functional / 規模（原文）**
- 每日 1000 萬則 -> 平均約 100/s（幾乎沒有）
- 但 campaign 在 9am 發送，1M 在 5 分鐘內 -> 超過 3,000/s（單一 campaign）
- 設計目標：尖峰 5,000 notifications/s，約 50 倍持續速率
- 高優先級通知（如 OTP）要在 5 秒內送達，即使 campaign 進行中（見 deep dive 2）

## Core Entities & API
（原文僅標題；補充，非原文）
- Entities：Notification(id, user_id, channel, priority, payload, send_at, status)、Campaign(segment, message, send_at)、UserPreference(user, channel opt-outs, quiet_hours)、DeliveryAttempt
- API：
  - `POST /notifications {user_id, channel, priority, payload, send_at?, idempotency_key}`
  - `POST /campaigns {segment_id, payload, send_at?}`
  - `PUT /users/{id}/preferences`

## High-Level Design
（原文僅標題；補充，非原文）
1. 單發：API -> 驗證 + 寫入 durable 儲存 -> 排入 queue -> Channel Worker 查偏好 -> 呼叫 APNs/FCM/SES/Twilio；排程者由 scheduler（時間索引）在 send_at 觸發。
2. Campaign：展開 job（fan-out）：分段讀取 segment 用戶 -> 分批寫入各用戶通知 queue，避免單一巨大工作。
3. 偏好：Preference Service（DB + cache），發送前檢查 opt-out 與 quiet hours（quiet hours 內延後到結束）。

## Deep Dives（依原文大綱逐條）
### 1) 如何保證已接受的通知絕不被丟失？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：收到請求後只放在記憶體 queue/直接呼叫外部 provider，服務重啟即遺失。
- 好解：先寫入 DB 再回 202，之後非同步處理；失敗重試。
- 最佳解：Durable queue（Kafka/SQS）作為接受點，ack 後才算接受；或用 transactional outbox（DB 寫入與 queue 發布同一 transaction，relay 發布）。Worker 處理成功才 commit offset；重試用指數退避，最終進 DLQ 並告警。
- 取捨：at-least-once 保證不丟但可能重複，由下一題去重補上。

### 2) 如何在 campaign 轟炸期間仍於 5 秒內送出高優先級通知？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：單一 queue，campaign 的 100 萬筆在前面，OTP 排在後面等好幾分鐘。
- 好解：按優先級分離 queue（high/low），worker 優先消費 high。
- 最佳解：獨立的 topic + 獨立 consumer pool（資源隔離，而非只靠排序），high 池永遠有保留容量；campaign 走受限速的 low 通道（rate limit 也保護下游 provider）；campaign fan-out 分批、可暫停。
- 取捨：隔離浪費些許閒置容量，換取確定性的延遲保證；僅排序（priority queue）在飽和時仍有 head-of-line blocking 風險。

### 3) 在 at-least-once 之上如何避免重複通知？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：假設不會重複，重試時使用者收到兩次 OTP。
- 好解：Notification 帶 idempotency key（上游提供或由 notification_id 推導），Worker 發送前用 DB/Redis `SETNX` 檢查是否已送。
- 最佳解：去重表（key -> 狀態：pending/sent）以原子方式 claim；呼叫 provider 時傳遞冪等 key（若 provider 支援）；先 claim 後送出，崩潰在送出與記錄之間的窗口仍可能重複，需接受 at-least-once 並盡量縮小。
- 取捨：真正 exactly-once 不可能（外部 provider 非 transactional）；去重表需 TTL 清理。

### 其他可考慮的 deep dive（原文有此章節但無標題）
補充：provider failover（多家 SMS 供應商）、使用者時區 + quiet hours 排程、速率控制與背壓、可觀測性。

## 關鍵數字與 back-of-envelope
- （原文）10M/天 ≈ 100/s 平均；1M/5min > 3,000/s；設計尖峰 5,000/s（約 50x）。
- 補充：若每筆約 1KB，5,000/s ≈ 5MB/s，Kafka 單叢集輕鬆承載；真正瓶頸是下游 provider 的 rate limit 與 worker 並行度。
- 補充：若 provider 單連線 ~100 req/s，則 5,000/s 需 ≥ 50 並行連線。

## 可遷移的 pattern（3-5 條）
1. 先持久化再 ack（durable queue / outbox）保證不丟。
2. 資源隔離（獨立 queue + 獨立 consumer pool）解決 head-of-line blocking 與優先級。
3. At-least-once + idempotency key 去重 ≈ 實務上的 exactly-once。
4. 大型 fan-out 拆成分批、可限速、可暫停的 job。
5. 尖峰/平均比高 -> 用 queue 削峰，並對下游限速。

## 常見追問（3-5 題，附簡短答案）
- 排程通知如何實作？按 send_at 分桶的時間索引（DB 查詢輪詢或 delay queue/時間輪），到期移入 queue。
- Quiet hours 內的通知？延後至結束，高優先級（如安全告警）可旁路。
- Provider 當機？Circuit breaker + 備援 provider + 重試退避。
- Campaign 100 萬用戶如何展開？批次讀取 segment（cursor），每批寫入 queue；記錄進度可續跑。
- 如何追蹤送達狀態？Provider callback/webhook 更新 DeliveryAttempt（分析 dashboard 屬 out of scope）。
