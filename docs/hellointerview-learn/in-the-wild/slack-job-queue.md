# How Slack Put Kafka in Front of Its Redis Job Queue
> 來源：https://www.hellointerview.com/learn/system-design/in-the-wild/slack-job-queue ｜ 分類：in-the-wild ｜ 原始 eng blog：Slack Engineering, 2017-12-06（https://slack.engineering/scaling-slacks-job-queue/）

## 一句話重點
Redis 的記憶體同時承擔「吸收突發的 backlog」與「dispatch 工作空間」，一次 DB 變慢就鎖死；Slack 在前面加 Kafka 當持久 buffer、Redis 只保留短 dispatch window，並以最小改動保留既有應用語意。

## 背景與問題（規模、痛點）
- 最忙的日子處理超過 14 億個 job，峰值 33,000 jobs/秒；用於發訊息、push 通知、URL unfurl、行事曆提醒、計費等「太慢不能放在 web request」的事。
- 架構：一組 Redis cluster + worker pool 輪詢。web app 用 job type + 參數產生 job identifier，與 logical queue 名稱 hash 選 Redis host；該 host 做有限的 dedup（同 identifier 已在等待就丟棄）；worker 從 pending 取出 job 移到 in-flight list 再非同步執行；完成移除，失敗重試，最終進永久失敗 list 由人工修復。Job 從數毫秒到數分鐘。
- 事故：DB 層資源爭用拖慢 job 執行 -> job 在 Redis 堆積直到達 maxmemory -> enqueue 失敗，所有依賴 queue 的功能掛掉。更糟：dequeue 要把 job 移到 processing list，需要少量可用記憶體，Redis 滿了連出隊都做不到，DB 恢復後 queue 仍卡死，需大量人工介入。
- 其他問題：每個 job-queue client 連每個 Redis instance（完全二部圖）；worker 無法獨立擴展（多一個 worker 多一份輪詢負載，可能壓垮已超載的 Redis）；dequeue 成本隨 queue 長度線性增長（第二個回饋迴路，越長越慢，最需要排空時最慢）；queue 語意從未釐清，工程師不敢依賴或改動 dedup 行為。
- （補充，原文標為推測）：典型 Redis task queue 用 RPOPLPUSH 做 O(1) 移轉，但依值移除（LREM）要掃整個 list，造成線性成本；Slack 並未說明用了哪些結構。

## 演進過程（舊架構 → 哪裡爆 → 新架構，保留原文數字）
1. 舊：web app -> Redis（備份 + dispatch 同一塊 RAM）-> worker。
2. 爆：見上，burst buffer 與 dispatch workspace 共用有界 RAM，overload 以鎖死而非延遲結束。
3. 需求：backlog 存在不會 OOM 的持久處；排程需要真正的 rate limit 與 priority；執行容量擴展不增加對 Redis 的輪詢負載。
4. 新（「minimum viable change」）：web app -> Kafkagate（HTTP POST /enqueue）-> Kafka -> JQRelay -> Redis -> worker。enqueue 介面與 worker 端都不變。Slack 先保護 enqueue 路徑，排程與 worker 擴展留待之後。
5. Cluster：16 brokers、每 topic 32 partitions、replication factor 3、保留 2 天、rack-aware replication 對應 AZ；啟用 unclean leader election。
6. 驗證：負載測試 + 故障演練（broker 遺失、強制 unclean leader election、整個 cluster 重啟）皆達可用性目標。
7. Rollout：雙寫（舊 Redis 路徑與新 Kafka 路徑同時寫）+ JQRelay「shadow」模式（讀 Kafka 後丟棄），讓真實流量通過所有新元件而零使用者影響；每一跳計數（web app -> Kafkagate -> Kafka -> Redis）；heartbeat canary 每 partition 每分鐘一個，涵蓋全部 1,600 個 partition（50 個 topic × 32，一個 topic 對應一個 Redis cluster）；內部使用數週，再依 job type 逐一對客戶開放。
8. 結果：backlog 堆在磁碟，operators 可限速進入 Redis。原文推測今日 Slack 仍大致如此（Kafka 持久 buffer、Redis 短期 dispatch、worker 執行）。

