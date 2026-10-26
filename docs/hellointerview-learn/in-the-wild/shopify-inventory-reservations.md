# How Shopify Moved Inventory Reservations from Redis to MySQL
> 來源：https://www.hellointerview.com/learn/system-design/in-the-wild/shopify-inventory-reservations ｜ 分類：in-the-wild ｜ 原始 eng blog：Shopify Engineering（原文標示 2026-05-12；https://shopify.engineering/scaling-inventory-reservations）

## 一句話重點
Reservation 與永久庫存帳本必須在同一個 transaction 提交，所以把 reservation 從 Redis 搬進 MySQL，並用「一個可預約單位一列 + SELECT ... FOR UPDATE SKIP LOCKED」避開單列 counter 的鎖爭用。

## 背景與問題（規模、痛點）
- Shopify 處理超過 14% 的美國電商。每個 checkout 都有 oversell protection：買家開始付款時保留商品數分鐘；付款成功則永久扣除庫存；失敗或逾時則釋放。
- 錯誤代價：超賣要取消訂單；隱藏實際還有的庫存則損失銷售。
- 舊系統：Redis 每個 item 一個 counter（Redis 單線程執行指令，兩個買家不可能同時搶到最後一件）；永久庫存在 MySQL。付款成功要做兩件事（扣 MySQL、清 Redis reservation），跨兩個 DB 無法一起 commit。
  - 先更新 MySQL 後 crash：Redis 仍視為保留 -> 隱藏實際可售庫存。
  - 反過來：清了 reservation 但 MySQL 沒扣 -> 已賣出的又變可售。
  - 換順序只是換失敗類型，視窗仍在。
- 常見解法不夠：two-phase commit 需雙方都參與協定，Redis 不行；outbox / reconciliation 只能事後修復，flash sale 中短暫不一致就可能重複賣。

## 演進過程（舊架構 → 哪裡爆 → 新架構，保留原文數字）
1. 舊：Redis counter（reservation）+ MySQL（帳本）-> 無法原子提交。
2. 第一次嘗試 MySQL（失敗）：每個 item 一列 + 數量 counter，`UPDATE reservations SET available = available - 1 WHERE inventory_item_id = 42 AND available >= 1`。InnoDB 一次只給一個 transaction 該列的 row lock，flash sale 時數千 checkout 擠在同一把鎖，序列化、慢到爬。
3. 新：`reservation_units` 表，每列代表一個目前可預約的單位。預約三件 = 在同一 transaction 內鎖住並選出三列可用列、從池中移除，並在 `reserved_quantities` 建一筆 active hold。使用 MySQL 8 `FOR UPDATE SKIP LOCKED`，兩買家鎖不同列並行提交。
4. 有界池：單一 item 可能產生數十萬閒置列、掃描變慢，且 item 有數百萬個，所以每個 item 的列數上限 1,000，由 replenishment 程序補池。
5. 結果：撐過 Black Friday 2025，merchant sales 高峰達 $5.1 million / 分鐘的紀錄。

## 關鍵設計決策與取捨（這是主體，寫細）
- **同 DB 才有原子性**：需求是 reserve / claim 與帳本一起 commit，只有與帳本同一個 DB 的列能做到。Redis 的併發計數一直是對的，卻仍得離開，因為不能參與帳本 transaction。
- **一單位一列（= Ticketmaster 的 seat-per-row）**：把爭用從一列分散到一池列；`SKIP LOCKED` 讓一般會等待的 `FOR UPDATE` 改成略過已鎖列繼續找。
- **有界池 + replenishment**：避免表無限成長。池被搶空時，預約請求會 inline refill 後重試；用鎖確保只有一個 transaction 補貨，其他請求等待，避免重複加容量。代價是觸發 refill 的請求變慢，但不會因池落後而拒絕帳本仍有庫存的買家。原文指出：blog 沒說 fallback 增加多少延遲，也沒說訂單大於 1,000 列池時怎麼處理。
- **三個鎖行為修正**：
  1. 原型用 auto-increment PK + secondary index 查詢，InnoDB 會同時鎖 index entry 與 table row（2 把鎖）。改成 `PRIMARY KEY (shop_id, inventory_item_id, inventory_group_id, id)`，查詢直接掃並鎖 table row，每單位一把鎖，熱路徑鎖流量減半。
  2. REPEATABLE READ 下鎖定查詢也鎖 gap；池空時鎖到索引尾端的 gap，正好是 replenishment 要插入的位置 -> 阻塞或死鎖。改用 READ COMMITTED（不取 gap lock），這是 Shopify 程式碼庫第一次使用非預設 isolation level。
  3. 不同路徑以不同順序碰 reservation 表造成 ordering deadlock。統一鎖順序：先從 `reservation_units` 刪列、再往 `reserved_quantities` 插 hold。
