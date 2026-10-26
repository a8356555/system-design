# Cross-Cutting Patterns:所有經典題共用的決策與知識點

> 核心結論:每道 system design 經典題都是同一批 pattern 的重新排列組合。把這 12 個 pattern 的「判準」內化,面試時就不是背 YouTube 怎麼設計,而是看到需求就知道該套哪個 primitive、以及**什麼時候不該套**。
>
> 讀法:每章遮住表格,只看「一句話總結」與「什麼題會用到」,自己推一次判準,推不動再看。搭配 [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md) 的推導鏈練習(naive → 哪裡爆 → 放寬需求 → 套 primitive)。

---

## 1. 容量估算(back-of-envelope)

> 一句話總結:面試要的是**量級與推理過程**,不是精確數字。目標是推出「這個設計需不需要分片/快取/非同步」,而不是算到小數點。

### 機制/推導

標準流程是一條單向鏈,每一步都從上一步推出來:

```
DAU → 每人每天動作數 → 每日請求數 → 平均 QPS → peak QPS(×2~3)
                                          ↓
每筆資料大小 → 每日新增儲存 → ×保存年限 → 總儲存
                                          ↓
每筆 response 大小 × peak QPS → bandwidth
```

必背換算(背這幾個就夠推所有題):

| 換算 | 值 | 用途 |
|---|---|---|
| 1 天 | ≈ 86,400s ≈ **10^5 s** | 把「每日總數」除成 QPS 的萬能分母 |
| 1 個月 | ≈ 2.6M s ≈ **2.5×10^6 s** | 月活/月量換算 |
| 1 年 | ≈ **3×10^7 s** | 儲存保存期推算 |
| char / int | 1B / 4B | 單筆 row 大小估算 |
| UUID / timestamp | 16B / 8B | 同上 |
| 一則 tweet | ~300B(含 metadata) | feed 類題 |
| 一張縮圖 / 照片 | ~10KB / ~1MB | 圖片類題 |

「1M QPS 意味著什麼」的直覺錨點:

| 量級 | 直覺 | 設計意涵 |
|---|---|---|
| < 1K QPS | 單機扛得住 | 不用分片,一台 DB 就好 |
| ~10K QPS | 單機吃緊 | 需要 read replica + cache |
| ~100K QPS | 單機不可能 | 必須 sharding + cache 層 |
| ~1M QPS | 巨量 | 分片 + 多層 cache + 可能要 CDN/edge、非同步化 |

### 推導範例(feed 類)

```
2 億 DAU × 每人每天讀 20 次 feed = 40 億次讀/天
40 億 / 10^5 s ≈ 40,000 QPS 平均 → peak ×3 ≈ 120K QPS 讀
寫:2 億 × 每人發 0.1 篇 = 2000 萬篇/天 ≈ 200 寫 QPS(平均)
→ 讀寫比 ~200:1 → 這就是為什麼 feed 要 fan-out on write(第 7 章):
  寫少讀多,把成本推到寫端划算。
```

### 什麼題會用到

**每一題開頭都要做**。面試官第一步幾乎都會問「規模多大」,這是判斷後面所有設計決策(要不要分片、要不要快取、同步還非同步)的地基。

### 面試高分要點

- **先問澄清數字**(DAU?讀寫比?資料多大?),不要自己瞎猜。
- 算到「量級」就停(是 10K 還是 1M),不要糾結 3.7 還是 4.2。**算太細是反訊號**——顯得抓不到重點。
- 每個數字都要**接一句設計結論**:「120K 讀 QPS,單機不可能,所以需要 cache 層扛住熱點。」數字本身不得分,數字推出的決策才得分。
- peak factor 講清楚假設:「平時 ×2、有 event/尖峰用 ×3」。

---

## 2. 併發寫入處理(核心章)

> 一句話總結:多個請求同時改「同一份資料」時,誰贏、會不會互蓋、會不會排隊爆掉,是分散式系統最核心的決策。選型只看三個變數:**衝突率、latency 需求、能不能接受 lost update**。

### 完整分類法

| 手段 | 機制 | 適用衝突率 | latency | 會爆在哪 |
|---|---|---|---|---|
| **(a) 悲觀鎖 / `SELECT FOR UPDATE`** | 讀時就鎖 row,別人等 | 高衝突、必須序列化 | 差(要等鎖) | 同一 row 高併發 → **hot row**,全部排隊 |
| **(b) 樂觀鎖 / version + CAS** | 讀出 version,寫時 `WHERE version=N`,不中就 retry | 低衝突 | 好(不鎖) | 高衝突時 retry 風暴,白做工 |
| **(c) 原子操作下推** | 交給 DB/Redis 原子執行(`DECR`、`UPDATE x=x-1`) | 任意,但操作要能表達成原子 | 極好 | 操作太複雜無法原子化時不適用 |
| **(d) 佇列序列化** | 把併發寫丟進佇列,單消費者順序處理 | 極高衝突(flash sale) | 寫端非同步(有延遲) | 佇列積壓、需要非同步結果通知 |
| **(e) MVCC** | DB 內建:讀舊版本快照,寫建新版本 | 讀寫混合 | 好(讀不擋寫) | 長交易累積舊版本、write-write 仍要衝突偵測 |

### 逐項推導

**(a) 悲觀鎖**:最直覺——「我改的時候別人不准動」。`SELECT ... FOR UPDATE` 開交易鎖住 row。**問題**:秒殺 10 萬人搶同一個 `stock` row,全部卡在同一把 row lock 上排隊 = hot row(見 handling-unfamiliar §7)。適合衝突真的高、且必須嚴格序列化(如帳戶轉帳),但要接受吞吐被鎖限制。

**(b) 樂觀鎖 / version column**:賭「大部分時候沒人跟我搶」。

