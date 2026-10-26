# System Design 經典題地圖

> 這份文件的用法:每題先遮住答案,用 `naive 方案 → 哪裡爆 → 放寬什麼 → 對應 primitive` 的推導鏈自己走一次,推不動再看。
> 每題固定五格:**考什麼 / 核心決策點 / 必背數字 / 高頻追問 / repo 資源**。核心決策點一律用「選項 A vs B:判準」一行寫,面試現場你要能講出「什麼時候不選它」。
> 推導的原始鏈條在 [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md);跨題共用的 pattern 在 [cross-cutting-patterns.md](cross-cutting-patterns.md);檔尾有「題型 → pattern」對照表與自測 checklist。
> 讀者背景:DE/AI-Infra,面 Google L4 / Meta E4。技術名詞保留英文。

---

## 群組一:讀重寫輕(cache 與 ID 生成的主場)

這組的共同骨架:寫入量小、讀取量爆炸、資料幾乎不可變。核心永遠是「怎麼把讀路徑壓到一次 key lookup」+「ID/short code 怎麼生成不撞」。

### 1. Short URL(TinyURL / bit.ly)

**考什麼**:ID 生成策略的取捨(collision vs 協調成本)+ 讀重寫輕系統的 cache 分層。這題簡單,面試官真正在看你能不能把 estimation 和 cache 講乾淨。

**核心決策點**
- short code 生成:**hash(MD5 取前幾碼) vs 發號器(counter + Base62)**:判準——hash 要處理 collision(生成後查 DB 是否存在,撞了重算),counter 天生唯一但需要分散式發號;面試建議講 counter + Base62,順帶帶到 Snowflake / Redis `INCRBY` 分段發號。
- 儲存:**SQL vs KV(如 DynamoDB)**:判準——資料是單純 `code → url` 的 point lookup、無 join、需水平擴展 → KV 更順;但若要跑 analytics 聚合,metadata 放關聯式也可接受。
- 讀路徑:**每次查 DB vs 三層 cache(local LRU → Redis → DB)**:判準——301/302 redirect 是超高頻讀,熱門 code 遵循長尾,cache 命中率可到 95%+,不 cache 直接打 DB 會被讀垮。
- redirect 類型:**301(永久,可被瀏覽器/CDN 快取)vs 302(暫時,每次回源)**:判準——要收 analytics 就用 302 讓流量回到你的伺服器;不在乎點擊統計、只求最快就用 301。

**必背數字**(以「100M 新 URL/月」為基準的標準題設)
- 寫入:100M/月 ≈ 40 QPS 寫;讀寫比抓 100:1 → 讀 ≈ 4000 QPS。
- code 長度:Base62^7 ≈ 3.5 兆,Base62^6 ≈ 570 億;6~7 碼足夠用數十年。
- 儲存:每筆 ~500 bytes,100M/月 × 12 × 5 年 ≈ 60 億筆 ≈ 3 TB,不大,單一 sharded 叢集能扛。

**高頻追問**
- 「custom alias 怎麼做?」→ 用戶指定的 code 走「先查存在性再寫入」的路徑,和發號器分開;要處理 race(兩人搶同 alias)用 DB unique constraint 兜底。
- 「怎麼做過期刪除?」→ TTL 欄位 + 背景 job 掃描 / DB 原生 TTL index;熱資料在 Redis 設 TTL 自然淘汰。
- 「多資料中心怎麼發號不撞?」→ 每個 region 分不同的 counter 區段(range-based),或直接 Snowflake 把 machine ID 編進去。

**repo 資源**:[../url-shortener/README.md](../url-shortener/README.md) 有 Base62 encoding 實作、counter-based 生成 + collision fallback、三層 cache(in-memory → Redis → MongoDB)與 endpoint-specific rate limiting 的完整程式碼。

---

### 2. Pastebin

**考什麼**:和 Short URL 幾乎同構,差別在「payload 是大文字 blob 而非一條 URL」——考你會不會把 metadata 和 blob 分開存。

**核心決策點**
- blob 儲存:**存 DB TEXT 欄位 vs 存 object storage(S3),DB 只留 metadata + S3 key**:判準——貼文可達 MB 級,塞進 DB 會撐大 row、拖慢備份與 cache;大 blob 一律進 object storage。
- 讀取:**DB/S3 直讀 vs 前面掛 CDN**:判準——熱門 paste 被大量分享時,CDN 快取 blob 直接省掉回源。
- 過期:**惰性刪除(讀到才判斷) vs 背景 job 掃描**:判準——量小惰性即可,量大且需回收儲存成本才排 job。

**必背數字**:寫入量級與 Short URL 同級(~百萬/日);單篇上限通常設 1~10 MB;code 生成同 Base62 邏輯。

**高頻追問**
- 「private/加密 paste?」→ 內容在 client 端加密後才上傳,server 只存密文;或用不可猜的長 key 當能力憑證(capability URL)。
- 「怎麼防濫用貼惡意內容?」→ 上傳時過 content moderation、rate limit 寫入端。

**repo 資源**:無專案。骨架同 [../url-shortener/README.md](../url-shortener/README.md),把「short code → URL」換成「key → S3 blob」,再加一層 object storage 即可。

---

### 3. Typeahead / Autocomplete(搜尋自動補全)

**考什麼**:預計算 + trie 的經典推導,以及 top-k 排名怎麼離線算、線上查。這題最能展現「讀重寫輕 → 把運算搬到寫入/離線側」的思路。

**推導鏈**(house style,務必能自己走一遍):
每個 keystroke 就打一次、要求 latency < 100ms → **不能現算**排名 → 觀察需求:讀爆多、寫(熱門度變化)可以延遲、不需即時精確 → 把「每個 prefix 的 top-k」**離線預先算好** → 查詢退化成一次 key lookup → 但 prefix 之間大量共享前綴、逐 prefix 存 key 太浪費 → 用樹結構共享節點 = **trie**,每個節點掛它子樹的 top-k → 熱門度每天(或每小時)batch 重算,把新的 top-k 灌回 trie。

**核心決策點**
- 資料結構:**每個 prefix 存一個 Redis key vs trie 節點掛 top-k**:判準——prefix 數量爆炸且高度共享 → trie 省空間;但若 prefix 集合有限、追求極簡,直接 `prefix → top-k list` 的 KV 也行(工業界常這樣,trie 反而是白板題偏好)。
- top-k 來源:**即時統計 vs 離線 batch(MapReduce/Spark 跑近 N 天查詢日誌)**:判準——排名不需秒級新鮮,離線算完整且省線上資源;真要「幾分鐘內反映熱點」再疊一層 streaming 近似計數。
- 熱點計數:**精確 count vs count-min sketch 近似**:判準——十億級 query 精確統計記憶體爆,而「第 47 vs 52 名」沒人在乎 → 容忍誤差換固定記憶體。
- 個人化:**全域 top-k vs 混入個人歷史**:判準——個人化要在查詢時合併 user 特徵,latency 預算吃緊時先上全域、個人化當後續迭代。

**必背數字**
- latency 目標 < 100ms(含網路來回,實際運算預算 ~10ms)。
- 每次搜尋觸發 5~10 次 autocomplete 請求(逐字元),所以 autocomplete QPS ≈ 搜尋 QPS × 幾倍。
- top-k 通常 k = 5~10;trie 節點只存 top-k 而非全部後綴,才不會每個節點爆大。