- **付款未完成時的過期（原文標明 blog 沒提，為 HI 的推測）**：
  - Redis 時代：TTL 不適用，因為是每 item 一個 counter，TTL 會刪整個 counter；改成每 reservation 一個 key，則計數需 O(n) 掃 keyspace，且過期不會觸發 INCR 還回單位，還會刪掉唯一紀錄。keyspace notification 是 fire-and-forget pub/sub 會丟事件。較佳做法：sorted set 以 deadline 為 score，worker 彈出到期者，atomic script 移除並還回 counter；或在每次 reserve 的 script 內順便 reclaim 少量（有上限，因 script 執行時阻塞其他指令）到期 hold，長尾 item 仍需背景 sweep。
  - MySQL 時代：hold 是一列帶 `expires_at`；replenishment 計算「帳本數 - 仍有效的 hold」，有效 = `expires_at > NOW()`，deadline 過了自動不計入，下次 refill 自動還回容量，不需要任何事件觸發。清理 job 只是 GC（防表膨脹、防忘記加 filter 的查詢），不是正確性所需。沒有人在 10 分鐘預約窗口內持有 DB lock，鎖只存在毫秒級的短 transaction。
- **取捨**：用 replenishment 程序（需運行、監控、on-call，最自然的失敗模式是 flash sale 中池空）換掉一個 Redis cluster；因新的活動部件在重要的 transaction 邊界內，所以划算。原文也提醒：若 hold 與記錄不必一起 commit，Redis counter 仍是更簡單的工具。MySQL 8 的 SKIP LOCKED 出現前此結論是對的，之後就錯了——過去排除某技術的理由值得重新檢驗。

## 面試怎麼用（這個案例可以拿來支撐哪類題目的哪個論點）
- 庫存 / 票務 / 搶購：單列 counter 會成為 hot row；拆成一單位一列 + SKIP LOCKED 分散爭用。
- 「為什麼不用 Redis 做 reservation？」：因為需與帳本原子提交；2PC / outbox 的限制。
- 預約過期：把 deadline 存在資料裡（`expires_at`）並在查詢中過濾，比依賴事件 / TTL 更穩健。
- 鎖調校：gap lock、isolation level、一致的鎖順序避免 deadlock。

## 相關題目
- [Ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)（seat-per-row、預約過期）
- [Flash Sale](../../hellointerview-breakdowns/flash-sale.md)
- [Online Auction](../../hellointerview-breakdowns/online-auction.md)
- [Payment System](../../hellointerview-breakdowns/payment-system.md)

## 自測問題（3-5 題附簡答）
1. Redis + MySQL 雙寫為何有 bug，換順序能解嗎？ 答：兩個 DB 無法一起 commit，crash 在中間會不一致；換順序只是換成另一種不一致（隱藏庫存 vs 重複賣出）。
2. 單列 counter 為何在 flash sale 變慢？ 答：InnoDB row lock 一次只給一個 transaction，數千 checkout 序列化在同一把鎖。
3. SKIP LOCKED 如何解決？ 答：略過已被鎖的列繼續找可用列，不同買家鎖不同列並行 commit；配合一單位一列。
4. 為何池要有界、池空怎麼辦？ 答：避免每 item 數十萬列拖慢掃描（上限 1,000）；池被搶空時 inline refill（以鎖保證只補一次）再重試。
5. MySQL 設計下 hold 怎麼自動過期？ 答：hold 存 `expires_at`，replenishment 只計 `expires_at > NOW()` 的 hold，過期自然不計入，下次 refill 還回容量；清理 job 只是 GC。