```sql
-- 讀:拿到 balance=100, version=5
UPDATE account SET balance=90, version=6
WHERE id=1 AND version=5;   -- 只有 version 還是 5 才成功
-- 影響 0 列 = 有人搶先改過 → 重讀 retry
```

衝突低時完勝悲觀鎖(不鎖、latency 好);衝突高時 retry 一直失敗,反而更糟。**判準:衝突率 <幾 %用樂觀,否則用悲觀或序列化。**

**(c) 原子操作下推**:不要「讀出來→在應用層算→寫回去」(這中間就是 race window),而是把運算下推給有原子保證的引擎:

- Redis `DECR stock`:單執行緒,天然原子,秒殺庫存首選。
- DB `UPDATE counter SET n = n + 1`:單語句原子,勝過讀改寫。

這是最優雅的解——只要你的操作能表達成一個原子指令,就沒有 race。

**(d) 佇列序列化**:flash sale 的終極解。與其讓 10 萬併發打 DB,不如**把併發變順序**:請求進 Kafka/queue,單一 consumer 依序扣庫存。併發問題直接消失(因為根本沒有併發了),代價是寫端變非同步、要處理結果回傳。

**(e) MVCC(Multi-Version Concurrency Control)**:DDIA 核心。DB 怎麼讓「讀不擋寫、寫不擋讀」?每筆寫產生新版本並標記交易 ID,讀取時看見「交易開始那刻的一致快照」,而不是等鎖。這就是 PostgreSQL / MySQL InnoDB 的 snapshot isolation 底層。面試講到「為什麼 read replica 讀舊資料不會卡住寫入」,答案就是 MVCC。

### 誰贏:衝突解決策略(多主 / 離線場景)

當寫入發生在多個節點(multi-leader、離線 app、CRDT),必須決定衝突時「誰的值贏」:

| 策略 | 機制 | 優點 | 致命傷 |
|---|---|---|---|
| **LWW(Last-Write-Wins)** | 比 timestamp,晚的贏 | 簡單、無狀態 | **靜默丟資料**;時鐘不同步時丟錯人的寫 |
| **Version vector** | 每節點各記一個 counter,能判斷「真並發」還是「有因果先後」 | 不會誤判、能偵測真衝突 | 存不下無限節點;衝突仍要上層決定怎麼合 |
| **CRDT** | 資料結構設計成「怎麼合都收斂」 | 自動合併、無需協調 | 只適用特定資料型別(counter、set、sequence) |

**判準**:能接受偶爾丟寫(如 presence、cache)→ LWW;不能丟寫且要正確偵測並發 → version vector;協作/離線編輯要自動合併 → CRDT。

### 協作編輯:CRDT vs OT

Google Docs 類題的專門併發問題(見 handling-unfamiliar §9,以及本 repo 的 OT 實作 [../google-docs-clone/README.md](../google-docs-clone/README.md)):

| | OT(Operational Transform) | CRDT |
|---|---|---|
| 核心 | 傳「操作」(insert at 5),收到並發操作先**轉換座標** | 設計成怎麼合都收斂的資料結構,每個字元帶唯一 ID |
| 心智負擔 | transform 函數要窮舉所有操作對,難寫難證明正確 | 資料結構複雜、metadata 膨脹 |
| 需要中央伺服器 | 傾向要(靠 server 定序) | 可 P2P、去中心 |
| 實務代表 | Google Docs 早期、本 repo 實作 | Yjs、Automerge、Figma |

本 repo 的 [../google-docs-clone/README.md](../google-docs-clone/README.md) 走 OT:operation 分 insert/delete/retain,server 維護 operation history + revision,client 送操作時帶 `revision`,server 用 transform function 把並發操作對齊座標。面試推到「operation-based + 處理並發順序 = OT;或設計 convergent 資料結構 = CRDT」就及格。

### 什麼題會用到

秒殺/搶票(d+c)、支付轉帳(a/b)、庫存(c/d)、協作編輯(OT/CRDT)、計數器(c)、離線同步 app(LWW/version vector/CRDT)、任何「同一 row 被多人改」的題。

### 面試高分要點

- 被問併發時,**先問衝突率**——這一句直接決定選悲觀還樂觀。
- 秒殺題別停在「加鎖」:要推到「別讓流量碰 DB → Redis 原子遞減 / 佇列序列化」,這是 senior 訊號。
- 講 lost update 時要能舉例:兩個人同時「讀 100 → 各自 -1 → 寫 99」,結果應是 98 卻變 99。這證明你懂 race 本質。
- 提 MVCC 能加分:「讀走快照所以不擋寫」是 DDIA 級別的理解。

---

## 3. 一致性譜系

> 一句話總結:「強一致 vs 最終一致」是假二分法。真實是一條光譜,每一級對應一個具體的使用者體驗保證;面試要能說出「這個功能需要哪一級、為什麼不用更強的」。

### 譜系(由強到弱)

| 級別 | 保證 | 具體場景 | 代價 |
|---|---|---|---|
| **Strong / Linearizable** | 所有人永遠看到最新值,像單機 | 銀行餘額、庫存、鎖 | latency 高、跨區難、可用性差 |
| **Bounded staleness** | 最多落後 N 秒 / N 個版本 | 儀表板、股價顯示 | 需時鐘/版本協調 |
| **Read-your-writes** | 你**自己**寫的一定讀得到(別人的不保證) | 發文後自己看得到那篇 | 需 session 綁定到同一 replica 或記 version |
| **Monotonic reads** | 不會「時光倒流」(讀到新的後不會又讀到舊的) | 留言數只增不減的錯覺 | 需綁 session |
| **Eventual** | 停止寫入後最終會一致 | 讚數、觀看數、DNS | 讀可能讀到舊值 |