**高頻追問**
- 「新熱詞(如突發事件)多久能出現?」→ 純離線 batch 有延遲,補一條 streaming pipeline 對近期查詢做近似計數,合併進結果。
- 「拼錯字 / 模糊匹配?」→ trie 上做 edit-distance 容錯,或加一層 fuzzy 索引(代價是 latency)。
- 「trie 太大單機放不下?」→ 依 prefix 首字母/雜湊 sharding 到多台,查詢路由到對應 shard。
- 「怎麼防止髒詞被補全?」→ 灌 trie 前過黑名單過濾。

**repo 資源**:無專案。推導原鏈見 [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md) 第三節(typeahead)與第六節(count-min sketch);本條目已把 trie + 離線 top-k + 近似計數補完整。

---

## 群組二:社交 / Feed(fan-out 與 presence 的主場)

這組的共同難點是 fan-out:一次寫入要擴散給大量讀者。核心決策永遠是 push(寫時擴散)vs pull(讀時聚合)vs 混合,以及 celebrity(超級節點)怎麼特判。

### 4. News Feed / Twitter Timeline

**考什麼**:fan-out on write vs on read 的取捨,以及 hot key(名人)怎麼破。這是社交題的母題。

**推導鏈**:naive 是每次刷 feed 就即時 join 你追蹤的所有人的貼文再排序 → follow 上千人時每次讀都要掃海量貼文、latency 爆 → 放寬「feed 可以有秒級延遲、可以最終一致」→ 改成**寫時擴散(fan-out on write)**:發文時就把 post ID 推進每個 follower 的 feed cache(Redis list)→ 讀變成一次 list 讀取 → 但名人發文要推給千萬 follower,一次寫入放大成千萬次 = **hot key / write amplification** → 對 celebrity 改回**讀時聚合(pull)**:一般人的貼文走 push,名人的貼文讀 feed 時才即時 merge 進來 = **混合方案**。

**核心決策點**
- 擴散時機:**fan-out on write(push)vs on read(pull)**:判準——寫少讀多、follower 數正常 → push(讀快);超級大 V → pull(避免寫放大)→ 實務混合。
- feed 儲存:**存 post ID list(輕,渲染時再撈內容) vs 存整份 post 快照**:判準——存 ID 省空間、內容改動好同步,但多一次 batch 撈;存快照讀最快但佔空間、更新麻煩。通常存 ID。
- 排序:**純時間序 vs ranked feed(ML 打分)**:判準——時間序簡單但參與度低;ranked 要離線算特徵 + 線上打分,latency 與複雜度都上升,面試先講時間序再說「可疊排名層」。
- 一致性:**強一致 vs 最終一致**:判準——feed 少一則、晚幾秒沒關係 → 最終一致換吞吐。

**必背數字**
- 假設 300M DAU、每人每天讀 feed 10 次 → 讀 ≈ 35K QPS(尖峰再 ×2~3)。
- 發文 ≈ 每人每天 0.2 篇 → 寫 ≈ 700 QPS;但一個名人 5000 萬 follower,一篇 push 就是 5000 萬次寫入,這就是 hot key 的來源。
- feed cache 每人存最近 ~800 條 post ID,每條 ~些 bytes;熱資料放 Redis,冷資料回 DB 重算。

**高頻追問**
- 「名人和普通用戶的界線怎麼定?」→ 設 follower 數門檻(如 > 10 萬走 pull),或動態依成本切換。
- 「怎麼保證 feed 不漏發也不重複?」→ 寫入端 idempotency + feed 去重(post ID 為 key)。
- 「多媒體貼文怎麼辦?」→ 圖片/影片走 object storage + CDN,feed 只存引用。

**repo 資源**:[../social-media-feed/README.md](../social-media-feed/README.md) 有 push/pull 混合、Bull queue 背景擴散、feed ranking 因子、多層 cache(in-memory / Redis / 預算 feed)與 Redis pub/sub 跨實例即時更新。

---

### 5. Chat / WhatsApp / Messenger

**考什麼**:長連線的維護與路由、訊息投遞保證(ordering + 不丟不重)、presence(在線狀態)。

**推導鏈**:naive 是 client 輪詢 DB 拿新訊息 → 即時性差、輪詢浪費 → 改**長連線(WebSocket)server 主動推** → 但用戶連在不同 server 上,A 發給 B,B 連在別台 → 需要一層知道「誰連在哪」的路由(session registry,存 Redis)+ 用 pub/sub 或訊息佇列把訊息投到正確的 server → 對方離線時訊息不能丟 → 進**持久化的 inbox / 訊息佇列**,上線後拉未讀 → presence 無法靠「離線事件」(斷網不會通知)→ 只能**心跳**反推。

**核心決策點**
- 傳輸:**WebSocket(長連線) vs long polling**:判準——高頻雙向、要 server push → WebSocket;環境有 proxy/firewall 限制的退路才用 long polling。
- 投遞保證:**at-most-once vs at-least-once + 去重**:判準——聊天不能丟訊息 → at-least-once,配 client 端 message ID 去重,做到不丟不重。
- 訊息儲存:**關聯式 vs 寬列(Cassandra/HBase,按 chat_id 分區、time 排序)**:判準——聊天是海量 append、按 conversation 讀最近 N 條 → 寬列/LSM 型存儲最合適。
- 群組擴散:**寫時展開(每人一份 inbox) vs 讀時聚合**:判準——小群寫時展開;超大群(廣播頻道)偏讀時聚合,避免寫放大——和 feed 同構。
- ordering:**全域順序 vs 每會話順序**:判準——只需每個 conversation 內有序,用單調序號/時間戳 per chat 即可,別追求跨會話全序。

**必背數字**
- 50M 併發連線,單機 WebSocket 撐 ~65K~100K 連線(記憶體是瓶頸,~256MB / 1 萬連線)→ 需數百到上千台接入層。
- 心跳每 ~30 秒一次;超過 N 秒(如 3 次)沒收到判離線。
- 訊息吞吐十萬~百萬級/秒,靠 Kafka 分區擴散。

**高頻追問**
- 「已讀回條 / 送達回條?」→ 額外的狀態事件回寫,更新訊息狀態(sent/delivered/read)。
- 「端到端加密?」→ client 端加密,server 只轉密文(Signal protocol),server 無法讀內容。
- 「presence 怎麼不把大量廣播打爆?」→ 只推給「正在看你」的訂閱者,而非所有好友(訂閱制而非廣播制)。
- 「多裝置同步?」→ 每裝置一個 session,訊息扇出到該用戶所有 active 裝置。

**repo 資源**:[../distributed-chat-system/README.md](../distributed-chat-system/README.md) 有 Socket.IO 多實例 + Redis session + Kafka 分區投遞 + MongoDB 持久化,涵蓋 presence、typing indicator、水平擴展。presence 心跳推導另見 [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md) 第五節。

---

### 6. Notification System(推播系統)

**考什麼**:多 channel 扇出(push/email/SMS/in-app)、投遞可靠性(retry + dedup)、user preference / rate limit / quiet hours 的策略層。

**推導鏈**:naive 是收到事件就同步呼叫各家 provider 發送 → provider 慢或掛就阻塞、失敗就丟 → 改**非同步**:事件進佇列,worker 消費後分 channel 投遞 → 第三方會 timeout/失敗 → 加 **retry + 指數退避 + DLQ(死信佇列)**;retry 可能重發 → 用 dedup key 做 at-least-once + 去重 → 用戶不想被打爆 → 加 **preference / rate limit / quiet hours** 策略層在投遞前過濾。

