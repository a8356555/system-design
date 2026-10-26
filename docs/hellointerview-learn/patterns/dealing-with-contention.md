# Dealing with Contention
> 🤖 **by agents**：原文為 Premium，僅公開介紹與章節大綱；除標「（原文）」的段落外，內容皆由 agents 依大綱撰寫／搜尋整理，非 Hello Interview 原文。
> 來源：https://www.hellointerview.com/learn/system-design/patterns/dealing-with-contention ｜ 分類：patterns

## 一句話重點
多個 process 同時搶同一份資源時，「read → check → write」不是原子操作會出 race condition；解法依序是 conditional write / 原子 UPDATE → pessimistic lock → OCC（版本號）→ isolation level → distributed lock，越往後越貴，能用單 DB 解就不要上分散式鎖。

## 原文大綱（原文）
- 介紹（原文）：Contention occurs when multiple processes compete for the same resource at the same time, like booking the last concert ticket or bidding on an auction item. Without proper handling, you get race conditions, double-bookings, and inconsistent state.
- The Race Condition（原文情境）：The Weeknd 演唱會剩最後一個座位，Alice 與 Bob 同時按 Buy Now；兩人都先 SELECT available_seats 看到 1，再各自 `UPDATE ... SET available_seats = available_seats - 1`，count 變 -1，兩張信用卡都被收 $500，兩人都收到同一座位的確認信。
- The Solution：Conditional Writes / Pessimistic Locking（Common Failure Modes）/ Optimistic Concurrency Control / Isolation Levels / Distributed Locks
- Choosing the Right Approach
- When to Use in Interviews：Recognition Signals / Common Interview Scenarios / When NOT to overcomplicate
- Common Deep Dives：「How do you prevent deadlocks with pessimistic locking?」「How do you handle the ABA problem with optimistic concurrency?」「What about performance when everyone wants the same resource?」
- Conclusion

## 內容（by agents）
### The Race Condition：問題
根因是 check-then-act 之間有空窗（TOCTOU）。症狀：超賣、雙重預訂、餘額變負、重複扣款。重點不是「讀到舊值」，而是「檢查與寫入不在同一個原子步驟」。

### Conditional Writes（最簡單）
把檢查放進寫入條件，讓 DB 單一語句原子完成：
```sql
UPDATE concerts SET available_seats = available_seats - 1
WHERE concert_id = 'weeknd_tour' AND available_seats > 0;  -- 看 affected rows
```
affected rows = 0 即售罄。也可用 DB CHECK constraint（`available_seats >= 0`）、unique constraint（(event, seat) 唯一）、DynamoDB `ConditionExpression`、Redis `SET NX`。取捨：只適用「單一資料列／單一 DB」且條件可寫成 predicate；跨多表、跨服務的不變量不行。

### Pessimistic Locking
先鎖再做：`SELECT ... FOR UPDATE` 鎖住該列，其他 transaction 等待。適合衝突機率高、臨界區短、錯了代價大（金錢）。
**Common Failure Modes**：
- 鎖持有太久（交易內呼叫外部 API／等使用者）→ 吞吐崩潰、connection pool 耗盡。
- Deadlock：A 鎖 1 再要 2、B 鎖 2 再要 1。
- Lock 範圍過大（鎖整表／gap lock）造成無謂序列化。
- 忘了 timeout、client crash 後鎖未釋放（DB 會在 session 結束時放，但應用層鎖不會）。

### Optimistic Concurrency Control（OCC）
不鎖，假設衝突少：讀時帶 `version`，寫時 `UPDATE ... SET qty=qty-1, version=version+1 WHERE id=? AND version=?`，affected rows=0 就重試或回報失敗。適合讀多寫少、衝突率低；衝突率高時 retry storm 浪費資源，反而比悲觀鎖差。同樣是 DynamoDB / etcd / HTTP ETag（If-Match）的常見模型。

### Isolation Levels
- Read Committed（Postgres 預設）擋 dirty read，不擋 lost update／write skew。
- Repeatable Read / Snapshot：Postgres 會對 lost update 報 serialization failure；MySQL InnoDB 行為不同（需注意）。
- Serializable：最強，DB 偵測衝突後 abort 其一，應用要準備 retry。代價是吞吐下降。
面試用法：說明「用 isolation 是把正確性交給 DB，但仍需 retry 邏輯」，不要只說「開 Serializable 就好」。