每降一級,就換來更低 latency、更高可用性、更容易跨區。**面試的功力是「精準挑最弱但夠用的那一級」**——讚數用 strong 是浪費,餘額用 eventual 是災難。

### Quorum:W + R > N

不靠單一 leader 也能有強一致的機制:N 份副本,寫要 W 份確認、讀要 R 份確認。只要 **W + R > N**,讀集合與寫集合必有交集 → 讀一定碰得到最新的那份。

```
N=3:
  W=2, R=2 → 2+2>3 ✓ 強一致(常見預設)
  W=3, R=1 → 寫慢讀快(讀多寫少場景)
  W=1, R=1 → 1+1<3 ✗ 只有最終一致(最快但可能讀舊)
```

調 W/R 就是在「讀延遲 vs 寫延遲 vs 一致性」之間滑動。

### CAP 的正確講法(別再說「三選二」)

分區(partition)發生時,你只能在 C 和 A 之間選一個:

- **CP**:分區時拒絕服務保正確(如需要 quorum 的 DB)。
- **AP**:分區時繼續服務但可能回舊值(如 DNS、購物車)。

但分區是**罕見事件**。CAP 沒說的是:平常沒分區時你其實在權衡 **latency vs consistency**——這才是 **PACELC**:`if Partition: C or A; Else: Latency or Consistency`。多副本強一致每次讀寫都要協調 = 平時就付 latency 稅。**面試講 PACELC 比只講 CAP 高一個檔次。**

### 既有材料:batch/serving 的一致性窗口

Lambda 架構的「batch 還沒更新完、但要 query」正是一個一致性窗口問題,解法是 **atomic swap + metadata cutoff**(見 [../dcard-interview.md](../dcard-interview.md) §7):batch view 用 staging table 算好後 `REPLACE PARTITION` 原子換入,並原子更新 `recent_threshold` metadata;查詢時讀 metadata 決定 batch/speed 各查哪段,避免重複計算或漏算。這是「用 atomic swap 把一致性窗口關掉」的漂亮實例。

### 什麼題會用到

支付/庫存(strong)、社群讚數觀看數(eventual)、發文後看自己(read-your-writes)、多區部署(PACELC 取捨)、任何有 read replica 的題(replication lag = 一致性窗口)。

### 面試高分要點

- 對每個資料項**分別**指定一致性等級,別一句「用強一致」帶過。
- 講 CAP 一定要加「分區是罕見的,平常真正的取捨是 PACELC 的 latency vs consistency」。
- 能把 quorum 的 W+R>N 畫出交集圖 = 加分。
- read-your-writes 的實作要能講:sticky session 綁 replica,或 client 記住自己寫入的 version 讀時比對。

---

## 4. Idempotency 與 exactly-once

> 一句話總結:分散式系統沒有真正的 exactly-once,只有 **at-least-once(重試)+ 去重(dedup)= 效果上的 exactly-once**。idempotency key 是去重的載體,reconciliation 是最後防線。

### 為什麼需要:重試的兩難

扣款 API timeout 了,錢扣了沒?不知道(見 handling-unfamiliar §8):

- 不重試 → 可能漏單(其實沒扣成功)。
- 重試 → 可能重複扣(其實扣成功了,只是 response 丟了)。

出路:**讓重試安全**,即 idempotent——同一個請求做幾次結果都一樣。

### idempotency key 的完整設計

| 設計點 | 做法 |
|---|---|
| **key 怎麼生成** | client 端生成(UUID),而非 server;同一「業務意圖」重試時必須用同一把 key |
| **dedup store schema** | `(idempotency_key PK, status, response_body, created_at)`;first-writer 靠 PK 唯一約束擋住並發重複 |
| **執行流程** | 收到 key → 查 store:沒看過 → 執行並記結果;看過且 done → **直接回上次的 response**;看過但 in-progress → 回 409/等待 |
| **TTL** | key 保留夠長覆蓋所有重試窗口(如 24h~7 天),太短會讓遲來的重試變成新請求 |
| **與 retry 的關係** | client 的 retry(backoff+jitter)必須帶原 key,否則去重失效 |

關鍵:dedup store 的**寫入要跟業務操作在同一交易**(或用 DB 唯一約束),否則「執行成功但還沒記 key」的瞬間崩潰,重試又會重做一次。

### at-least-once + dedup = effective exactly-once

這是整章的心臟。網路不可靠,傳輸層只能保證 at-least-once(重傳直到收到 ACK)。真正的 exactly-once 不存在於傳輸,而是**接收端去重**做出來的效果:

```
producer 重傳(at-least-once)→ consumer 用唯一 key 去重 → 效果 = exactly-once
```

### Kafka / Flink 的 exactly-once(引用不重寫)

流式框架的 exactly-once 已有完整材料:

- **Flink checkpointing**:定期把 operator state + source offset 一起做一致性快照,故障時回滾到上個 checkpoint 重放,配合 two-phase commit sink 達到 end-to-end exactly-once。細節見 [../data-intensive-app-flink/README.md](../data-intensive-app-flink/README.md)。
- **Kappa 的 exactly-once 依賴**:見 [../dcard-interview-kappa/README.md](../dcard-interview-kappa/README.md) 與 [../dcard-interview.md](../dcard-interview.md) §6——Kappa 的正確性高度依賴 streaming 框架的 exactly-once 語意 + watermark 處理遲到資料,這也是它「難做到絕對正確」的原因。

### reconciliation:最後防線

再嚴謹的 idempotency 也可能有漏網(bug、跨系統不一致)。金流/庫存類系統一定要有**每日對帳**(見 handling-unfamiliar §8):把兩邊(如自家帳本 vs 銀行流水)拉出來比對,找出差異補償。這是承認「線上防不完,離線補一刀」的成熟設計。