**核心決策點**
- 處理模型:**同步呼叫 provider vs 佇列 + worker 非同步**:判準——第三方不可靠且慢,一律非同步解耦。
- 投遞保證:**at-least-once + dedup vs exactly-once(不存在)**:判準——寧可靠 dedup key 去重,也不能漏發關鍵通知(如驗證碼)。
- 扇出時機:**發送當下逐一投遞 vs 依 channel 分別排隊**:判準——各 channel 速率限制、失敗模式不同 → 分 channel 佇列、各自 retry。
- template:**硬編碼 vs template engine + A/B**:判準——內容常變、要多語系與實驗 → 抽 template。

**必背數字**
- 大廠級可達 100M+ notifications/分鐘;靠 Kafka 分區 + 水平擴展 worker。
- rate limit 範例:push 每用戶每分鐘 ~10 則、SMS ~2 則(尊重 provider 限額也保護用戶)。
- retry 通常 3 次,退避間隔遞增;超過進 DLQ 人工處理。

**高頻追問**
- 「怎麼避免重複打擾(同事件多來源)?」→ dedup key(user + event + 時間窗)在投遞層去重。
- 「quiet hours 怎麼做?」→ 依用戶時區排程延後投遞,非緊急類才受限。
- 「provider 掛了怎麼辦?」→ 多 provider failover(如 FCM 掛切 APNS 的替代路徑),配 circuit breaker。
- 「怎麼追一則通知的下場?」→ 每則帶 ID,記錄 sent/delivered/failed,回寫 analytics。

**repo 資源**:[../notification-system/README.md](../notification-system/README.md) 有 Kafka 分區、多 channel(FCM/APNS/SES/Twilio/WebSocket)、template + A/B、per-user/per-channel rate limit、quiet hours、at-least-once + dedup、DLQ 與 analytics 的完整設計。

---

## 群組三:媒體(object storage + CDN + async pipeline 的主場)

這組的骨架都是:大 blob 進 object storage、靠 CDN 就近分發、上傳/轉檔走 async pipeline。差別在「點播 vs 直播」的延遲要求,以及推薦系統要不要。

### 7. YouTube(影片點播平台)

**考什麼**:上傳/轉檔 pipeline 的設計 + 大規模讀取靠 CDN + metadata 與 blob 分離。這題是「積木組合」的範本題:object storage + CDN + async pipeline + metadata DB。

**推導鏈**:影片檔很大、不能一次同步處理 → 上傳後**切 chunk / segment** → 用戶網速與裝置各異 → 同一支轉多種解析度/bitrate = **adaptive bitrate streaming(HLS/DASH)** → 轉檔耗 CPU 且可平行 → **async pipeline + message queue + worker pool**,各 chunk 獨立轉、轉完組回(DAG 式流程)→ 播放是超高頻讀、全球分布 → blob 放 **object storage** + 前面掛 **CDN** 就近快取 → metadata(標題、作者、統計)是結構化小資料,和影片 blob 分開存於 metadata DB。

**核心決策點**
- 上傳:**單次上傳 vs 分片 + resumable(斷點續傳)**:判準——大檔 + 網路不穩 → 必須分片可續傳,client 直傳 S3(pre-signed URL)不經過應用伺服器。
- 轉檔:**同步 vs async pipeline(queue + workers)**:判準——轉檔以分鐘計、可平行,一律非同步,上傳完先回「處理中」。
- 分發:**origin 直讀 vs CDN**:判準——熱門影片被海量觀看 → CDN 快取 segment,冷門長尾才回源。
- 儲存分層:**全放 SSD vs 熱在 CDN/SSD、冷轉低成本儲存**:判準——觀看極度長尾,冷影片轉 cold storage 省錢。
- metadata 存儲:**單體 SQL vs sharded**:判準——影片數與觀看數巨大,metadata 依 video_id sharding,計數走近似/非同步聚合。

**必背數字**
- 上傳 ~500 小時影片/分鐘(YouTube 級);轉檔算力是主要成本。
- 讀寫比極端(1 上傳 : 數千~百萬觀看)→ CDN 命中率決定成敗。
- 一支 1080p 影片依 codec ~數 GB;多 bitrate 版本讓儲存 ×3~5。
- segment 長度常 2~10 秒(短 segment 換更快的 bitrate 切換與更低直播延遲)。

**高頻追問**
- 「觀看數怎麼即時又準?」→ 即時用 Redis 近似計數 + 非同步 batch 校正(近似排行不需精確,見 count-min sketch)。
- 「熱門影片的 thumbnail / 前幾秒怎麼再加速?」→ 預熱 CDN、prefetch 首個 segment。
- 「怎麼防盜連 / DRM?」→ 簽章 URL(限時)、token 驗證、DRM 加密 segment。
- 「search / 推薦?」→ search 走倒排索引(Elasticsearch);推薦拆成獨立系統(見 Netflix)。

**repo 資源**:編碼與 async pipeline 推導見 [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md) 第 0 節(video 編碼)與第 0b 節(object storage 排除法);delivery / CDN / HLS 的實作見 [../live-streaming-platform/README.md](../live-streaming-platform/README.md)(直播與點播共用 CDN + ABR 骨架)。本條目已把兩者整合成完整敘事。

---

### 8. Netflix(串流 + 推薦)

**考什麼**:和 YouTube 共用串流骨架,但 Netflix 的重點在「內容庫固定 → 可預先轉檔並預佈 CDN」+ 推薦系統 + 即時互動通道(WebSocket vs SSE)。

**核心決策點**
- 內容佈署:**觀看時才轉/拉 vs 預先轉檔並 push 到邊緣(open connect)**:判準——內容庫有限且已知,離線把所有 bitrate 版本轉好、熱門片預佈到各 ISP 邊緣快取 → 播放零轉檔延遲。這是 Netflix 和 UGC(YouTube)最大的不同。
- 推薦計算:**線上即時算 vs 離線 batch 產生候選 + 線上輕排序**:判準——推薦特徵重、可離線;線上只做快速 re-rank 與情境調整(時段、裝置)。
- 即時通道:**WebSocket vs SSE**:判準——需雙向(用戶可取消 autoplay 倒數、主動要新推薦)→ WebSocket;只需 server 單向推(trending 更新、背景刷新首頁)→ SSE 更簡單、自動重連、走標準 HTTP 不易被擋。
- 互動事件收集:**同步阻塞 vs 背景非同步 track**:判準——點播放要立刻開始,user interaction 追蹤丟背景 task,不能阻塞播放。

**必背數字**
- 尖峰佔北美網路頻寬極高比例 → CDN/邊緣快取是命脈,靠自建 Open Connect 把 bytes 推到 ISP 機房。
- trending 計數用 Redis sorted set(`ZINCRBY`)即時累加(1~5ms),比 DB 聚合(100ms~2s)快兩個數量級。
- 互動事件量巨大 → 走 message queue + stream processing 聚合。

**高頻追問**
- 「推薦怎麼冷啟動(新用戶/新片)?」→ 靠熱門榜 + 內容相似(content-based)過渡到協同過濾。
- 「A/B 測試推薦演算法?」→ 流量切分 + 指標(觀看時長、完成率)離線比較。
- 「autoplay 倒數要能取消 → 為何非 WebSocket 不可?」→ 需要 client 主動送「取消」訊息回 server,SSE 是單向做不到。

**repo 資源**:[../streaming-recommendation-system/Q.md](../streaming-recommendation-system/Q.md) 有 WebSocket vs SSE 的詳細對照表與使用場景、互動事件何時觸發、trending 為何用 Redis;架構全貌見 [../streaming-recommendation-system/README.md](../streaming-recommendation-system/README.md) 與 [../streaming-recommendation-system/Netflix-Recommendation-System-Architecture-Note.md](../streaming-recommendation-system/Netflix-Recommendation-System-Architecture-Note.md)。串流本身骨架見 YouTube 條目。

