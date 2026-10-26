# LeetCode（線上判題 + 競賽排行榜）
> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/leetcode ｜ 難度：Medium ｜ 類別：Managing Long Running Tasks

## 一句話核心
小規模系統（數十萬用戶、~4000 題）的重點只有兩件事：(1) 在隔離的 container 沙盒中安全執行不受信任的使用者程式碼（配 queue + 非同步 polling 取結果），(2) 用 Redis Sorted Set 做競賽即時排行榜、client 每 5 秒 polling 而非 WebSocket。

## 需求
**Functional（Core）**
- 檢視題目列表
- 檢視單一題目並用多種語言寫解答
- 提交解答並取得即時回饋
- 競賽的即時排行榜

Out of scope：user auth、user profile、付款、user analytics、social 功能。假設使用者已驗證，userId 在 session / JWT。

**Non-functional（Core）**
- availability > consistency
- 執行使用者程式碼時需隔離與安全
- 提交結果 5 秒內回傳
- 支援 100,000 人的競賽

Out of scope：fault-tolerant、安全交易、CI/CD / 可測試性、定期備份。

重要背景：LeetCode 只有數十萬用戶與約 4,000 題，相對多數系統設計題是**小規模**，會顯著影響設計（避免 over-engineering）。

## Core Entities & API
Entities：Problem（題目、測試案例、預期輸出）、Submission（使用者程式碼與結果）、Leaderboard。（User 可加但屬隱含。）

```
GET  /problems?page=1&limit=100 -> Partial<Problem>[]     # 只回 title/id/level/tags
GET  /problems/:id?language={language} -> Problem          # 含該語言的 code stub，預設如 python
POST /problems/:id/submit -> Submission   { code, language }
GET  /leaderboard/:competitionId?page=1&limit=100 -> Leaderboard
```
- **安全提醒**：userId 不放 API 參數（從 session/JWT 取），timestamp 由 server 產生；client 傳來的資料不可信。

Problem schema（NoSQL，測試案例以 subdocument 巢狀）：`id, title, question, level, tags[], codeStubs{python, javascript, typescript...}, testCases[{type, input(JSON), output(JSON)}]`。codeStubs 可由 admin 手填，或用 LLM 從單一語言範例生成。

## High-Level Design
小系統用 **monolith / 簡單 client-server** 即可，微服務開銷不值得。

```
Client (Monaco Editor)
  -> API Server -> DB (DynamoDB: problems, submissions)
  -> POST submit -> [Queue (SQS)] -> Code Execution Workers/Containers (per language)
       -> result -> API Server -> DB + Redis (leaderboard sorted set)
  -> GET /check/:id (poll 1s) -> DB
  -> GET leaderboard (poll 5s) -> Redis
```

### 1) 題目列表
API Server + DB；DB 需 index 支援分頁。作者選 NoSQL（DynamoDB），因為不需複雜查詢，且想把 test cases 巢狀在 problem 內。

### 2) 檢視題目
`GET /problems/:id` 回題目與 code stub，前端用 **Monaco Editor** 編輯。

### 3) 提交與即時回饋 —— 如何執行程式碼
- **爛解：直接在 API Server 跑**。安全（惡意程式刪資料、外流、挖礦、DDoS）、效能（CPU 密集、無限迴圈、memory leak）、隔離（同 process 崩潰拖垮整個 server）三方面都不可行。
- **好解：VM**。隔離性強、可重置；但資源重、啟動慢，生命週期管理（資源耗盡、忘記關閉的成本）麻煩。
- **最佳解：Container（Docker）**。與 VM 差異：VM 經 hypervisor 跑完整 OS，隔離強但大且慢；container 共用 host kernel、只隔離 process，輕量啟動快、隔離較弱。每個支援的 runtime（Python/JS/Java）一種 container，可跨多次提交重用。缺點：共享 kernel，需正確設定防逃逸與資源限制。
- **最佳解：Serverless function**。自動擴縮、適合 CPU 密集且負載不可預測；缺點：cold start 延遲、資源上限。
- **作者選擇 container**：提交量變異不大、想避開 cold start。
- 流程：API Server 把程式碼送到對應語言 container → container 在沙盒執行（不對外發呼叫；管理 container 的 worker 同步呼叫，例如 Docker exec API，從 stdout 或掛載 volume 讀輸出）→ API Server 存結果進 DB 並回傳。