### 什麼題會用到

支付、下單、庫存扣減、通知去重(同一則別發兩次)、任何有 retry 的寫入 API、任何 message queue consumer(訊息會重送)。

### 面試高分要點

- 一定要講出「exactly-once 不存在,是 at-least-once + dedup 做出來的」——這句話立刻分辨你懂不懂分散式。
- idempotency key 由 **client 生成**、重試沿用同一把,是常被漏掉的關鍵。
- dedup 記錄與業務操作的**原子性**(同交易/唯一約束)是深度所在。
- 收尾提 reconciliation 當安全網,顯示你知道線上防禦有極限。

---

## 5. Sharding 與 consistent hashing

> 一句話總結:單機存不下就要分片;分片的三種切法各有代價,而 consistent hashing 專門解決「擴容時不要搬光所有資料」——因為 `mod N` 在改 N 時是災難。

### 三種 sharding 判準

| 切法 | 機制 | 優點 | 致命傷 | 適用 |
|---|---|---|---|---|
| **Hash sharding** | `hash(key) → shard` | 分布均勻、無熱點(除非單 key 熱) | **無法範圍查詢**;擴容要 rehash | 點查為主(user by id) |
| **Range sharding** | 按 key 區間切(A-M / N-Z) | 支援範圍掃描、scan 友善 | 易熱點(如按時間切,今天的 shard 被打爆) | 範圍查詢多(時序、字典序) |
| **Directory sharding** | 查一張 lookup 表決定去哪 | 最靈活、可任意搬遷 | 多一跳、lookup 表變單點/瓶頸 | 需要靈活 rebalance |

### consistent hashing 推導

**naive:`shard = hash(key) % N`**
→ **哪裡爆**:N 從 4 變 5,幾乎**所有 key 的 `% N` 結果都變** → 幾乎全部資料要搬家 → 擴容 = 全體 cache miss / 大遷移。
→ **放寬**:我不需要完美均勻,只要「加一台時只搬該台附近的一小段」。
→ **primitive:hash ring**。把 hash 空間想成一個環(0 ~ 2^32),節點和 key 都 hash 到環上,key 歸給「順時針遇到的第一個節點」。加一台節點,只有它到前一個節點之間的 key 要搬,其他不動 → 遷移量從 O(全部) 降到 O(1/N)。

**virtual nodes(解決不均勻)**:節點少時環上分布不均,一台可能扛很多。解法:每台實體節點在環上放 100~200 個 virtual node(用 `hash(node + i)`),分布更均勻,且下線時它的負載平均分攤給其他台,而非全丟給下一台。

### resharding 實務:雙寫遷移

線上改 shard 不能停機,標準做法:

```
1. 新舊 shard 方案並存,寫入「雙寫」(同時寫舊+新)
2. 背景 backfill 把歷史資料從舊搬到新
3. 讀取先切到新 shard 驗證一致
4. 停舊寫、下線舊 shard
```

### hot shard:sub-key 拆分

即使 hash 均勻,單一超熱 key(某明星、某爆紅商品)還是會把它所在的 shard 打爆。解法:把該 key 拆成 `key#0 ~ key#9` 十個 sub-key 分散到不同 shard,讀時聚合十份(counter 類尤其適用)。這與第 8 章 hot key 相通。

### 既有材料:partition 數推理

Kafka topic 怎麼分區?見 [../dcard-interview.md](../dcard-interview.md) §3:按 `user_id` 分區保證同一 user 的事件有序,但直接 `user_id` 當 key 會產生上百萬 partition → 用 `user_shard = user_id % N` 收斂成**數百到低千** partition。這正是「分片粒度不能太細也不能太粗」的實例。

### 什麼題會用到

任何 DB/cache 存不下要水平擴展的題、分散式快取(consistent hashing 經典場景)、Kafka 分區、URL shortener 的 key 分布、feed 儲存。

### 面試高分要點

- 講 consistent hashing 一定要先講「為什麼 `mod N` 不行」——沒有這個對比,ring 就沒有動機。
- virtual node 是必答的第二層,不然「節點少時不均 + 下線負載全丟給鄰居」的問題沒解決。
- 主動提「hash 均勻也擋不住單一超熱 key」顯示你想到了 hash sharding 的盲點。
- resharding 提「雙寫 + backfill」證明你知道線上遷移不能停機。

---

## 6. 快取模式

> 一句話總結:快取的三種寫入策略在「一致性 vs 寫延遲 vs 資料遺失風險」間取捨;而快取失效(invalidation)與快取雪崩(stampede)才是真正的難題。

### 三種模式對照

| 模式 | 寫流程 | 一致性 | 寫延遲 | 風險 |
|---|---|---|---|---|
| **Cache-aside(旁路)** | app 先寫 DB,再刪/更新 cache;讀時 miss 才回填 | 較弱(有窗口) | 低 | 併發下「刪 cache 與回填」交錯可能存到舊值 |
| **Write-through(穿透寫)** | 寫先進 cache,cache 同步寫 DB | 強(cache 永遠最新) | 高(等兩層) | 冷資料也被寫進 cache 浪費空間 |
| **Write-back / write-behind(回寫)** | 寫只進 cache,非同步批次刷 DB | 弱 | 極低 | cache 掛了 = **資料遺失**;需持久化 cache |

**判準**:讀多寫少、能容忍短暫舊值 → cache-aside(最常見預設);要求 cache 與 DB 一致 → write-through;寫極多且能容忍遺失風險(如計數、log) → write-back。

### TTL 策略

- 熱門/穩定資料:長 TTL 或永久(如 URL shortener 的熱門短碼,見 [../url-shortener/README.md](../url-shortener/README.md):熱門 URL 永久快取,一般 URL 1 小時 TTL + LRU)。
- 易變資料:短 TTL(如統計查詢 15 分鐘)。
- TTL 是「一致性」與「命中率」的滑桿:短 = 新但常 miss,長 = 快但可能舊。