---

### 9. Live Streaming / Twitch(直播)

**考什麼**:和點播的關鍵差異是「延遲」——直播要秒級甚至次秒級,不能像點播那樣慢慢轉。外加超大並發聊天室(fan-out 的另一形態)。

**核心決策點**
- 攝取:**RTMP(通用、延遲數秒) vs WebRTC(次秒級)**:判準——一般直播 RTMP 進、HLS/DASH 出;要次秒級互動(如視訊通話、拍賣)才上 WebRTC,代價是複雜度與規模成本。
- 轉檔:**離線多版本 vs 即時 realtime transcoding**:判準——直播沒有「離線」,必須邊收邊轉多 bitrate,吃硬體編碼(NVENC 等)。
- segment 長度:**長 segment(省開銷、延遲高) vs 短 segment / LL-HLS(低延遲、開銷大)**:判準——要壓延遲就縮短 segment;能容忍幾秒延遲就用一般 HLS 省成本。
- 聊天室:**單機廣播 vs 依 stream key sharding + Redis pub/sub 扇出**:判準——單一熱門直播 10 萬+ 同時聊天 → 必須分片並用 pub/sub 跨實例廣播,配 rate limit 防洗版。

**必背數字**
- 延遲:HLS/DASH 2~5 秒,WebRTC < 1 秒。
- CDN edge 快取 live segment 只需 ~10 秒 TTL(內容一直變)。
- 熱門直播並發觀看可達千萬級;單一聊天室 10 萬+ 用戶、訊息可達每秒數十萬。

**高頻追問**
- 「直播結束轉點播(VOD)?」→ 把 segment 存檔重新打包成 VOD,轉入 YouTube 式點播路徑。
- 「觀看數即時統計?」→ 邊緣上報 + 近似聚合,不逐一精算。
- 「主播端網路抖動?」→ client 端 adaptive bitrate 上行 + server 端 buffer 吸收。

**repo 資源**:[../live-streaming-platform/README.md](../live-streaming-platform/README.md) 有 RTMP 攝取 + FFmpeg 多 bitrate 轉檔 + HLS/DASH/WebRTC 分發 + 依 stream key 分片的聊天(10 萬+/室)+ CDN edge 策略 + 自動擴縮的完整設計。

---

## 群組四:Geo(把二維查詢壓成一維 key 的主場)

這組的核心 primitive 是 geo-indexing:「附近」這種二維範圍查詢,對經緯度各建 B-tree 做交集效率極差,一律靠切格子壓成一維 key。差別在 marketplace 的撮合複雜度。

### 10. Uber / Lyft(叫車)

**考什麼**:即時 geo 撮合(driver ↔ rider)、高頻位置更新的寫入、供需狀態的即時性。

**推導鏈**:「找附近司機」對 lat/lng 各建 B-tree 做二維交集 → 極慢 → 把二維壓成一維:地圖切格子,格子 ID 當 key,「附近」= 自己格子 + 周圍八格 → 市中心一格上萬車、沙漠零車 → 密的地方遞迴切四塊 = **quadtree**;前綴越長格子越小 = **geohash**(Redis `GEOADD`/`GEORADIUS` 直接支援)→ 司機每 5~10 秒回報位置 → 高頻寫入不能每次落盤 → 位置放 Redis(記憶體 + geo 索引),歷史軌跡進 time-series DB。

**核心決策點**
- geo 索引:**geohash(Redis GEO) vs quadtree vs S2/H3**:判準——均勻分布用 geohash 最省事;分布極不均、要動態調整格子密度用 quadtree;要更漂亮的球面分割用 S2/H3。面試講 geohash + 周圍格,提一句 quadtree 應對熱區即可。
- 位置儲存:**每次寫 DB vs 寫 Redis(即時)+ 非同步落 time-series**:判準——5 萬次/秒的位置更新打 DB 會爆 → 即時態放記憶體,歷史另存。
- 撮合:**最近距離 vs 多因子打分(距離/ETA/評分/車型)**:判準——單純最近會忽略 ETA(直線近但被河隔開)與司機意願 → 用打分排序,距離為主 + ETA/評分加權。
- 撮合觸發:**廣播給範圍內所有司機搶單 vs 系統指派**:判準——指派可全域最佳化(減少空駛)但要快;搶單簡單但體驗差。多數用系統指派 + 逾時 re-match。

**必背數字**
- 100K+ 併發用戶;位置更新 ~50K/秒;撮合延遲目標 < 500ms。
- 位置回報間隔 5~10 秒;單機 WebSocket ~1 萬連線。
- 格子大小依城市密度調,常見 geohash precision 5~6(~數公里到數百公尺)。

**高頻追問**
- 「動態定價(surge)?」→ 依格子內供需比即時算倍率,供需資料本就在 Redis geo 索引裡。
- 「司機在格子邊界怎麼辦?」→ 一定要查周圍八格(3×3),否則邊界漏司機。
- 「ETA 怎麼算?」→ 呼叫路網服務(考慮路況),不是直線距離;可 ML 預測。
- 「跨城市 / 全球擴展?」→ 依地理 region sharding,格子 key 天然可分區。

**repo 資源**:[../ride-sharing-system/README.md](../ride-sharing-system/README.md) 有 Redis GeoHash 撮合、多因子打分(距離 40% / ETA 25% / 評分 20% / 經驗 10% / 車型 5%)、InfluxDB 位置時序、WebSocket 即時通訊與 trip 生命週期。geo 推導原鏈見 [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md) 第一節。

---

### 11. UberEats / DoorDash(外送)

**考什麼**:三方 marketplace(顧客 / 餐廳 / 外送員)的訂單狀態機、餐廳庫存、dispatch 與 ETA。比 Uber 多一個角色和一個「備餐」的時間耦合,這是它和叫車最大的差異。

**和 Uber 的關鍵差異**(面試務必主動點出):
- Uber 是「兩方即時撮合、一段行程」;外送是「三方、兩段耦合」:顧客下單 → 餐廳接單備餐 → 外送員取餐 → 送達,dispatch 時機要抓「餐快好」才派人,派太早外送員空等、太晚餐涼了。
- 多了 **restaurant inventory / 菜單可用性**:菜賣完、餐廳打烊要即時反映,顧客下單瞬間要校驗。
- 多了**訂單狀態機**:placed → confirmed → preparing → ready → picked_up → delivered,每個轉移要可靠、可追、可補償(餐廳拒單、外送員取消要 rollback)。

**核心決策點**
- dispatch 時機:**下單即派 vs 依預估備餐完成時間延後派**:判準——要最小化「外送員等餐 + 餐等外送員」的總浪費 → 用備餐 ETA 反推派單時機。
- 撮合對象:**只看距離 vs 看「取餐點 → 送達點」的整段路徑 + 順路併單(batching)**:判準——外送可一趟送多單(同方向)降成本 → 要做 route-aware 的批次撮合,比 Uber 複雜。
- 訂單狀態:**單表狀態欄位 vs 顯式狀態機 + 事件溯源**:判準——多方、多步、要補償 → 用狀態機 + 事件記錄,方便對帳與客訴回溯。
- 庫存校驗:**下單後才查 vs 加入購物車即鎖定/校驗**:判準——熱門餐廳尖峰售罄快 → 下單瞬間要對庫存做原子校驗,避免超賣(和 flash sale 同源,但競爭沒那麼極端)。