### 4) 即時排行榜（初版）
競賽定義：90 分鐘、10 題、最多 100k 人；分數 = 解題數，同分比完成所有題目所花時間。

SQL 版：
```sql
SELECT userId, COUNT(DISTINCT problemId) AS numSolvedProblems, MIN(submittedAt) AS lastSolveTime
FROM submissions WHERE competitionId = :competitionId AND passed = true
GROUP BY userId ORDER BY numSolvedProblems DESC, lastSolveTime ASC
```
（原文用 `MIN(submittedAt)` 命名 lastSolveTime，嚴格說同分比較應看最後一題時間；面試時可點出。（補充））
DynamoDB 版：以 competitionId 為 partition key 建 **GSI**，查出再於記憶體 group & sort。Client 每 ~5 秒重新請求。作者承認此解 DB 負載很大，留待 deep dive 優化。

## Deep Dives

### 1) 如何確保執行使用者程式碼的隔離與安全？
在 container 之上再加：
- **Read-only filesystem**：程式碼目錄唯讀，輸出寫入短暫存在的 temp 目錄。
- **CPU / Memory 限制**：超限就 kill container。
- **Explicit timeout**：如 5 秒，殺掉無限迴圈，也幫助滿足 5 秒回應需求。
- **限制網路**：關閉 container 網路；AWS 可用 VPC Security Groups / NACLs 限制進出流量。
- **Seccomp 限制 system calls**。
- 面試不需深入實作細節，說出「Docker + 限網路 + CPU/memory 上限 + timeout」通常就夠。

### 2) 如何更有效取得排行榜？
- **爛解：Polling + DB query**（即初版）。每次輪詢都查並排序大量資料，隨用戶數成長 DB 負載與延遲飆升。
- **好解：Cache + 定期更新**。Redis 存當前榜單，每 ~30 秒從 DB 重算。降低 DB 負載，但新鮮度受限於 30 秒，client 仍需 polling；適合較小規模競賽。
- **最佳解：Redis Sorted Set + 定期 polling**。
  - 提交處理完同時更新 DB 與 Redis sorted set；client 每 5 秒 polling，server 直接從 sorted set 取 top N，不查 DB。
  - Key：`competition:leaderboard:{competitionId}`，score = 總分 / 解題時間，value = userId。
  - 更新：`ZADD competition:leaderboard:{competitionId} {score} {userId}`；取 top N：`ZRANGE ... 0 N-1 REV WITHSCORES`（`ZREVRANGE` 在 Redis 6.2 已 deprecated）。
  - 先回前幾頁（如 top 1,000），使用者翻頁時再取下一頁。
  - 優點：實作比 WebSocket 簡單、5 秒延遲可接受、大幅降低 DB 負載、可擴展。
  - **為何不用 WebSocket**：此規模與可接受的 5 秒延遲下屬於 overkill；Staff 候選人會說明「我知道更複雜的方案，但這裡不值得」。
  - 可做漸進式 polling：比賽最後幾分鐘 2 秒、其他時間 10 秒。

### 3) 如何擴展到 100k 人的競賽？
API Server 水平擴展即可撐住；瓶頸是 CPU 密集的程式執行。
- **爛解：Vertical scaling**。估算：尖峰 10k 同時提交 × 每份 ~100 個測試案例 × 每案 100ms（保守，實際多為 10-50ms）→ 1M 測試案例 = 100,000 秒（> 27 小時）；若要在一分鐘內跑完需約 **1,667 CPU cores**，最大 AWS instance 也僅數百 vCPU，且大機器平時閒置浪費。
- **好解：動態水平擴展**。每個語言 container 水平擴展，用 auto-scaling group（AWS 可用 ECS + ECS Auto Scaling）依流量/CPU/memory 調整。缺點：過度配置的成本風險。
- **好解：水平擴展 + Queue（SQS）**。API Server 把提交丟進 queue，container 取用；緩衝尖峰、不丟提交、容器失敗可 **retry**（重新入列）。
  - 系統變成**非同步**：新增 `GET /check/:id`，client 每秒 polling 提交狀態（DB 查詢，有結果回結果，否則回 "processing"）。Worker 取得結果後通知 App Server 同時更新 DB 與 cache。
  - 不用 WebSocket：1 秒 polling 已足夠，persistent connection 增加複雜度。實際上 LeetCode 就是這樣做的（Network tab 可見 polling）。
  - 缺點：以此規模可能 over-engineering（用戶需報名競賽就能預測尖峰、預先擴容）；作者仍選擇用 queue，主因是支援 retry 與緩衝。