### cache stampede / thundering herd:三解法

熱門 key 過期的瞬間,成千上萬請求同時 miss、同時去打 DB → DB 被瞬間打爆。三種解法:

| 解法 | 機制 | 代價 |
|---|---|---|
| **Lock / single-flight** | 只放第一個請求去重算,其餘等它回填 | 等待者略增 latency |
| **Logical expiry** | value 存「邏輯過期時間」,過期後仍回舊值,但**背景**非同步刷新 | 短暫回舊值 |
| **TTL jitter** | TTL 加隨機抖動,避免大量 key 同一瞬間集體過期 | 實作簡單,首選之一 |

實務常組合:jitter 防「集體過期」+ single-flight 防「單一熱 key 過期」。

### invalidation 的兩難

「Cache invalidation 是電腦科學兩大難題之一」不是玩笑:

- 主動刪:寫 DB 後刪 cache——但「刪 cache 失敗」或「刪完到回填前的併發讀」會留下不一致。
- 靠 TTL 過期:簡單但有陳舊窗口。
- 進階:用 CDC(binlog)驅動 cache 失效,讓 DB 變更自動同步到 cache。

### 多層快取

真實系統快取是分層的(見 [../url-shortener/README.md](../url-shortener/README.md) 與 [../data-intensive-app/README.md](../data-intensive-app/README.md)):

```
Client(browser cache)
  → CDN / edge(靜態、地理近)
    → L1 本機記憶體(app 內,最快,不跨機)
      → L2 Redis(共享,跨機一致)
        → DB
```

每層攔掉一部分流量,越往裡命中率要求越低。

### 什麼題會用到

幾乎每題。URL shortener、feed、typeahead、任何讀多寫少、任何有熱點的系統。

### 面試高分要點

- 主動講 cache-aside 的併發不一致窗口(刪與回填交錯),別假裝快取沒有一致性問題。
- stampede 三解法能講出兩個 = 加分,尤其 logical expiry 與 jitter。
- 提多層快取並說每層「攔什麼流量」,而不是只堆名詞。
- 一句「invalidation 難,所以易變資料我傾向短 TTL + CDC 驅動失效」很加分。

---

## 7. Fan-out

> 一句話總結:「發一則貼文,怎麼送到所有粉絲的 feed」有 push(寫時展開)和 pull(讀時聚合)兩種,選擇是一道**寫放大 vs 讀放大**的成本數學題,而 celebrity 打爆 push 端是經典陷阱。

### push vs pull 的成本數學

| | Push(fan-out on write) | Pull(fan-out on read) |
|---|---|---|
| 機制 | 發文時就寫進每個粉絲的 feed(預先展開) | 讀 feed 時才去拉所有追蹤對象的最新貼文合併 |
| 成本落在 | **寫**(一次發文 → N 次寫,寫放大) | **讀**(一次讀 → 拉 M 個對象,讀放大) |
| 讀 latency | 極低(feed 已算好) | 高(即時聚合排序) |
| 適合 | 粉絲少、讀多寫少的普通用戶 | 追蹤對象多、或本身粉絲極多 |

具體數字推導:

```
普通用戶 A 有 200 粉絲,發 1 篇 → push 寫 200 次。可接受。
名人 B 有 5000 萬粉絲,發 1 篇 → push 要寫 5000 萬次!
  → 一次發文瞬間 5000 萬寫,feed 儲存被打爆、延遲爆炸 = celebrity problem
```

### hybrid 閾值(業界標準解)

- 普通用戶:**push**(讀便宜、粉絲少寫得起)。
- 超過某粉絲數閾值(如 >100 萬)的名人:**pull**——他們的貼文不 push,而是粉絲讀 feed 時「push 好的部分 + 即時拉名人最新貼文」合併。

閾值就是「push 的寫成本 開始 > pull 的讀成本」的交叉點。這是 Twitter 實際採用的混合策略。

### 既有材料

本 repo 的 feed 實作見 [../social-media-feed/README.md](../social-media-feed/README.md):用 Bull queue 做背景 feed 生成(即 fan-out on write 的非同步版本——發文丟 queue,worker 慢慢展開到粉絲 feed),Redis 快取 feed。把「fan-out 用背景佇列削峰」講出來會加分。

### 什麼題會用到

Twitter/FB/IG feed、通知系統(一個事件通知多人)、群組訊息(一則訊息送多人)、任何「一次寫入要擴散到多個接收端」的題。

### 面試高分要點

- 一定要用**數字**推 celebrity problem(200 vs 5000 萬),光說「名人有問題」不夠。
- hybrid 的閾值要能說出「交叉點在哪、為什麼」。
- push 用非同步佇列削峰(而非同步展開 N 份)是實務細節。
- 讀 feed 時「合併 push 好的 + pull 名人的」的混合讀路徑能講清楚 = senior 訊號。

---

## 8. Hot key / hot partition

> 一句話總結:即使分片均勻,單一超熱的 key(明星、爆紅商品、當紅 hashtag)還是會把它所在的節點打爆。要先**偵測**,再**打散或分流**。

### 偵測

- **Count-min sketch**(見 handling-unfamiliar §6):固定記憶體的機率型計數,犧牲一點精確度換「用極小記憶體找出高頻 key」,適合在十億級 key 流中即時抓熱點。
- 抽樣統計、access log 分析(離線)。
- 監控單 shard/單 key 的 QPS 突增告警。

### 緩解手段