## 關鍵設計決策與取捨（這是主體，寫細）
- **為何 Kafka 在前，不是取代 Redis**：Kafka 是 append-only log，磁碟上受 retention 而非 RAM 限制，突發只讓 log 變長。但 offset 是 partition 位置，不是 per-job 狀態；per-job ack、retry、dedup、in-flight 都要自建（retry 當 re-enqueue、dedup 用小型 keyed store），很多團隊這麼做，但 Slack 已有多年依賴 Redis 語意的程式碼，全面換成 Kafka 會把可用性修補變成重寫。
- **為何不換 RabbitMQ / SQS / beanstalkd**：同樣落地磁碟，但各自有不同 delivery 語意，一樣要重寫。開 Redis persistence 也沒用：dataset 還是要放得進 RAM，事故是容量問題不是持久性問題。只留 Redis 就是剛失敗的設計。
- **Kafkagate**：無狀態 Go 服務；維持與 broker 的持久連線、追隨 partition leader 移動、同步寫入，caller 必得到明確 ack 或錯誤。只等 partition leader ack（不等 replication）：最低延遲，換取 broker 在複製前掛掉時小機率遺失 job，Slack 判斷對多數 job 值得。enqueue host 優先連同 AZ 的 Kafkagate，必要時 failover。也省掉 enqueue 側對 50 個 Redis cluster 的連線扇出。
- **JQRelay**：每個 instance 把一個 Kafka topic 導入對應 Redis cluster；靠 Consul 分散式鎖確保每個 topic 只有一個 relay；失去鎖就釋放全部並重啟讓別人接手（auto-scaling group 的替換走同流程）。核心迴圈：先寫入 Redis（Redis 掛了就無限重試），成功後才 commit offset -> at-least-once，log 在後面吸收新工作。個別 job 出錯則 re-enqueue 回 Kafka，不阻塞也不遺失。rate limit 存在 Consul 並用 watch API 取得：堆積時 web app 全速 enqueue，operators 調低 relay 以匹配 worker 的執行能力。
- **多語言 runtime 的暗坑**：JQRelay 會解碼再重新編碼 JSON；Go 預設把 `<`、`>`、`&` 轉成 unicode 實體，PHP 則轉義 `/`，同樣資料不同位元組，造成「heartache」。
- **核心洞見**：把 backlog 放在不會 OOM 的地方，讓快速層只保存 in-flight 的東西。
- **現代對應**：Kafka consumer groups、SQS（持久 buffer + ack / retry / DLQ，但排程 / 優先權 / dedup 仍可能在別處）、Temporal 這類 durable execution、Redis Streams（一年後出現，但資料仍須放得進 RAM）。

## 面試怎麼用（這個案例可以拿來支撐哪類題目的哪個論點）
- 任何 job queue / 非同步任務系統：用 durable log 吸收突發、削峰；快速層只留短 window。
- 解釋「為何要 queue 前再加 queue」：兩種角色（burst buffer vs dispatch）資源需求不同，不該共用 RAM。
- 背壓：在 relay 處限速，而不是限制 producer。
- 可靠性語意：at-least-once（先寫目標再 commit offset）、leader-only ack 的延遲 vs 持久性取捨。
- 漸進遷移與驗證：double write、shadow mode、canary、逐 job type 放量。

## 相關題目
- [Job Scheduler](../../hellointerview-breakdowns/job-scheduler.md)
- [Notification System](../../hellointerview-breakdowns/notification-system.md)
- [Ad Click Aggregator](../../hellointerview-breakdowns/ad-click-aggregator.md)（Kafka 作為持久 buffer）

## 自測問題（3-5 題附簡答）
1. 為何 Redis 滿了之後連 dequeue 都失敗，DB 恢復也救不了？ 答：dequeue 要把 job 移到 processing list，需要少量可用記憶體；Redis 已滿，無法出隊，需人工介入。
2. Slack 為何不直接把 queue 換成 Kafka？ 答：Kafka offset 不是 per-job 狀態，ack / retry / dedup / in-flight 都要自建，且既有應用依賴 Redis 語意，會變成重寫；他們選 minimum viable change。
3. JQRelay 如何避免丟 job？ 答：先寫入 Redis 成功才 commit Kafka offset，Redis 掛了就重試；錯誤 job re-enqueue 回 Kafka。
4. 只等 partition leader ack 的取捨？ 答：延遲最低，但 leader 在複製前掛掉有小機率遺失 job；Slack 認為對多數 job 可接受。
5. 如何在上線時驗證新路徑？ 答：double write + JQRelay shadow 模式、每跳計數、每 partition 每分鐘 heartbeat canary（1,600 partitions）、內部數週後依 job type 放量。