### 4) 如何實際對任意語言的使用者程式碼跑測試案例？
- 不要為每題每語言各寫一套測試；每題只寫**一套**測試，語言無關。
- 需要：標準化的輸入/輸出**序列化格式** + 每個語言的 **test harness**（反序列化輸入、餵給使用者程式碼、與反序列化後的預期輸出比對）。
- 例：Max Depth of Binary Tree。TreeNode 以 level-order (BFS) 陣列序列化（`[3,9,20,null,null,15,7]`），每個語言有自己的 TreeNode 類別可反序列化；container 內使用者程式碼同目錄要有該類別檔。test case 含 `type`、`input`、`output`。
- 每種資料結構都需定義序列化策略。

## 關鍵數字與 back-of-envelope
- 規模：數十萬用戶、~4,000 題（小規模）
- 競賽：90 分鐘、10 題、最多 100k 人
- 提交 5 秒內回傳；timeout 範例 5 秒
- 尖峰 10k 提交 × 100 test case × 100ms = 1M test case = 100,000 秒 ≈ 27+ 小時；約需 1,667 cores 才能一分鐘跑完
- 排行榜 polling：5 秒；提交結果 polling：1 秒；cache 定期更新範例：30 秒
- 首次排行榜回傳：top 1,000 左右

## 面試官期待
- **Mid（IC4，80/20）**：清楚定義 API 與資料模型，HLD 可運作；理解執行使用者程式碼需要安全與隔離，理想上提出 container、VM 或 serverless 之一。
- **Senior（IC5，60/40）**：快速走完 HLD，把時間花在如何安全隔離執行程式碼；能比較 container vs VM vs serverless 並說明選擇；能跳出「畫方塊」模式，講出如何實際對使用者程式碼跑測試案例。
- **Staff+**：作者通常不拿這題問 Staff+；若問，期待主導全程、主動識別問題、說明取捨、講清楚測試案例執行與安全隔離且滿足 5 秒，並設計**不 over-engineer 但有清楚擴展路徑**的簡單系統。

## 可遷移的 pattern
1. **Managing Long Running Tasks**：API 立刻回 job id，queue + background worker 處理重活，client polling 查狀態；適用轉碼、報表、批次處理。
2. **不信任程式碼的沙盒化**：container + read-only FS + CPU/memory 上限 + timeout + 無網路 + seccomp 的縱深防禦。
3. **Redis Sorted Set 做 leaderboard**：ZADD / ZRANGE REV，取代對 DB 做 group-by 排序。
4. **Queue 的價值不只削峰**：還提供 retry 與不丟任務；但要承認小規模下可能 over-engineering。
5. **Polling vs WebSocket 的取捨**：可接受秒級延遲時 polling 更簡單，並可做漸進式 polling 頻率。

## 常見追問
- **為什麼選 container 不選 VM / Lambda？** 比 VM 輕量快速，且提交量變異小，避免 serverless cold start；代價是共享 kernel，需靠 seccomp、資源限制等加固。
- **使用者程式碼進入無限迴圈？** 明確 timeout（如 5 秒）殺掉 process，並有 CPU/memory 上限讓 container 被 kill。
- **100k 人同時競賽怎麼撐？** API Server 水平擴展；程式執行 container 以 autoscaling + SQS queue 水平擴展；排行榜走 Redis。
- **為什麼排行榜不用 WebSocket？** 規模小、5 秒延遲可接受，polling 簡單夠用；需要時可調整頻率。
- **同一份測試案例如何跑多種語言？** 標準化序列化格式（如 tree 用 BFS 陣列）+ 每語言一個 harness 反序列化並比對。
- **Container 失敗怎麼辦？** 因為有 queue，可將提交重新入列重試。