**必背數字**
- 訂單量級遠低於位置更新(下單是低頻寫、狀態查詢是中頻讀)。
- ETA 準確度是核心體驗指標,誤差要壓在數分鐘內。
- 尖峰(午餐/晚餐)供需極不均,dispatch 與定價要動態應對。

**高頻追問**
- 「ETA 怎麼估?」→ 備餐時間(歷史 + 餐廳當前負載)+ 取餐路程 + 送達路程,ML 綜合預測,比 Uber 多「備餐」這段不確定性。
- 「餐廳拒單 / 缺料怎麼補償?」→ 狀態機觸發退款 + 重新推薦,saga 式補償。
- 「併單(一個外送員多訂單)怎麼決策?」→ 同區、同方向、時間窗相近才併,權衡準時率與效率。
- 「顧客即時追蹤外送員?」→ 復用 Uber 的即時位置推送(WebSocket + geo)。

**repo 資源**:無專案。即時位置與 geo 撮合可借 [../ride-sharing-system/README.md](../ride-sharing-system/README.md);訂單狀態機的可靠轉移與補償見交易類的 saga(本檔群組六 Payment 條目)。本條目已把三方 marketplace 的差異點寫足。

---

### 12. Yelp / 附近餐廳(proximity service)

**考什麼**:純讀的 geo 查詢——和 Uber 共用 geo-indexing,但沒有即時撮合、資料相對靜態,重點在「範圍查詢 + 過濾排序」。

**核心決策點**
- 索引:**geohash / quadtree 預建索引 vs 每次掃 DB 算距離**:判準——店家位置靜態、讀多寫少 → 預建 geo 索引,查詢 = 取自己 + 周圍格再過濾。
- 儲存:**關聯式 + geo 擴充(PostGIS) vs 專用 geo 索引 + search engine(Elasticsearch geo query)**:判準——要多條件過濾(評分、營業中、菜系)+ 全文搜尋 → Elasticsearch 的 geo + filter 一次搞定。
- 更新:**即時 vs 批次**:判準——店家資訊變動慢,批次重建索引即可。

**必背數字**:讀 QPS 高、寫極低;結果集通常 top-N(20~50 家)分頁;格子精度依「附近」定義(1~5 公里)。

**高頻追問**
- 「怎麼同時按距離和評分排序?」→ 先用 geo 縮小候選集,再在候選集上多因子排序(不能反過來全表排序)。
- 「熱門商圈查詢很集中怎麼辦?」→ 熱門格子結果快取。

**repo 資源**:無專案。geo 索引骨架同 [../ride-sharing-system/README.md](../ride-sharing-system/README.md)(去掉撮合與即時位置,只留範圍查詢),推導見 [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md) 第一節。

---

## 群組五:儲存 / 協作(chunking、delta sync、衝突解決的主場)

### 13. Dropbox / Google Drive(檔案同步)

**考什麼**:大檔的 chunking 與去重、增量同步(delta sync)、多裝置的衝突解決、metadata 與 blob 分離。

**推導鏈**:naive 是改一個字就重傳整個檔 → 大檔浪費頻寬 → 把檔案**切 chunk**(固定或內容定義切塊 CDC)→ 只傳變動的 chunk = **delta sync** → 相同 chunk 不必重存 → 用 chunk 的 hash 當 key **去重(dedup)** → 多裝置同時改同一檔 → 需要**衝突偵測**:用版本向量 / revision,衝突時保留兩版(conflicted copy)而非默默覆蓋 → metadata(檔案樹、版本、權限)是結構化小資料,和 chunk blob 分開存。

**核心決策點**
- 切塊:**固定大小 chunk vs content-defined chunking(CDC)**:判準——固定簡單,但檔頭插一個 byte 會讓後續所有 chunk 位移、去重失效 → 對頻繁編輯的檔用 CDC(依內容找切點,插入只影響鄰近 chunk)。
- 同步:**全量比對 vs 只傳變動 chunk 的 delta sync**:判準——大檔小改動 → 一定要 delta,靠 chunk hash 比對出差異集。
- 衝突:**last-write-wins vs 保留衝突版本 / 版本向量**:判準——檔案同步不能默默吃掉對方修改 → 偵測到並發修改就產生 conflicted copy 交給用戶,或對可合併類型做 merge。
- blob 儲存:**自建 vs object storage(S3)**:判準——chunk 是大 blob、讀多寫少、要高 durability → object storage;metadata 走關聯式 DB。
- 上傳路徑:**經應用伺服器中轉 vs client 直傳 object storage(pre-signed URL)**:判準——大檔中轉浪費頻寬與伺服器資源 → 直傳,伺服器只發簽章與記 metadata。

**必背數字**
- 常見 chunk 大小 4MB(權衡去重粒度與 metadata 開銷)。
- chunk hash 用 SHA-256 當去重 key。
- metadata 操作(列目錄、查版本)是高頻讀 → 要 cache;chunk 傳輸是頻寬密集。

**高頻追問**
- 「怎麼做到近即時同步而不狂輪詢?」→ 長連線 / 通知通道推「有變更」,client 收到再拉 delta。
- 「跨裝置怎麼知道哪些 chunk 已存在(省上傳)?」→ 上傳前先送 chunk hash 清單問 server,只傳缺的(dedup at source)。
- 「大量小檔?」→ 打包減少 metadata 與請求開銷。
- 「離線編輯後上線?」→ 本地記 pending 操作,上線後同步並跑衝突偵測。

**repo 資源**:[../google-drive-clone/README.md](../google-drive-clone/README.md) 有 S3/MinIO blob 儲存、PostgreSQL metadata、checksum 去重、版本控制、軟刪除與權限分享(read/write/admin)。專案較淺;chunking / delta sync / CDC / 衝突解決本條目已補足。

---

### 14. Google Docs(協同編輯)

**考什麼**:並發編輯的收斂——OT vs CRDT。這是「一致性」在協作場景的極致版本。

**推導鏈**:naive 是整份文件 last-write-wins → 對方的字被吃掉 → 改傳「操作」(insert "x" at position 5)而非整份 → 兩人同時編輯,position 會互相影響(你在我前面插了字,我的 position 就偏了)→ 收到對方操作前要先**轉換座標** = **Operational Transform(OT)**;或設計「不管以什麼順序合併都收斂」的資料結構 = **CRDT**。推到「operation-based + 處理並發順序」就及格。

**核心決策點**
- 收斂機制:**OT vs CRDT**:判準——OT 需要中央 server 定序、實作轉換函式複雜但 metadata 輕(Google Docs 用);CRDT 每個字元帶唯一 ID、天然可去中心/離線合併,但 metadata 較肥。要中央協調且省空間選 OT,要 P2P/離線優先選 CRDT。
- 傳輸:**每次改都送 vs 批次/節流**:判準——逐鍵送太吵 → 節流成批 + 即時性平衡。
- 儲存:**存每個 operation(可重播、可還原歷史) vs 只存快照**:判準——要版本歷史與協作審計 → 存 operation log + 定期快照(避免重播過長)。
- 游標/presence:**廣播全部 vs 只推同文件協作者**:判準——只推正在編輯同文件的人,和 chat presence 同理。

**必背數字**
- 單文件同時編輯者通常個位數到數十;瓶頸不是規模而是**正確性**(收斂)。
- operation log 定期壓縮成快照,避免無限增長。

**高頻追問**
- 「離線編輯回來怎麼合併?」→ CRDT 天然支援;OT 要把離線期間的 operation 依序 transform 進來。
- 「怎麼保證所有 client 最終看到一致內容?」→ OT 靠 server 統一定序後廣播轉換後的操作;CRDT 靠合併運算的交換律/結合律/冪等性。
- 「大文件效能?」→ 分段(按段落/區塊)降低單次轉換範圍。