| 手段 | 機制 | 適用 |
|---|---|---|
| **Local cache(本機快取)** | 熱 key 在每台 app 本機各存一份,讀不出網 | 讀極熱、可容忍短 TTL 舊值 |
| **Key 打散(sub-key)** | `hot_key` → `hot_key#0..#9` 分散到多 shard,寫隨機挑、讀聚合 | 熱 counter、熱寫入 |
| **專用通道 / 隔離** | 把已知熱 key(如首頁 banner、當紅商品)放獨立叢集,別跟一般流量搶 | 可預測的熱點 |
| **Read replica 擴散** | 熱讀 key 多開副本分攤讀 | 讀熱、寫不熱 |

打散(sub-key)與第 5 章 hot shard 的 sub-key 拆分是同一招,差別只在觸發原因(這裡是單 key 熱,那裡是 shard 熱)。

### 什麼題會用到

秒殺(爆品 hot row/key)、feed(明星貼文)、trending(當紅 hashtag)、任何有長尾 + 極端頭部分布的系統。

### 面試高分要點

- 主動說「hash 均勻不代表沒有 hot key」——這是很多人漏掉的盲點。
- 偵測提 count-min sketch,把它跟「機率型結構換記憶體」的 primitive 連起來。
- 緩解要分「熱讀」(local cache / replica)和「熱寫」(sub-key 打散)——這兩個解法不同。

---

## 9. Rate limiting 演算法

> 一句話總結:五種限流演算法在「精確度、記憶體、能否平滑突發」間取捨;分散式限流的難點是**跨機共享計數的原子性**(Redis + Lua)。

### 五種演算法對照

| 演算法 | 機制 | 精確度 | 記憶體 | 邊界問題 |
|---|---|---|---|---|
| **Fixed window** | 每固定窗口(每分鐘)一個計數器,滿了就拒 | 低 | 極小 | **邊界突刺**:窗口交界處可放進 2 倍量 |
| **Sliding log** | 記每個請求的 timestamp,算滑動窗口內筆數 | 最高(精確) | 大(存每筆) | 高流量下記憶體爆 |
| **Sliding window counter** | 用「當前窗口 + 前一窗口加權」近似滑動 | 高 | 小 | 近似,不 100% 精確 |
| **Token bucket** | 桶以固定速率補 token,來請求扣 token,桶可累積 | 高 | 小 | **允許突發**(桶滿時可一次消耗) |
| **Leaky bucket** | 請求進桶,以固定速率漏出,滿則丟 | 高 | 小 | **強制平滑**,不允許突發 |

**判準**:要允許短暫突發(API 大多如此)→ token bucket;要強制勻速(如寫入下游有硬上限)→ leaky bucket;要簡單且能容忍邊界誤差 → fixed/sliding window counter;要絕對精確且量不大 → sliding log。

token bucket vs leaky bucket 的核心差異:**token bucket 允許攢額度後爆發,leaky bucket 永遠勻速漏出**。

### 分散式實作:Redis + Lua 原子性

單機限流用記憶體計數器就好;多台 app 要共享限額,計數必須放共享儲存(Redis)。難點:「讀計數 → 判斷 → 加一」三步若非原子,高併發下會超放。解法:**Redis + Lua script**,把整段邏輯在 Redis 單執行緒內原子執行:

```lua
-- 偽碼:原子地檢查並遞增
local current = redis.call('INCR', key)
if current == 1 then redis.call('EXPIRE', key, window) end
if current > limit then return 0 else return 1 end
```

因為 Redis 單執行緒 + Lua 整段原子,不會有 race。這與第 2 章「原子操作下推」是同一個 primitive。

### 什麼題會用到

API gateway、防爬蟲/防刷、秒殺入口限流、通知發送限速、任何對外開放的 endpoint(見 [../url-shortener/README.md](../url-shortener/README.md) 的 IP-based limiting)。

### 面試高分要點

- token bucket vs leaky bucket 的「允許突發 vs 強制平滑」是必答對比。
- fixed window 的「邊界突刺」是常被問的坑,要能畫出來(窗口交界前後各塞滿 = 2 倍)。
- 分散式限流一定要提「計數共享 + 原子性(Redis Lua)」,否則答案不完整。
- 提「限流回 429 + Retry-After」,呼應第 10 章 backpressure。

---

## 10. 佇列與 backpressure

> 一句話總結:佇列的三大角色是削峰、解耦、序列化;但**無界佇列是謊言**——它只是把「拒絕」偷偷換成「延遲無限增長後一起崩」。backpressure 是誠實地把「我扛不住了」往上游傳。

### 佇列的三個角色

| 角色 | 機制 | 例子 |
|---|---|---|
| **削峰(buffering)** | 尖峰流量進佇列,下游按自己速度消化 | 秒殺請求進 queue,worker 慢慢扣庫存 |
| **解耦(decoupling)** | 生產者不直接呼叫消費者,靠佇列中介 | 發文 → queue → fan-out worker(第 7 章) |
| **序列化(ordering)** | 把併發變順序,單消費者依序處理 | 併發寫同一資源 → 佇列排隊(第 2 章 d) |

### 無界佇列是謊言

新手常以為「加個佇列就不會過載」。錯:**無界佇列(unbounded queue)是生產事故之王**(見 [../../docs/cs-fundamentals/networking-03-production-networking.md](../../docs/cs-fundamentals/networking-03-production-networking.md) backpressure 章)。下游消化不過來時,佇列無限長 → 記憶體吃光 OOM,或延遲一路飆到上游 timeout,最後**整條鏈一起死**,而且死得很慢很難查。佇列必須**有界**;滿了就要做決定:拒絕(shed load)還是阻塞上游。

### backpressure:誠實往上游傳

timeout / retry / circuit breaker 都是**上游(caller)自保**;backpressure 是**下游(callee)誠實說「我滿了」**的機制(見 networking-03 §backpressure)。本質兩件事:

1. **有界佇列**:滿了不再吞。
2. **明確拒絕訊號**:回 429(Too Many Requests),讓上游減速,而不是靜默吞進來。

健康系統過載時:429 上升,但 p99 latency **有上限**(shed load 生效)。壞系統:沒有 429,p99 一路飆到 client timeout(無界佇列在偷偷吞)。這是 networking-03 壓測劇本的判斷法。

backpressure 要能**逐層往上傳**:最下游滿 → 回 429 → 中層佇列也滿 → 也回 429 → 最上游減速。任何一層用無界佇列吞下來,這條反饋鏈就斷了。

### DLQ(Dead Letter Queue)

處理不了的訊息(格式錯、重試耗盡)不能無限卡在主佇列擋住後面,也不能直接丟掉。丟進 **DLQ** 隔離,之後人工/自動排查。這是佇列系統的標配安全閥。

### 什麼題會用到

秒殺(削峰)、fan-out(解耦)、任何 producer/consumer 速率不匹配、任何 LLM/影片轉檔等慢下游(backpressure)、任何 message queue(DLQ)。

### 面試高分要點

- 主動說「佇列要有界,無界佇列只是把過載延後成更難查的崩潰」——這句立刻顯示生產經驗。
- 講清楚 backpressure 是下游側機制,和上游的 timeout/retry/circuit breaker 是**互補的一整套**(見第 12 章)。
- 過載時「回 429 讓 p99 有上限」vs「延遲無限增長」的對比是高分句。
- 提 DLQ 顯示你想到了「毒訊息」不能阻塞主流程。

---

## 11. Geo-indexing 與 ID 生成(短章)

> 一句話總結:兩個高頻小題,推導已在 handling-unfamiliar,這裡補精確度/位元佈局的速查表。

### Geo-indexing(見 handling-unfamiliar §1)

核心推導:經緯度各建 B-tree 做二維範圍交集極慢 → 把二維壓成一維 key → 切格子,「附近」= 自己格 + 周圍八格 → 密的地方遞迴切四塊 = **quadtree**;格子 ID 用字串前綴表示、前綴越長格子越小 = **geohash**。

geohash precision 速查:

| geohash 長度 | 格子大小(約) | 用途 |
|---|---|---|
| 4 | ~40 km | 城市級 |
| 5 | ~5 km | 區域 |
| 6 | ~1.2 km | 鄰里(「附近餐廳」常用) |
| 7 | ~150 m | 街區 |
| 8 | ~40 m | 建物級 |

geohash 的好處:**共同前綴 = 地理相近**,可直接用字串前綴查詢做「附近」。陷阱:邊界效應(兩點很近但跨格 → 前綴不同),所以要查自己格 + 周圍八格。

### 分散式 ID 生成(見 handling-unfamiliar §2)

核心推導:auto-increment 單點、多 master 撞;UUID 隨機寫入 B-tree 造成 page split 且 128 bit 太肥 → 需求:全域唯一 + 大致遞增 + 機器間免協調 → **Snowflake**。

Snowflake 64-bit 佈局:

```
 0 | 41 bits timestamp | 10 bits machine id | 12 bits sequence
 ^        ^                     ^                    ^
 |    毫秒級時間戳         最多 1024 台機器      同毫秒內 4096 個序號
符號位   (可用 ~69 年)      (5 datacenter+5 worker)  (同機同毫秒不撞)
```

- **timestamp 在高位** → ID 大致遞增(B-tree 友善、append 寫入)。
- **machine id** → 機器間不用溝通就不撞。
- **sequence** → 同一毫秒同一機器可產 4096 個。
- 陷阱:**時鐘回撥**(NTP 校時往回跳)會產生重複 ID → 要偵測並等待/拒發。

### 什麼題會用到

Geo:Uber/Lyft 附近司機、Yelp 附近餐廳、外送、交友距離。ID:任何需要分散式唯一主鍵的題(貼文 ID、訂單 ID、短碼)。

### 面試高分要點

- geohash 講「共同前綴 = 相近」+「邊界效應要查九宮格」。
- Snowflake 講「timestamp 放高位是為了遞增、對 B-tree 友善」,並主動提「時鐘回撥」這個坑。

---

## 12. 可靠性三件套:timeout / retry / circuit breaker

> 一句話總結:這三個不是各自獨立的技巧,而是「面對下游變慢時系統怎麼不崩」的一整套;SD 面試講到「怎麼防雪崩」時,這是標準答案骨架。細節見 cs-fundamentals N3。

### 三件套 + backpressure 是一個系統

(完整機制見 [../../docs/cs-fundamentals/networking-03-production-networking.md](../../docs/cs-fundamentals/networking-03-production-networking.md) §「Timeout、retry、backpressure 作為一個系統」)

| 元件 | 位置 | 作用 | 關鍵設計 |
|---|---|---|---|
| **Timeout** | 上游 | 不無限等慢下游 | **分層設定,上游 timeout 要比下游長**(否則上游先放棄,下游白做) |
| **Retry** | 上游 | 重試暫時性失敗 | **前提是冪等**(第 4 章);要 **backoff + jitter**,否則變 retry storm |
| **Circuit breaker** | 上游 | 下游持續失敗時直接快速失敗,不再打它 | closed → open(連續失敗跳閘)→ half-open(試探)→ closed |
| **Backpressure** | 下游 | 誠實回「我滿了」(429) | 有界佇列 + 拒絕訊號(第 10 章) |

前三個是 caller 側自保,backpressure 是 callee 側自保,合起來才是完整的「防雪崩」故事:上游設好 timeout 不空等、retry 冪等且退避不放大流量、下游頂不住時斷路器跳閘 + backpressure 回壓,讓過載訊號傳回最上游減速。

### retry storm 陷阱

