# System Design 面試:遇到不熟領域的應對與推導練習

> 核心結論:system design 考的是**推理過程**,不是知識背誦。遇到不熟的部分,那一刻就是考題本身。

## 一、現場應對策略(按優先順序)

### 1. 誠實 + 第一性原理推導(最重要)

直接說:「我沒有實際做過 X,但讓我從需求推推看。」這句話不會扣分,反而是 senior 的訊號——工作上本來就常要設計自己沒做過的系統。

### 2. 黑盒化,繼續前進

推不動時,把它抽象成一個元件:「這裡我需要一個 transcoding service,input 是原始影片、output 是多種格式的 segments,先假設它存在,把整體架構走完,有時間再回來深入。」面試官在意的是你**不會卡死**,會管理時間和 scope。

### 3. 把它變成對話

面試是 collaborative 的。可以問:「這一塊你希望我深入到什麼程度?」或「我對 X 的理解是這樣,如果有誤請糾正我。」接住面試官的提示往下推,比硬掰好看很多。

### 唯一會死的做法

**不懂裝懂、自信地講錯細節。**「我不確定,但我推測是…因為…」永遠比編造安全。

## 二、通用推導模板

1. **Naive 解法是什麼?**(單機、精確、同步、現算)
2. **哪個數字讓它爆掉?**(QPS、key 數量、同一 row 的競爭、二維查詢)
3. **需求哪裡有鬆動空間?**(能容忍誤差?能容忍延遲?讀寫比懸殊?)
4. **套對應的 primitive**:預計算、切格子/分片、機率型結構換記憶體、非同步化、心跳偵測、冪等 + 對帳。

## 三、推導範例集

> 練法:遮住推導鏈,只看題目自己推一次,推不動再看。目標是內化 primitive,不是背答案。

### 0. Video 編碼(YouTube)

不需要懂 H.264 內部:
- 影片很大 → 不能一次處理 → 切 chunk(segment)
- 使用者網速、裝置不同 → 同一支影片轉出多種解析度/bitrate → **adaptive bitrate streaming** 的由來
- 轉檔耗 CPU 且可平行 → async pipeline + message queue + worker pool
- 各 chunk 轉完要組合 → DAG 式處理流程

### 0b. Object storage 替代方案

先講需要的**性質**(存大 blob、便宜、高 durability、不需要 POSIX 語意、讀多寫少),再用排除法:
- 存 DB 當 BLOB?→ DB 貴、備份變慢、多餘的 transaction overhead → 排除
- 一般檔案系統 + 自己做 replication?→ 重新發明輪子 → 排除
- 自建(HDFS / Ceph / MinIO)vs 雲端(S3)→ 成本 vs 維運人力的 tradeoff

### 1. 附近的人/餐廳(Uber、Yelp)— Geo index

經緯度各建 B-tree,「範圍內」要做二維交集,效率極差 → 把二維壓成一維 key → 地圖切格子,格子 ID 當 key,「附近」= 自己格子 + 周圍八格 → 市中心一格幾萬家店、沙漠零家 → 密的地方遞迴切四塊 = **quadtree**;格子 ID 用字串表示、前綴越長格子越小 = **geohash**。

### 2. 分散式唯一 ID — Snowflake

auto-increment 是單點、多 master 會撞 → UUID 夠唯一但隨機寫入 B-tree 造成 page split、128 bit 太肥 → 需求:全域唯一、大致遞增、機器間不用溝通 → 時間戳(遞增)+ 機器 ID(不撞)+ 同毫秒序號 = **Snowflake**。

### 3. 搜尋自動補全(typeahead)

每 keystroke 打一次、latency <100ms → 不能現算 → 讀多寫少、不需即時 → 每個 prefix 的 top 10 **預先算好** → 查詢變 key lookup → prefix 大量共享 → 用樹共享節點 = **trie** → 熱門度每天 batch 重算。

### 4. Web crawler(Google)

本質是 BFS + 佇列 → 同 domain 狂打會打掛對方/被 ban → 按 domain 分隊列 + 延遲 = **politeness** → 大量鏡像頁 → content hash 去重 → 「URL 抓過沒?」百億級,精確 set 存不下 → 容忍極小誤判換記憶體 = **bloom filter**。

### 5. 聊天室在線狀態(presence)

斷網、殺 app 不會送「離線事件」→ 只能反做:client 每 30 秒**心跳**,超過 N 秒沒收到 = 離線 → 1000 個好友每次上下線都廣播太貴 → 只推給「正在看的人」= 訂閱制而非廣播制。

### 6. 熱門排行/Trending(Twitter)

精確統計十億級 key 記憶體爆 → 需求只要前 K 名、第 47 和 52 名搞混沒人在乎 → 容忍誤差 → 固定記憶體的機率型計數 = **count-min sketch** + heap 維護 top-K;或分片各算 local top-K 再合併。關鍵句:「犧牲精確度換固定記憶體,因為需求是排行榜不是帳單。」

### 7. 秒殺/搶票(庫存)

10 萬人 update 同一 row 的 `stock - 1` → 全部排隊等同一把 row lock = **hot row** → 方向:別讓流量碰 DB → 入口先隨機丟棄/排隊(99.9% 買不到)→ 庫存搬 Redis 原子遞減 → 非同步落帳 → 寧可少賣不能超賣 → 預扣 + 超時釋放。

### 8. 支付系統 — 冪等與對帳

扣款 API timeout,扣了沒?不知道 → 不重試漏單、重試可能重複扣 → 讓重試安全:唯一 **idempotency key**,看過就回上次結果 → 更深一層:分散式沒有真正 exactly-once,只有 at-least-once + 去重 → 最後要有每日**對帳(reconciliation)**當安全網。

### 9. 協同編輯(Google Docs)

整份文件 last-write-wins 會吃掉對方的字 → 改傳「操作」(insert at position 5)→ 並發時位置互相影響 → 收到對方操作要先轉換座標 = **OT**;或設計怎麼合併都收斂的資料結構 = **CRDT**。推到「operation-based + 處理並發順序」就及格。

### 10. 廣告點擊統計(ad click aggregation)

事件亂序、遲到 → 「這分鐘的 window 何時關?」→ 不能無限等 → 設最多等多久的水位線 = **watermark** → 這是錢,流式快但可能漏 → 每日 batch 重算修正 = **lambda architecture**(可串 dcard-interview-lambda 筆記)。

## 四、預防面:準備策略

不要試圖讀完所有系統,改成掌握 **~15 個 building blocks 的性質和 tradeoff**:LB、cache、CDN、message queue、object storage、SQL/NoSQL、search index、rate limiter、consistent hashing、CDC、stream processing…

幾乎所有題目都是積木的組合(YouTube = object storage + CDN + async pipeline + metadata DB)。真正的洞在於每個積木要能講出「什麼時候**不**用它」。