**repo 資源**:[../google-docs-clone/README.md](../google-docs-clone/README.md) 有 OT 實作(insert/delete/retain + transform 函式)、revision 同步、WebSocket 協作通道、游標追蹤與留言。OT/CRDT 推導原鏈見 [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md) 第九節。

---

## 群組六:交易類(idempotency、ledger、hot row 的主場——最大缺口,寫最深)

這組是 DE/AI-Infra 面試的高價值題:錢不能算錯、不能重複扣、不能超賣。核心 primitive 是 idempotency、不可變 ledger、對帳,以及 hot row 的三層破法。

### 15. Payment System(支付系統)

**考什麼**:分散式下「錢的正確性」——冪等、對帳、狀態一致。這題答得好,直接證明你懂 exactly-once 的真相與資料一致性底層。

**推導鏈**:扣款 API timeout,到底扣了沒?不知道 → 不重試怕漏單,重試怕重複扣 → 讓重試安全:每筆交易帶唯一 **idempotency key**,server 看過就回上次結果(不重複執行)→ 更深一層:分散式沒有真正的 exactly-once,只有 **at-least-once + 去重** → 帳務要能追、不能被竄改 → 用**不可變的 double-entry ledger**(每筆記借貸兩方,只 append 不 update)→ 和第三方 PSP(Stripe 等)之間還是可能狀態不一致 → 最後必須有每日 **reconciliation(對帳)** 當安全網,比對內部帳與 PSP 帳。

**核心決策點**
- 冪等:**應用層自己去重 vs idempotency key + 去重表(唯一鍵約束)**:判準——所有寫入型金流 API 都要吃 client 傳的 idempotency key,存去重表,重送直接回上次結果。這是不可省的。
- 帳務模型:**可變餘額欄位(update balance) vs 不可變 double-entry ledger(append entries,餘額由加總得出)**:判準——直接改餘額無法審計、出錯無法回溯、並發改同一 row 有競爭 → 用 append-only ledger:每筆交易寫借貸兩條 entry,任何時刻餘額 = 該帳戶 entries 加總。不可變是為了可審計與可對帳。
- 跨服務一致性:**2PC vs saga**:判準——2PC 有協調者單點、鎖資源久、跨異質服務難落地 → 長流程金流(下單→扣款→出貨)用 **saga**:每步有補償動作,失敗就反向補償;只有同一資料庫內的強一致才考慮短交易/2PC。
- PSP webhook:**假設 exactly-once vs 當 at-least-once 處理**:判準——PSP 的 webhook 會重送、會亂序 → 必須冪等消費(用事件 ID 去重)+ 容忍亂序(以最終狀態為準)。
- 對帳:**信任即時流程 vs 每日 reconciliation 兜底**:判準——即時流程再嚴謹也會有邊界失敗(timeout、部分成功)→ 對帳不是可選項,是必須存在的安全網,抓出內外帳差異人工/自動修補。

**必背數字**
- 金流寫入相對低頻(相較讀),但每筆都要強保證,不能為吞吐犧牲正確性。
- idempotency key 去重表要設保留窗(如 24h~數天)覆蓋所有重試場景。
- 對帳週期通常每日(T+1),差異進例外佇列處理。

**高頻追問**
- 「為什麼 double-entry 一定要不可變?」→ 可變會讓歷史不可稽核、並發更新有 lost update、出錯無法定位;append-only + 加總天然可審計、可重算。
- 「webhook 重送導致重複入帳?」→ 用 PSP 事件 ID 當去重鍵,消費前查去重表。
- 「saga 中途失敗,錢卡在中間狀態?」→ 每步定義補償(退款、釋放),配合對帳掃描卡住的交易。
- 「怎麼防 double spending / 餘額算錯?」→ 扣款前在 ledger 上做原子檢查(餘額加總 ≥ 扣款額),用交易隔離或樂觀鎖 + 冪等。

**repo 資源**:無專案。idempotency + 對帳推導原鏈見 [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md) 第八節;本條目已寫成小型完整設計(idempotency key / 不可變 double-entry ledger / PSP webhook 的 at-least-once 消費 / saga vs 2PC / reconciliation)。

---

### 16. Ticket Booking / Flash Sale(訂票 / 秒殺)

**考什麼**:hot row 競爭下的「不超賣」——同一庫存被海量請求爭搶時的三層破法,以及 seat hold + TTL。

**推導鏈**:10 萬人同時 `UPDATE stock = stock - 1` 打同一 row → 全部排隊等同一把 row lock = **hot row**,DB 被鎖死 → 方向是「別讓流量都碰到 DB 同一 row」→ 三層遞進:(1) 入口先用**排隊/隨機丟棄**削峰(99.9% 註定買不到,先擋在門外);(2) 庫存搬到 **Redis 原子遞減**(`DECR`,單執行緒天然序列化,毫秒級),扣成功才放行;(3) 用**佇列序列化**把下單請求串成單一有序流,非同步落 DB。訂票另有「選了座位還沒付款」→ **seat hold + TTL**:先鎖座位設過期時間,逾時未付自動釋放。原則:寧可少賣不可超賣。

**核心決策點**
- 扣減層級:**DB 悲觀鎖 vs Redis 原子扣減 vs 佇列序列化**:判準——競爭低用 DB 樂觀鎖(version 欄位)即可;競爭高(秒殺)必須把庫存搬 Redis 原子扣減;極端熱點再加佇列把請求序列化。三層按競爭強度遞進選用。
- 削峰:**全部放進來 vs 入口排隊 / 令牌**:判準——供遠小於求時,先在入口發放資格(排隊號 / 令牌桶)擋掉絕大多數,別讓它們碰到庫存邏輯。
- 座位保留:**下單即扣 vs seat hold + TTL(預扣 + 逾時釋放)**:判準——訂票有「選位→付款」的時間差 → 先 hold 設 TTL,付款成功才真扣,逾時自動釋放,避免座位被卡死也避免超賣。
- 落帳:**同步寫 DB vs Redis 扣成功後非同步落 DB**:判準——同步落 DB 會把 hot row 問題搬回來 → Redis 為真相源,非同步持久化,配對帳校正。

**必背數字**
- 秒殺瞬時 QPS 可達數十萬~百萬,但真實庫存可能只有數千 → 削峰比例極高(99%+ 被擋)。
- Redis 單執行緒原子操作 ~10 萬+ ops/秒,足以當庫存序列化點。
- seat hold TTL 常設 5~15 分鐘(付款時間窗)。

**高頻追問**
- 「Redis 扣成功但落 DB 失敗?」→ 以 Redis 為準 + 非同步重試 + 對帳修補;或用可靠佇列保證最終落地。
- 「怎麼絕對不超賣?」→ 原子扣減是唯一真相源,DB 只是投影;寧可少賣(扣成功沒付款則釋放)。
- 「防機器人搶票?」→ 入口 rate limit + 驗證碼 + 資格審核。
- 「Redis 掛了?」→ 主從 + 持久化;切換期間寧可拒絕下單(fail closed)也不超賣。

**repo 資源**:無專案。hot row / 秒殺推導原鏈見 [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md) 第七節;本條目已把三層破法與 seat hold + TTL 寫足。

---

## 群組七:基礎設施題(演算法對照與分散式協調的主場)

### 17. Rate Limiter(限流器)

**考什麼**:四種限流演算法的取捨,以及分散式版怎麼跨節點共享狀態、怎麼處理 race condition。

**四種演算法對照**