下游抖動一下 → 大家一起重試 → 流量瞬間翻倍 → 把剛要恢復的下游又打死 → 更多失敗 → 更多重試……**正回饋雪崩**。解法:backoff(每次重試間隔指數增長)+ jitter(加隨機,避免大家同步重試)+ circuit breaker(失敗夠多就別再試)。

### Graceful degradation 的分級

過載或部分故障時,不是「全好」或「全掛」,而是分級降級:

| 級別 | 做法 | 例子 |
|---|---|---|
| 完整服務 | 全功能 | 個人化推薦 feed |
| 降級 | 關掉貴的非核心功能 | 改回熱門排行(非個人化) |
| 唯讀 | 停寫保讀 | 只能看不能發文 |
| 靜態兜底 | 回快取/預設值 | 回上次快取的 feed |
| 明確失敗 | 回 429/503 + 友善訊息 | 「系統忙碌,稍後再試」 |

**核心價值**:讓使用者「用得差」遠勝於「全掛 + 錯誤頁」。降級路徑要事先設計,不是故障當下才想。

### 什麼題會用到

任何有下游依賴的題(幾乎全部)、微服務呼叫鏈、LLM/第三方 API 依賴、任何被問「某個服務掛了會怎樣」的追問。

### 面試高分要點

- 把四個元件講成「一整套防雪崩」,而不是四個孤立名詞——這是 senior 與背名詞的分界。
- timeout「上游要比下游長」、retry「必須冪等 + backoff+jitter」是最容易漏又最能加分的兩個細節。
- 主動講 graceful degradation 分級,顯示你設計時就想好了故障路徑。

---

## Pattern × 經典題對照矩陣

哪一題會用到哪些 pattern(數字對應章節)。橫軸是 pattern,縱軸是經典題:

| 經典題 | 1估算 | 2併發 | 3一致性 | 4冪等 | 5分片 | 6快取 | 7fanout | 8hotkey | 9限流 | 10佇列 | 11geo/id | 12可靠 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| URL shortener | ✓ | | ✓ | | ✓ | ✓ | | ✓ | ✓ | | ✓(id) | ✓ |
| Twitter/FB feed | ✓ | | ✓ | | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓(id) | ✓ |
| 秒殺/搶票 | ✓ | ✓ | ✓ | ✓ | | ✓ | | ✓ | ✓ | ✓ | | ✓ |
| 支付系統 | ✓ | ✓ | ✓ | ✓ | ✓ | | | | ✓ | ✓ | ✓(id) | ✓ |
| 聊天/IM | ✓ | | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ | ✓(id) | ✓ |
| Uber/附近的人 | ✓ | ✓ | ✓ | | ✓ | ✓ | | ✓ | ✓ | ✓ | ✓(geo) | ✓ |
| Typeahead 補全 | ✓ | | ✓ | | ✓ | ✓ | | ✓ | ✓ | | | ✓ |
| Google Docs 協作 | ✓ | ✓ | ✓ | ✓ | ✓ | | | | | ✓ | ✓(id) | ✓ |
| 通知系統 | ✓ | | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ | ✓(id) | ✓ |
| 觀看數/trending | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ | | ✓ | | ✓ |
| Ad click 統計 | ✓ | | ✓ | ✓ | ✓ | | | ✓ | | ✓ | | ✓ |
| Google Drive/存檔 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | | ✓ | ✓ | ✓(id) | ✓ |

觀察:**第 1(估算)、3(一致性)、12(可靠性)幾乎每題都用到**——這三個是無論什麼題都該主動帶到的通用骨架。第 7(fan-out)、11(geo)是題型專屬。

---

## 自測 checklist(面試前過一遍)

遮住答案,能對每題答出「機制 + 判準 + 一個坑」才算過關:

1. **估算**:給定 2 億 DAU、每人每天讀 20 次,峰值讀 QPS 大概多少?(推:40 億 / 10^5 × 3 ≈ 120K)
2. **併發**:什麼時候用樂觀鎖、什麼時候用悲觀鎖?判準是什麼?(衝突率)
3. **併發**:秒殺為什麼不能只靠 `SELECT FOR UPDATE`?終極解是什麼?(hot row;佇列序列化 / Redis 原子遞減)
4. **一致性**:read-your-writes 和 eventual 差在哪?各舉一個真實場景。
5. **一致性**:CAP 的正確講法?PACELC 補了什麼?(分區時 C/A;平時 latency/consistency)
6. **冪等**:為什麼說「沒有真正的 exactly-once」?怎麼做出效果上的 exactly-once?(at-least-once + dedup)
7. **冪等**:idempotency key 該由誰生成?為什麼?(client;重試沿用同一把)
8. **分片**:為什麼 `hash % N` 在擴容時是災難?consistent hashing 怎麼解?virtual node 又解決什麼?
9. **快取**:cache stampede 是什麼?講出兩種解法。(lock / logical expiry / jitter)
10. **fan-out**:celebrity problem 用數字說明,hybrid 閾值在哪個交叉點?
11. **限流**:token bucket vs leaky bucket 差在哪?分散式限流怎麼保證原子?(允許突發 vs 平滑;Redis Lua)
12. **可靠性**:timeout / retry / circuit breaker / backpressure 怎麼合成一套防雪崩?各自關鍵設計是什麼?

---

> 延伸:單題深入推導看 [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md);Lambda/Kappa 與一致性窗口看 [../dcard-interview.md](../dcard-interview.md);流式 exactly-once 看 [../data-intensive-app-flink/README.md](../data-intensive-app-flink/README.md);timeout/retry/backpressure 的機制細節與壓測劇本看 [../../docs/cs-fundamentals/networking-03-production-networking.md](../../docs/cs-fundamentals/networking-03-production-networking.md)。