### Distributed Locks
當資源不只在一個 DB（跨服務、跨資料來源、外部資源）才需要。常見實作：Redis `SET key val NX PX ttl`（Redlock 有爭議）、ZooKeeper / etcd lease、DB 內的 lock table。必須要有 TTL（防 crash）與 **fencing token**（防過期持有者仍寫入，見 Martin Kleppmann 的批評）。取捨：多一個依賴、延遲更高、failure mode 多；能不用就不用。常見用法是「Redis 暫時 hold 座位 + DB 做最終一致的 conditional write」（見 ticketmaster）。

## Choosing the Right Approach（by agents）
| 情境 | 建議 |
|---|---|
| 單列計數／庫存 | Conditional write（原子 UPDATE） |
| 衝突頻繁、金錢 | Pessimistic lock（短臨界區） |
| 衝突稀少、讀多 | OCC（version） |
| 多列不變量（write skew） | Serializable 或明確鎖 |
| 跨服務／跨資源 | Distributed lock + fencing，或改 saga／單一寫入者（partition by key） |
另一個思路：把同一資源的寫入路由到單一 partition／單一 consumer（序列化到 queue），根本消除競爭。

## 常見深入題（by agents）
- **如何避免 pessimistic locking 的 deadlock？** 固定加鎖順序（依 id 排序）；縮短交易；`lock_timeout` + retry；一次 `SELECT ... FOR UPDATE` 鎖齊多列；讓 DB 偵測 deadlock 後 abort 並重試。
- **ABA 問題？** OCC 若比對的是「值」，值 A→B→A 會被誤判沒變。改用單調遞增 version／timestamp／LSN 而非比對值本身。
- **所有人都搶同一資源（熱點）怎麼辦？** 把庫存切成 N 個 sub-counter（sharded counter）分散鎖；排隊（virtual waiting room）限流；先在 Redis 原子扣再非同步落 DB；接受「預扣 + 逾時釋放」模型；對非真正稀缺資源放寬到最終一致。

## 面試怎麼用（by agents）
- Recognition signals：「最後一張票／最後一件」「搶購」「拍賣最高價」「帳戶餘額」「同時預約」「不能超賣」。
- 先講單 DB 的 conditional write／鎖，再被問到「跨服務／高併發」才升級到 distributed lock 或 queue 序列化。
- 不要過度設計：資源不稀缺、可容忍偶發衝突、或單列原子更新就夠時，別搬出 Redlock。
- 一定要提：retry 策略、冪等性、鎖的 TTL／fencing、失敗時如何補償。

## 相關題目
- [ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)
- [flash-sale](../../hellointerview-breakdowns/flash-sale.md)
- [online-auction](../../hellointerview-breakdowns/online-auction.md)
- [payment-system](../../hellointerview-breakdowns/payment-system.md)

## 自測問題（by agents）
1. 為什麼 `SELECT` 再 `UPDATE` 會超賣？怎麼一句 SQL 解掉？答：check-then-act 非原子；`UPDATE ... WHERE seats > 0` 並檢查 affected rows。
2. OCC 與 pessimistic lock 怎麼選？答：看衝突率與臨界區長短；衝突低用 OCC，高衝突或失敗代價大用悲觀鎖。
3. Redis 分散式鎖為何需要 fencing token？答：鎖過期後舊持有者（GC pause）仍可能寫入，token 讓儲存端拒絕舊 token。
4. Read Committed 能防 lost update 嗎？答：不能；需 conditional write、鎖或 RR/Serializable。
5. 熱門商品 10 萬人搶 100 件如何設計？答：Redis 原子預扣 + queue／waiting room 限流 + DB conditional write 落帳 + 逾時釋放。

## 參考來源
- https://www.postgresql.org/docs/current/transaction-iso.html （PostgreSQL isolation levels）
- https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html （fencing token）
- https://redis.io/docs/latest/develop/use/patterns/distributed-locks/ （Redis distributed locks）
- https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.ConditionExpressions.html （DynamoDB conditional writes）
- 註：以上為 agents 憑既有知識列出的公開文件；2026-10-19 已逐一確認連結可開啟（HTTP 200），但內容未逐條比對。