| 演算法 | 原理 | 優點 | 缺點 |
|---|---|---|---|
| Fixed window | 每固定時間窗計數,超額拒絕 | 實作最簡單、記憶體小 | 窗邊界可瞬間放行 2 倍(邊界突刺) |
| Sliding window log | 記錄每次請求時間戳,算滑動窗內數量 | 精確 | 存所有時間戳,記憶體大 |
| Sliding window counter | 用前一窗 + 當前窗加權近似滑動 | 近似精確 + 記憶體小 | 有輕微誤差 |
| Token bucket | 桶以固定速率補 token,請求耗 token | 允許突發(burst)、平滑 | 參數(容量/補速)要調 |
| Leaky bucket | 請求進桶、以固定速率漏出 | 輸出絕對平滑 | 不允許突發、可能排隊延遲 |

**核心決策點**
- 演算法:**fixed window vs sliding window vs token bucket**:判準——要簡單且能容忍邊界突刺 → fixed;要平滑且允許合理突發 → token bucket(最常用);要精確且省記憶體 → sliding window counter。
- 狀態位置:**單機記憶體 vs 集中式 Redis**:判準——多實例部署下每台各算會讓實際限額 × 台數 → 用 Redis 集中計數才準。
- 原子性:**GET 後 SET(有 race) vs Redis 原子操作 / Lua 腳本**:判準——併發下讀-改-寫會 race 導致超額 → 用 `INCR` + `EXPIRE` 原子化,或 Lua 腳本把判斷+扣減包成一個原子操作。
- 限流維度:**per-IP vs per-user vs per-API-key**:判準——防匿名濫用用 IP,對登入用戶用 user ID,對 API 服務用 key;常多層疊加。

**必背數字**
- 限流判斷要極快(< 1ms),放在請求最前端(gateway / middleware)。
- Redis 計數 key 帶 TTL(等於窗長),自動過期回收。
- 突刺容忍:fixed window 最壞可放行 2× limit(兩窗交界)。

**高頻追問**
- 「分散式下怎麼避免 race?」→ Redis Lua 腳本原子化「檢查 + 扣減」,或 `INCR` 回傳值判斷。
- 「Redis 成為瓶頸 / 單點?」→ 按 key sharding、本地先做粗略預算(local + 定期同步)、Redis 叢集。
- 「超額後怎麼回應?」→ 回 429 + `Retry-After` header,讓 client 退避。

**repo 資源**:無專案。實作範例散見各專案(如 [../url-shortener/README.md](../url-shortener/README.md) 的 endpoint-specific rate limit、[../notification-system/README.md](../notification-system/README.md) 的 per-user/per-channel 限流)。本條目已把四演算法對照與分散式版寫足。

---

### 18. Web Crawler(網路爬蟲)

**考什麼**:大規模 BFS 的工程化——politeness、去重、frontier 管理、陷阱處理。

**推導鏈**:本質是 URL 圖上的 BFS + 佇列 → 對同一 domain 狂打會打掛對方或被 ban → 按 domain 分隊列 + 加延遲 = **politeness**(尊重 robots.txt + crawl-delay)→ 大量鏡像/重複頁面 → 對內容算 hash 去重 → 「這 URL 抓過沒?」百億級,精確 set 存不下 → 容忍極小誤判換記憶體 = **bloom filter** → 待抓佇列(**frontier**)要能區分優先級、避免被單一 domain 塞爆 → 遇到動態生成的無限連結(日曆、search 頁)= **crawler trap** → 限制深度 / 偵測模式跳出。

**核心決策點**
- URL 去重:**精確 set vs bloom filter**:判準——URL 數達百億、精確 set 記憶體爆,而偶爾漏抓一頁可接受 → bloom filter 換固定記憶體。
- frontier 排程:**單一全域佇列 vs 依 domain 分隊 + 優先級**:判準——單一佇列會讓熱門 domain 霸佔且違反 politeness → 依 host 分隊,各隊有延遲,再疊優先級(重要頁先抓)。
- 內容去重:**URL 去重就好 vs 再對內容算 hash**:判準——不同 URL 可能同內容(鏡像) → 加 content hash(如 SimHash 抓近似重複)。
- 分散式:**單機 vs 多機依 URL hash 分片**:判準——規模一大必須分散,依 domain/URL hash 分片,注意同 domain 盡量落同節點以維持 politeness。

**必背數字**
- 網頁規模數百億~兆級;bloom filter 以極小誤判率(如 0.1%)大幅省記憶體。
- politeness delay 常數秒/同 domain;整體吞吐靠橫向擴展 worker。
- 重抓頻率依頁面更新率調(新聞高頻、靜態頁低頻)。

**高頻追問**
- 「怎麼尊重 robots.txt?」→ 每 domain 先抓並快取 robots，據以過濾與定 crawl-delay。
- 「crawler trap / 無限空間?」→ 限制 URL 深度與單 domain 頁數上限,偵測 URL 模式重複。
- 「怎麼保證新鮮度?」→ 依頁面歷史更新率排定重抓優先級。
- 「bloom filter 誤判(誤判已抓)漏頁?」→ 可接受;或用分層(bloom 前置 + 精確存熱門)。

**repo 資源**:無專案。politeness / frontier / bloom filter / trap 推導原鏈見 [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md) 第四節;本條目已補完整。

---

### 19. Distributed Job Scheduler(分散式排程 / 延遲任務)

**考什麼**:定時/延遲任務的可靠觸發——delay queue、exactly-once 觸發的近似、cron 分片。短條目。

**核心決策點**
- 延遲觸發:**輪詢 DB(掃 `run_at <= now`) vs delay queue(如 Redis sorted set 以時間為 score、或 Kafka 延遲主題)**:判準——量小輪詢即可;量大用 sorted set,worker `ZRANGEBYSCORE` 取到期任務,取用原子(`ZPOPMIN` / Lua)避免重複領。
- 觸發保證:**at-most-once vs at-least-once + 冪等**:判準——分散式無真 exactly-once → at-least-once 觸發 + 任務執行冪等(用 job ID 去重),達到「效果上只執行一次」。
- 領取協調:**單一 scheduler(單點) vs 多 worker 搶佔(帶 lease/lock)**:判準——單點簡單但不可用風險高 → 多 worker + 分散式鎖 / 租約(lease)搶任務,做完釋放,逾時未完成可被他人接手。
- cron 分片:**單機跑所有 cron vs 依任務 key 分片到多節點**:判準——任務量大 → 按 hash 分片,各節點負責一部分,配 leader election 或一致性協調避免重複。

**必背數字**
- 到期精度依 poll 間隔(秒級常見);高精度需更密集掃描或優先佇列。
- lease 逾時要 > 任務最長執行時間,否則會被誤搶重跑。

**高頻追問**
- 「怎麼保證任務不重複執行?」→ 領取原子化 + 執行冪等(job ID 去重表)。
- 「worker 領了任務就掛?」→ lease 逾時後任務重新可領,配合冪等避免副作用重複。
- 「大量任務同一秒到期(驚群)?」→ 加抖動(jitter)打散,或分片分散觸發。

**repo 資源**:無專案。可參考 [../notification-system/README.md](../notification-system/README.md) 的 scheduled notification(`scheduled_at`)與 Kafka 消費模型。本條目為短條目,已涵蓋核心。

---

## 題型 → 共同 pattern 對照表

每題用到 [cross-cutting-patterns.md](cross-cutting-patterns.md) 的哪幾章(章名對齊姊妹檔實際章節):

| 題目 | 主要用到的 pattern(連結) |
|---|---|
| Short URL / Pastebin | [ID 生成](cross-cutting-patterns.md#11-geo-indexing-與-id-生成短章)、[快取模式](cross-cutting-patterns.md#6-快取模式)、[容量估算](cross-cutting-patterns.md#1-容量估算back-of-envelope)、[hot key](cross-cutting-patterns.md#8-hot-key--hot-partition) |
| Typeahead | [快取模式](cross-cutting-patterns.md#6-快取模式)、[sharding](cross-cutting-patterns.md#5-sharding-與-consistent-hashing)、[容量估算](cross-cutting-patterns.md#1-容量估算back-of-envelope) |
| News Feed / Twitter | [Fan-out](cross-cutting-patterns.md#7-fan-out)、[hot key](cross-cutting-patterns.md#8-hot-key--hot-partition)、[快取模式](cross-cutting-patterns.md#6-快取模式)、[一致性譜系](cross-cutting-patterns.md#3-一致性譜系) |
| Chat / WhatsApp | [Fan-out](cross-cutting-patterns.md#7-fan-out)、[Idempotency 與 exactly-once](cross-cutting-patterns.md#4-idempotency-與-exactly-once)、[佇列與 backpressure](cross-cutting-patterns.md#10-佇列與-backpressure)、[sharding](cross-cutting-patterns.md#5-sharding-與-consistent-hashing) |
| Notification | [Fan-out](cross-cutting-patterns.md#7-fan-out)、[Idempotency 與 exactly-once](cross-cutting-patterns.md#4-idempotency-與-exactly-once)、[佇列與 backpressure](cross-cutting-patterns.md#10-佇列與-backpressure)、[Rate limiting](cross-cutting-patterns.md#9-rate-limiting-演算法)、[可靠性三件套](cross-cutting-patterns.md#12-可靠性三件套timeout--retry--circuit-breaker) |
| YouTube | [容量估算](cross-cutting-patterns.md#1-容量估算back-of-envelope)、[佇列與 backpressure](cross-cutting-patterns.md#10-佇列與-backpressure)、[快取模式](cross-cutting-patterns.md#6-快取模式)、[sharding](cross-cutting-patterns.md#5-sharding-與-consistent-hashing) |
| Netflix | [快取模式](cross-cutting-patterns.md#6-快取模式)、[佇列與 backpressure](cross-cutting-patterns.md#10-佇列與-backpressure)、[hot key](cross-cutting-patterns.md#8-hot-key--hot-partition) |
| Live Streaming | [Fan-out](cross-cutting-patterns.md#7-fan-out)、[快取模式](cross-cutting-patterns.md#6-快取模式)、[hot key](cross-cutting-patterns.md#8-hot-key--hot-partition)、[Rate limiting](cross-cutting-patterns.md#9-rate-limiting-演算法) |
| Uber / Lyft | [Geo-indexing](cross-cutting-patterns.md#11-geo-indexing-與-id-生成短章)、[hot partition](cross-cutting-patterns.md#8-hot-key--hot-partition)、[佇列與 backpressure](cross-cutting-patterns.md#10-佇列與-backpressure)、[容量估算](cross-cutting-patterns.md#1-容量估算back-of-envelope) |
| UberEats / DoorDash | [Geo-indexing](cross-cutting-patterns.md#11-geo-indexing-與-id-生成短章)、[併發寫入處理](cross-cutting-patterns.md#2-併發寫入處理核心章)、[Idempotency 與 exactly-once](cross-cutting-patterns.md#4-idempotency-與-exactly-once)、[一致性譜系](cross-cutting-patterns.md#3-一致性譜系) |
| Yelp / proximity | [Geo-indexing](cross-cutting-patterns.md#11-geo-indexing-與-id-生成短章)、[快取模式](cross-cutting-patterns.md#6-快取模式) |
| Dropbox / Drive | [併發寫入處理](cross-cutting-patterns.md#2-併發寫入處理核心章)、[一致性譜系](cross-cutting-patterns.md#3-一致性譜系)、[快取模式](cross-cutting-patterns.md#6-快取模式) |
| Google Docs | [併發寫入處理](cross-cutting-patterns.md#2-併發寫入處理核心章)、[一致性譜系](cross-cutting-patterns.md#3-一致性譜系) |
| Payment | [Idempotency 與 exactly-once](cross-cutting-patterns.md#4-idempotency-與-exactly-once)、[併發寫入處理](cross-cutting-patterns.md#2-併發寫入處理核心章)、[一致性譜系](cross-cutting-patterns.md#3-一致性譜系)、[可靠性三件套](cross-cutting-patterns.md#12-可靠性三件套timeout--retry--circuit-breaker) |
| Ticket / Flash Sale | [併發寫入處理](cross-cutting-patterns.md#2-併發寫入處理核心章)、[hot key / hot partition](cross-cutting-patterns.md#8-hot-key--hot-partition)、[佇列與 backpressure](cross-cutting-patterns.md#10-佇列與-backpressure)、[Idempotency 與 exactly-once](cross-cutting-patterns.md#4-idempotency-與-exactly-once) |
| Rate Limiter | [Rate limiting 演算法](cross-cutting-patterns.md#9-rate-limiting-演算法)、[併發寫入處理](cross-cutting-patterns.md#2-併發寫入處理核心章)、[sharding](cross-cutting-patterns.md#5-sharding-與-consistent-hashing) |
| Web Crawler | [佇列與 backpressure](cross-cutting-patterns.md#10-佇列與-backpressure)、[sharding](cross-cutting-patterns.md#5-sharding-與-consistent-hashing)、[Rate limiting](cross-cutting-patterns.md#9-rate-limiting-演算法) |
| Job Scheduler | [Idempotency 與 exactly-once](cross-cutting-patterns.md#4-idempotency-與-exactly-once)、[佇列與 backpressure](cross-cutting-patterns.md#10-佇列與-backpressure)、[併發寫入處理](cross-cutting-patterns.md#2-併發寫入處理核心章) |

---

## 自測 checklist(10 條)

遮住答案,每條能不能一口氣講出推導鏈與判準:

1. **讀重寫輕題**:能不能講清楚 short code 用 hash 還是發號器、為什麼要三層 cache、301 vs 302 的取捨?
2. **Fan-out**:能不能說出 push vs pull 的判準,以及 celebrity(hot key)為什麼要特判、怎麼混合?
3. **presence / 長連線**:能不能說明「為什麼只能靠心跳反推離線」以及訊息投遞為什麼是 at-least-once + 去重?
4. **媒體題**:能不能把 YouTube 拆成 object storage + CDN + async pipeline + metadata DB,並講出 Netflix「預轉 + 預佈邊緣」和 UGC 的差別?
5. **WebSocket vs SSE**:能不能用「是否需要 client → server」一句話判斷,並各舉一個場景?
6. **Geo**:能不能推導「二維交集慢 → 切格子 → quadtree / geohash」,並記得查周圍八格?
7. **外送 vs 叫車**:能不能點出三方 marketplace 多出的訂單狀態機、restaurant inventory、備餐 ETA 與 dispatch 時機?
8. **Payment**:能不能講清 idempotency key、為什麼 double-entry ledger 必須不可變、saga vs 2PC 判準、對帳為什麼必須存在?
9. **Hot row / 秒殺**:能不能講出三層破法(入口削峰 → Redis 原子扣減 → 佇列序列化)+ seat hold + TTL,並說「寧可少賣不可超賣」?
10. **基礎設施題**:rate limiter 四演算法能不能各講一句取捨 + 分散式 race 怎麼解?crawler 的 politeness / bloom filter / trap 三點能不能都提到?

