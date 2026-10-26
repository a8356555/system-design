# 重要組件的深刻認識(Component Deep Dives)

> 這份不是使用手冊,是「面試官追問到第三層時,你還答得出來」的認識。每個組件只問三件事:**它為什麼能做到它宣稱的(內部機制)、它什麼時候會騙你/爆掉(失效模式)、面試官會怎麼追**。
>
> 讀法:先看「一句話定位」,遮住其餘自己講一遍內部機制,講不動再往下看。搭配 [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md) 的推導模板——這份給你積木的「深度」,那份給你組裝的「推理」。
>
> 固定結構:**一句話定位 → 內部機制(重點)→ 保證與不保證 → 失效模式與 tuning 直覺 → 面試追問**。

---

## 1. Kafka(最高頻)

**一句話定位**:一個**分散式、可重播、以 partition 為單位順序寫的 append-only log**。它不是 message queue,是「持久化的事件日誌」——訊息被消費不會消失,offset 由 consumer 自己記。

### 內部機制

**(a) log 抽象為什麼快——三件套(接 [os-02 第 5、6 節](../../docs/cs-fundamentals/os-02-io-and-filesystems.md))**

每個 partition 就是磁碟上一疊 append-only segment 檔。Kafka 高吞吐的三個物理根源:

| 招式 | 機制 | 為什麼快 |
|---|---|---|
| **順序 I/O** | producer 永遠往 log 尾端 append,不做隨機寫 | 順序寫比隨機寫快幾個數量級,連 HDD 都能跑滿頻寬([os-02 §6](../../docs/cs-fundamentals/os-02-io-and-filesystems.md)) |
| **page cache** | 寫入先進 OS page cache,不自己管 buffer;剛寫的訊息還熱 | consumer 讀近期資料常常連磁碟都不碰 |
| **zero-copy(sendfile)** | broker 用 `sendfile` 把 log 片段從 page cache 直送 consumer 的 socket | 不進 JVM heap、不繞 user space,省掉多次拷貝([os-02 §5](../../docs/cs-fundamentals/os-02-io-and-filesystems.md)) |

面試問「Kafka 為什麼快」,答這三件套就滿分。反過來也要知道:**開了 TLS/SSL 加密就破功**——資料要進 user space 解密,sendfile zero-copy 失效,吞吐明顯掉。

**(b) partition 與 consumer group——平行度模型**

- Partition 是**平行度的原子單位**。一個 partition 在同一個 consumer group 裡**只能被一個 consumer 消費**。
- 所以 **consumer group 的有效平行度 = min(partition 數, consumer 數)**。partition 開 4 個,consumer 開 10 個,有 6 個永遠閒著。
- 推論:**partition 數是吞吐的上限,且只能加不能減**(減會亂掉 key→partition 的映射)。開多少?見 [dcard-interview.md §3](../dcard-interview.md)(`user_shard = user_id % N` 避免百萬 partition 的推理)。
- **同一 key 的訊息保證進同一 partition**(預設 hash(key) % partition 數),所以**順序保證只在單一 partition 內成立**,跨 partition 無全域順序。要保序就得讓相關事件共用 key。

**(c) replication 內部**

每個 partition 有 N 個副本(replication factor):一個 **leader**,其餘 **follower**。

```
  partition-0  replication.factor = 3
    ┌─ broker A: leader   ◄── producer 只跟 leader 講話,consumer 也只讀 leader
    ├─ broker B: follower ── 不斷向 leader fetch,追平 log
    └─ broker C: follower ── 落後太多會被踢出 ISR
```

- **所有讀寫都走 leader**,follower 只是不斷 fetch leader 的 log 來複製(pull 模式,不是 leader push)。
- **ISR(In-Sync Replicas,同步副本集合)**:能跟上 leader 進度的副本(含 leader 自己)。follower 落後超過 `replica.lag.time.max.ms` 就被踢出 ISR,追上再加回。ISR 是**動態的**。
- Leader 掛掉時,controller 從 **ISR 裡**選新 leader——因為 ISR 裡的副本才保證有最新資料。

**acks:producer 的持久性旋鈕**(接 [os-02 §7](../../docs/cs-fundamentals/os-02-io-and-filesystems.md) 「Kafka 靠 replication 而非每筆 fsync」)

| `acks` | leader 何時回 ack | 丟資料風險 | 用在哪 |
|---|---|---|---|
| `0` | 送出就當成功,不等 | 最高,leader 沒收到也不知道 | metrics、log,丟一點無所謂、要極致吞吐 |
| `1` | leader 寫進自己的 log 就回 | leader 落盤前掛掉、follower 還沒複製到 → 丟 | 預設折衷(舊版) |
| `all`(=`-1`) | 等 **ISR 裡所有副本**都複製到才回 | 最低 | 金流、訂單,不能丟 |

**關鍵陷阱:`acks=all` 不等於「至少 N 份」**。它等的是「當前 ISR 全部」——如果 ISR 因為 follower 都落後被縮到只剩 leader 一個,`acks=all` 就退化成 `acks=1`,你以為很安全其實只有一份。補這個洞的是:

- **`min.insync.replicas`**:ISR 少於這個數時,producer 的 `acks=all` 寫入**直接被拒絕**(`NotEnoughReplicas`),寧可寫失敗也不假裝安全。標準生產設定:**replication.factor=3 + min.insync.replicas=2 + acks=all**——容許掛一台,還保證每筆至少寫進 2 份才回成功。

**unclean.leader.election(這題最能分辨懂不懂)**

ISR 全掛了怎麼辦?(例如三台副本同時斷電)

- `unclean.leader.election.enable=false`(現代預設):**不允許**從 ISR 外(落後的副本)選 leader。partition 直接**不可用**,等 ISR 裡的副本活回來。選擇了 **一致性 > 可用性**(CP)。
- `=true`:允許讓一個落後的 out-of-sync 副本當 leader,partition 立刻恢復可用,但**那個副本缺的訊息就永久丟了**(已 commit 的資料消失,還可能造成 log divergence)。選擇了 **可用性 > 一致性**(AP)。
- 這就是 CAP 在 Kafka 一個旋鈕上的具體化。面試講得出「這個 flag 是在 CP 和 AP 之間選邊」就是 senior 訊號。

**(d) rebalance 的痛**:consumer group 成員增減、或有 consumer 心跳超時,會觸發 rebalance——重新分配 partition 給 consumer。傳統(eager)rebalance 是 **stop-the-world**:所有 consumer 先放棄全部 partition、暫停消費、重新分配、再開始,期間整個 group 卡住。這是 Kafka 運維最常見的抖動來源。常見肇因:consumer 處理單筆太久超過 `max.poll.interval.ms` 被踢、擴縮容、部署滾動重啟。緩解:`cooperative-sticky` 分配策略(只搬動要動的 partition,不全放)、把重活移出 poll loop、調大 `max.poll.interval.ms`。

**(e) log compaction**:除了「保留 N 天就刪」(time/size retention),Kafka 還有 compaction 模式——**同一 key 只保留最後一筆值**,舊值背景清掉。這讓 topic 變成一張「可重播的 key→最新值表」,是 CDC、event sourcing、把 topic 當狀態儲存(如 Kafka Connect offset、KStreams changelog)的基礎。

**(f) transactions / EOS**:Kafka 支援 exactly-once semantics(冪等 producer + 交易),讓「consume→process→produce」這條鏈的輸出對下游只生效一次。一句帶過即可,追問再展開:底層是 producer 的 sequence number 去重 + 交易性寫多 partition + consumer 的 `read_committed` 隔離。

### 保證與不保證

| Kafka 保證 | Kafka 不保證 |
|---|---|
| 單一 partition 內的訊息順序 | 跨 partition 的全域順序 |
| 訊息持久(靠 replication,`acks=all`+`min.insync`) | 每筆都 fsync 落盤(預設靠副本,不逐筆 fsync) |
| at-least-once 交付(預設) | 天生 exactly-once(要開 EOS/交易才有) |
| 已 commit 的訊息可被重播(retention 內) | 無限期保留(過 retention 或被 compact 就沒了) |
| 同 key 進同 partition | consumer 處理不重複(那是你 offset 提交時機的責任) |

### 失效模式與 tuning 直覺

- **consumer lag 一路漲**:消費追不上生產。看是單 consumer 太慢(加 partition + consumer 平行)還是有毒訊息卡住(加 DLQ)。lag 是 Kafka 最重要的健康指標。
- **hot partition**:某個 key 流量爆量(如某大 V 的貼文),該 partition 的 consumer 過載而其他閒置。解法:換 partition key、或對熱 key 加 salt 打散。
- **重複消費**:consumer 處理完但 offset 還沒提交就掛 → 重播。所以下游必須**冪等**(接 [handling-unfamiliar-topics.md §8 冪等與對帳](handling-unfamiliar-topics.md))。
- **producer 端 tuning**(接 [data-intensive-app/README.md](../data-intensive-app/README.md) 的 async producer):`batch.size` + `linger.ms` 換吞吐(攢一批再送,犧牲一點延遲),`compression.type`(lz4/zstd)省頻寬,`acks` 換持久性。三個旋鈕就是延遲/吞吐/持久的三角。

### 面試追問

1. **「`acks=all` 保證不丟資料嗎?」**——不夠,要配 `min.insync.replicas≥2`,否則 ISR 縮到只剩 leader 時 `acks=all` 退化成 `acks=1`。
2. **「unclean leader election 開與不開,各犧牲什麼?」**——不開=partition 可能不可用但不丟已 commit 資料(CP);開=立即可用但可能丟資料(AP)。
3. **「Kafka 為什麼比傳統 MQ 快這麼多?」**——順序 append + page cache + zero-copy sendfile;且 consumer 自己記 offset,broker 不用追蹤每筆的 per-message ack 狀態。追問:開 TLS 後為何吞吐掉?(zero-copy 失效)

---

## 2. Redis

**一句話定位**:一個**單執行緒、記憶體優先、資料結構即 API** 的伺服器。它快不是因為魔法,是因為所有操作都在記憶體 + 避開鎖與 context switch。

### 內部機制

**(a) 單執行緒 event loop 為什麼夠快,以及什麼會卡死它**

Redis 用**單一主執行緒 + epoll event loop**([os-02 §3](../../docs/cs-fundamentals/os-02-io-and-filesystems.md))處理所有 client 命令。敢單執行緒是因為:操作都在記憶體(µs 級)、瓶頸在網路 I/O 不在 CPU、單執行緒**天然沒有鎖和 race condition**——所以每個命令都是原子的(這也是它能當 lock/counter 的根基)。

但單執行緒的代價是:**任何一個慢命令會卡住所有人**。經典地雷:

| 卡死主執行緒的操作 | 為什麼 | 正確做法 |
|---|---|---|
| `KEYS *` | O(n) 掃全部 key,百萬 key 直接卡秒級 | 用 `SCAN`(游標式增量掃) |
| 大 value(幾 MB 的 hash/list) | 單次操作/傳輸/刪除都吃主執行緒時間 | 拆小、`UNLINK`(背景刪)取代 `DEL` |
| 慢 Lua script / `MULTI` 大交易 | script 執行期間全 server 阻塞 | script 要短、可預測 |
| `SAVE`(同步存 RDB) | 前景 fork+寫盤 | 用 `BGSAVE` |

**(b) 資料結構就是 API——面試應用場景**

Redis 的價值不在「快取字串」,在它內建的資料結構直接對應到系統設計問題:

| 結構 | 命令 | 面試場景 |
|---|---|---|
| String + `INCR` | 原子計數 | rate limiter 計數、庫存扣減(接 [handling §7 秒殺](handling-unfamiliar-topics.md)) |
| Hash | `HSET`/`HGET` | 存物件(user profile),省記憶體 |
| **Sorted Set(ZSET)** | `ZADD`/`ZRANGE`/`ZRANGEBYSCORE` | **排行榜、延遲佇列(score=執行時間)、時間窗 rate limit(score=timestamp)** |
| List | `LPUSH`/`BRPOP` | 簡單佇列、最近 N 筆 |
| **Stream** | `XADD`/`XREADGROUP` | 帶 consumer group 的輕量事件流(Kafka 的小號替代) |
| Bitmap / HyperLogLog | `SETBIT` / `PFADD` | 日活躍去重(HLL 用極小記憶體估基數,接 [handling bloom/count-min 精神](handling-unfamiliar-topics.md)) |

「用什麼結構做排行榜」→ ZSET,是最高頻的 Redis 追問。

**(c) persistence:RDB vs AOF 的真話**

| | RDB(快照) | AOF(append-only file) |
|---|---|---|
| 機制 | 定期 fork 子進程 dump 全記憶體成一個檔 | 每個寫命令 append 到 log |
| 恢復 | 快(直接載入) | 慢(replay 所有命令) |
| 丟資料 | 丟兩次快照之間的(可能幾分鐘) | 看 fsync 策略:`always`(每筆,慢)/ `everysec`(預設,丟≤1秒)/ `no`(靠 OS) |
| 真話 | Redis **不是為持久設計的**,別當唯一真相來源 | 生產常 RDB+AOF 並用;`everysec` 是吞吐/安全的折衷,和 [os-02 §7](../../docs/cs-fundamentals/os-02-io-and-filesystems.md) Postgres `synchronous_commit` 是同一個賭注 |

**(d) cluster mode:16384 hash slots**

單機記憶體/吞吐不夠時,Redis Cluster 把 key 空間切成**固定 16384 個 hash slot**(`CRC16(key) % 16384`),每個節點負責一段 slot 範圍。

- **resharding = 搬 slot**:加節點時把一部分 slot 連同資料搬過去,線上進行。
- **為什麼 multi-key 操作受限**:`MGET k1 k2`、交易、Lua 若 key 落在不同節點就無法原子執行。解法:**hash tag** `{user123}:profile` 和 `{user123}:cart` ——大括號內相同就保證同 slot,能一起操作。這是 cluster 模式最常咬人的限制。

**(e) sentinel vs cluster**

| | Sentinel | Cluster |
|---|---|---|
| 解決 | **高可用**(自動 failover) | **水平擴展**(sharding)+ 高可用 |
| 資料 | 全部在一個 master(+副本),沒分片 | 分散在多節點 |
| 何時用 | 資料塞得下單機,只要不掛 | 單機裝不下或吞吐不夠 |

**(f) 快取之外的角色與各自的坑**

- **分散式鎖**:`SET key val NX PX 30000`(不存在才設 + 自動過期)。坑:過期時間到了但業務還沒做完 → 鎖被別人搶走。**Redlock**(多節點多數決)有學術爭議(Martin Kleppmann 質疑其在 GC pause / 時鐘漂移下的正確性),要強一致的鎖用 [ZK/etcd](#3-zookeeper--etcd近乎全新寫足)。一句話:**Redis 鎖適合「搶到最好、偶爾雙搶可容忍」,不適合「絕不能雙持有」**。
- **rate limiter**:`INCR` + `EXPIRE` 固定窗,或 ZSET 滑動窗。
- **queue**:List(`BRPOP`)或 Stream。坑:List 沒有消費確認,消費者拿了就掛訊息會丟(要 Stream 的 ack)。

### 保證與不保證

| Redis 保證 | Redis 不保證 |
|---|---|
| 單命令原子(單執行緒) | 跨節點 multi-key 原子(cluster 下) |
| 極低延遲(記憶體) | 持久(除非 AOF always,且那會慢) |
| 主從複製 | **強一致**:複製是非同步的,failover 會丟已寫入 master 但沒同步到副本的資料 |

### 失效模式與 tuning 直覺

- **cache stampede(快取雪崩/擊穿)**:熱 key 過期瞬間,大量請求同時打穿到 DB。解法:互斥重建(只讓一個請求回源)、邏輯過期、隨機 TTL 避免同時到期。
- **big key / hot key**:單個大 value 或單個超熱 key 拖垮節點。監控 + 拆分。
- **記憶體打滿 + eviction**:設 `maxmemory` + policy(`allkeys-lru` 等)。忘了設 → OOM 或寫入被拒。
- **主從複製延遲**:剛寫 master 立刻讀副本可能讀到舊值(非同步複製)。要 read-after-write 就讀 master。

### 面試追問

1. **「Redis 單執行緒為什麼還這麼快?什麼會讓它變慢?」**——記憶體 + 無鎖 + epoll;慢命令(`KEYS`、大 value、慢 Lua)阻塞全局。
2. **「做排行榜用什麼?延遲佇列呢?」**——都是 ZSET,score 分別放分數和執行時間戳。
3. **「Redis 當分散式鎖安全嗎?」**——一般夠用但非同步複製 + failover 可能丟鎖;要強保證用 ZK/etcd,Redlock 有爭議。

---

## 3. ZooKeeper / etcd

**一句話定位**:分散式系統的**「大家都同意的一小塊真相」**。不是資料庫,是**協調服務(coordination service)**——存的是 config、誰是 leader、鎖、成員清單這類「量小但必須全體一致」的關鍵狀態。

### 內部機制

**(a) 它們解什麼問題**

分散式系統有個根本難題:多台機器怎麼對「一件事」達成一致?例如:

- 誰是現在的 leader?(不能兩個都以為自己是 → split-brain)
- 這個分散式鎖現在誰持有?
- 叢集現在有哪些活著的節點?(membership)
- 這份 config 的最新值是什麼?

這些狀態的共同點:**資料量很小,但一致性要求極高**——所有人讀到的必須是同一個值,不能各說各話。這正是 ZK/etcd 的定位:一個**高一致、可線性化(linearizable)讀寫的小型 KV store**,你把「需要全體同意的真相」放這裡。

**(b) 共識演算法直覺版(Raft,用故事不用數學)**

etcd 用 **Raft**,ZK 用 **ZAB**(概念相通)。Raft 的三個角色故事:

```
  一群節點要選一個 leader,並讓所有人的 log 一致:

  1. term(任期):時間切成一段段任期,每段最多一個 leader。
     像「第 5 屆總統」,任期編號單調遞增,用來辨識新舊。

  2. leader election(選舉):
     - 平時 follower 等 leader 的心跳。
     - 心跳超時 → follower 變 candidate,term+1,向大家拉票。
     - 拿到「多數票(quorum,過半)」就當 leader。
     - 為什麼要過半?→ 兩個 leader 不可能同時各拿到過半(鴿籠原理),
       這就從根本上杜絕了 split-brain。

  3. log replication(日誌複製):
     - 所有寫入只由 leader 接,append 到自己的 log。
     - leader 把 entry 複製給 follower,「多數確認」後才 commit。
     - 只要多數活著,系統就能繼續;掛掉的少數追上即可。
```

**核心直覺:一切靠「過半(quorum)」**。過半確認才算數,所以能容忍**少於半數**的節點失效:3 台容忍掛 1、5 台容忍掛 2。這也解釋了為什麼**節點數通常是奇數**(3、5)——4 台和 3 台一樣只能容忍掛 1,多一台只是成本。

**(c) 為什麼寫入量不能大——這是最重要的認識**

**所有寫入都要經過 leader + 過半節點確認落盤**。這意味著每一筆寫都有一輪跨節點的網路往返 + fsync。所以:

- ZK/etcd 的寫吞吐是**幾千 ops/s 等級**,不是幾十萬。
- **它們不是拿來存業務資料的**。把高頻業務寫塞進 etcd = 打爆它 = 拖垮依賴它的整個叢集(例如 K8s)。
- 讀可以擴(follower 也能服務讀,或用 leader lease 保線性化),但**寫是天生的瓶頸**,這是共識的代價,不是實作缺陷。

**(d) ZK znode/watch/ephemeral vs etcd lease/watch 對應**

| 概念 | ZooKeeper | etcd | 用途 |
|---|---|---|---|
| 資料節點 | znode(樹狀路徑) | key(扁平 + prefix) | 存那一小塊真相 |
| **變更通知** | watch(一次性,要重設) | watch(串流式,持續) | config 變了、leader 換了立刻知道 |
| **會話綁定的臨時節點** | ephemeral node(session 斷就自動刪) | lease + key(lease 過期 key 自動刪) | **這是做鎖/presence 的關鍵機制** |
| 有序性 | sequential node(自動遞增後綴) | revision(全域單調版本號) | 公平鎖、排隊 |

**ephemeral/lease 為什麼是關鍵**:節點掛了(session/lease 過期),它建的臨時 key **自動消失**。所以「持有鎖的人掛了,鎖自動釋放」「presence 節點消失代表下線」都是天然的——不需要額外的心跳偵測邏輯,機制內建。

**(e) distributed lock:用 ZK/etcd vs Redis 的判準**

| | ZK/etcd 鎖 | Redis 鎖 |
|---|---|---|
| 正確性 | 強(共識 + ephemeral 自動釋放 + fencing token) | 弱(非同步複製,failover 可能雙持有) |
| 效能 | 較低(每次過 quorum) | 高(記憶體單命令) |
| 判準 | **絕不能兩人同時持有**(如 controller 選主) | **偶爾雙持有可容忍、要快**(如去重觸發) |

**fencing token**:ZK/etcd 的 sequential/revision 給你一個單調遞增的 token,下游可以拒絕舊 token 的操作——這是防「持鎖者卡住又復活」造成資料損壞的正解,Redis 鎖較難優雅實現。

**(f) 誰在用它們**

- **Kafka**:舊版用 ZK 存 broker membership、controller 選舉、topic metadata;新版 **KRaft** 把這搬進 Kafka 自己(內建 Raft),幹掉 ZK 依賴——因為多維護一個 ZK 叢集是運維負擔,且 ZK 成了 metadata 規模的瓶頸。
- **Kubernetes**:**etcd 是 K8s 的唯一真相來源**,所有叢集狀態(Pod、Service、ConfigMap)都存在 etcd。這也是為什麼「etcd 慢/滿」= 整個 K8s 控制面癱瘓,etcd 的備份是 K8s 災難恢復的核心。

### 保證與不保證

| ZK/etcd 保證 | ZK/etcd 不保證 |
|---|---|
| 線性化的讀寫(強一致) | 高寫入吞吐(共識天生受限) |
| 過半存活即可用(容忍少數失效) | 過半掛掉還能寫(失去 quorum 就停寫) |
| 臨時節點在會話斷時自動清理 | 存大量/大體積資料(是協調服務不是 DB) |
| watch 可靠通知變更 | 無限低延遲(每寫過 quorum) |

### 失效模式與 tuning 直覺

- **失去 quorum**:5 台掛 3 → 無法過半 → **整個服務停止寫入**(只能讀舊值或全不可用)。所以跨機架/跨 AZ 部署避免同時失效很重要。
- **寫入被濫用**:把它當 KV DB 高頻寫 → 延遲飆升 → 依賴它的系統(K8s/Kafka)集體抖動。
- **watch 風暴**:大量 client watch 同一個 key,變更時一次性喚醒全部 → 驚群(thundering herd)。設計鎖時用「只 watch 前一個排隊者」避免。
- **etcd defrag / compaction**:etcd 保留歷史 revision,不定期 compact + defrag 會讓 DB 膨脹到觸發 quota 而拒寫——K8s 運維經典事故。

### 面試追問

1. **「為什麼 ZK/etcd 的寫入量不能大?」**——每筆寫要過 leader + 過半節點確認落盤,共識的固有成本;它是協調服務不是資料庫。
2. **「分散式鎖,ZK/etcd 和 Redis 怎麼選?」**——絕不能雙持有 → ZK/etcd(共識 + ephemeral + fencing token);要快且能容忍偶爾雙搶 → Redis。
3. **「Raft 怎麼避免 split-brain?」**——leader 要拿過半票,兩個 leader 不可能同時各過半;term 編號辨識新舊。追問:3 台能容忍掛幾台?(1 台,要保過半)

---

## 4. Cassandra / DynamoDB 家族

**一句話定位**:**為寫入吞吐和水平擴展而生的 wide-column store**。用 LSM-tree 讓寫入極快、用一致性雜湊分散資料、用可調一致性換可用性——代價是**沒有 join、要照查詢先建模**。

### 內部機制

**(a) LSM-tree 寫路徑(接 [os-02 §6](../../docs/cs-fundamentals/os-02-io-and-filesystems.md) 與 DDIA Ch3)**

為什麼寫快讀(可能)慢:

```
  寫: → 先寫 commit log(WAL,順序 append,可恢復)
      → 同時寫記憶體的 memtable(排序結構)
      → memtable 滿 → 順序 flush 成一個不可變的 SSTable 檔(順序 I/O!)
      → 背景 compaction 把多個 SSTable 合併、去重、刪 tombstone

  讀: → 查 memtable → 查多個 SSTable(可能要翻好幾個)
      → 用 bloom filter 快速跳過「一定沒有」的 SSTable
      → 可能要合併多版本 → 比單一 B-tree 讀複雜
```

核心 tradeoff:**把隨機寫變成順序寫(快),代價是讀可能要翻多個 SSTable(慢)+ compaction 的背景 CPU/I/O 開銷**。相對地,B-tree(Postgres)讀快(一次定位)但寫要隨機更新頁。**寫重選 LSM,讀重選 B-tree** 是儲存引擎選型的第一刀。

**(b) wide-column 資料模型與 query-first 建模**

不是關聯式的「先設計正規化 schema 再想查詢」,而是**倒過來:先列出你要跑的查詢,再設計表**。

- 資料按 **partition key** 分片(決定資料在哪台機器),partition 內按 **clustering key** 排序。
- 你只能高效查「給定 partition key」的資料——**沒有 join、沒有任意欄位的 ad-hoc 查詢**。
- 所以同一份資料常**為不同查詢反正規化存多份**(denormalization)。寫放大換讀效能。

**(c) tunable consistency 與 W+R>N**

這是 Dynamo 系列的招牌。設 replication factor = N,每次寫要 W 個副本確認、每次讀問 R 個副本:

| 設定 | 效果 |
|---|---|
| `W + R > N` | **保證讀到最新寫入**(讀寫的副本集合必然重疊,強一致) |
| 例:N=3, W=QUORUM(2), R=QUORUM(2) | 2+2>3,強一致且容忍掛 1 台 |
| `ONE`(W=1 或 R=1) | 最快、最可用,但可能讀到舊值(最終一致) |
| `ALL` | 最強但一台掛就不可用 |

**旋鈕在你手上**:同一個叢集,關鍵讀用 QUORUM、能容忍舊值的讀用 ONE。這就是 CAP 裡「每次操作各自選 C 或 A」的具體化。

**(d) hinted handoff、read repair(掉隊副本怎麼追上)**

- **hinted handoff**:寫入時某副本暫時掛了,協調節點先把這筆「暗示」存下來,等它活回來再補送——短暫故障不影響寫可用性。
- **read repair**:讀取時發現多個副本值不一致,回傳最新的給 client,同時**順手把舊副本更新**——用讀流量慢慢修複製差異。
- 兩者合起來讓系統「最終一致」:允許暫時分歧,靠這些機制收斂。

### 保證與不保證

| Cassandra/Dynamo 保證 | 不保證 |
|---|---|
| 極高寫入吞吐(LSM 順序寫) | join、跨 partition 交易(基本沒有) |
| 線性水平擴展(加節點加吞吐) | ad-hoc 任意查詢(只能照 partition key 查) |
| 可調一致性(W+R>N 可強一致) | 預設強一致(預設常是最終一致) |
| 多 DC 複製、無單點 | 讀效能一定好(要看 compaction/SSTable 數) |

### 失效模式與 tuning 直覺

- **tombstone 累積**:刪除是寫一個 tombstone 標記(不是真刪),掃描時要跳過大量 tombstone → 讀變慢甚至 timeout。大量刪除/TTL 的 workload 要小心。
- **hot partition**:partition key 選不好(如用低基數欄位或時間),流量集中在少數 partition → 熱點。key 設計是 Cassandra 成敗關鍵。
- **compaction 風暴**:背景 compaction 吃 I/O,和前景讀寫搶資源。
- **大 partition**:單一 partition 資料無限成長 → 讀取和修復都變慢。

### 面試追問

1. **「Cassandra 為什麼寫這麼快?」**——LSM-tree:WAL 順序 append + memtable,把隨機寫變順序寫,不像 B-tree 要隨機更新頁。
2. **「怎麼保證讀到最新資料?」**——W+R>N,讓讀寫的副本集合必然重疊;例如 N=3 用 QUORUM 讀寫。
3. **「什麼場景選 Cassandra 而不是 Postgres?」**——寫重、要線性水平擴展、多 DC、查詢模式固定且不需要 join(如時序、IoT、feed、訊息);反之要交易/join/中小規模就 Postgres。

---

## 5. Elasticsearch

**一句話定位**:建在 Lucene 上的**分散式全文搜尋引擎**——核心是 inverted index,讓「哪些文件包含這個詞」變成一次查表而非全表掃描。它是搜尋/log 分析的利器,但**不是可靠的 primary store**。

### 內部機制

**(a) inverted index(倒排索引)**

一般 DB 的索引是「文件 → 內容」;搜尋要的是反過來「**詞 → 哪些文件有它**」:

```
  正排(慢):doc1: "the quick fox"  → 要找 "fox" 得掃每篇文件
  倒排(快):
     "quick" → [doc1, doc7, doc9]   ← posting list(倒排列表)
     "fox"   → [doc1, doc3]
  查 "quick fox" → 兩個 posting list 取交集 → doc1
```

建索引時做 **analysis**:斷詞(tokenize)、轉小寫、去 stop word、詞幹還原(stemming)。所以「查 running 也能命中 run」不是魔法,是建索引時就把詞正規化了。這也是為什麼**索引怎麼 analyze 決定了能查到什麼**,事後改 analyzer 要重建索引。

**(b) 為什麼是 near-real-time(不是 real-time)**

寫進去的文件**不是立刻可搜**:

- 新文件先進記憶體 buffer,每隔 **`refresh_interval`(預設 1 秒)** 才 flush 成一個新的**不可變 segment**,變成可搜。所以有約 1 秒的可見延遲——這叫 near-real-time。
- segment 不可變(呼應 LSM 精神),更新 = 標記舊的刪除 + 寫新的;背景 **merge** 小 segment 成大的、清掉已刪。
- 調 tuning:大量寫入時把 `refresh_interval` 調大(如 30s)甚至關掉,能大幅提升寫入吞吐(少做 segment)——bulk 灌資料的標準手法。

**(c) shard / replica 模型與深分頁問題**

- index 切成多個 **primary shard**(建立後不可改數量),每個 shard 是一個完整的 Lucene index;replica shard 提供高可用 + 分攤讀。
- **深分頁(deep pagination)問題**:查「第 10000 頁」時,因為結果分散在各 shard,每個 shard 都要回傳 **from+size** 筆給協調節點排序,再取那一頁——`from=100000` 會讓每個 shard 各撈 10 萬筆到記憶體排序,爆炸。所以 ES 預設 `from+size` 上限 1 萬。要深翻用 **`search_after`**(帶上一頁最後一筆的排序值,游標式)或 scroll,別用 offset 分頁。這是 ES 面試高頻坑。

**(d) relevance scoring**:預設用 BM25 算相關性分數(詞頻 × 逆文件頻率的改良版)——罕見詞比常見詞更能區分文件。一句帶過即可,追問再說「TF-IDF 家族」。

### 保證與不保證

| ES 保證 | ES 不保證 |
|---|---|
| 快速全文/模糊/聚合查詢 | 立即可見(near-real-time,約 1s) |
| 水平擴展、分散式 | 強一致 / 交易(不是 ACID) |
| 靈活的 analysis / scoring | 可靠持久(refresh≠fsync,設計上非 source of truth) |
| 豐富聚合(aggregation) | 高效深分頁(from/size 有上限) |

### 失效模式與 tuning 直覺

- **當 primary store 用**:ES 沒有真正的交易、複製模型不如專門 DB 嚴謹、曾有丟資料的歷史。**正解:真相存在 DB/Kafka,ES 只當可重建的搜尋索引**,壞了重灌即可。
- **mapping 爆炸 / field 太多**:動態 mapping 讓每個新欄位都建索引,欄位失控 → 記憶體爆。
- **shard 太多或太少**:太多 shard(over-sharding)每個都有固定開銷,拖垮叢集;太少無法平行。
- **深分頁 / 大聚合**:如上,用 search_after;大聚合吃 heap。

### 面試追問

1. **「ES 為什麼搜尋快?」**——inverted index,詞→posting list,查交集而非掃全表;建索引時就做好斷詞/正規化。
2. **「為什麼寫進去不能馬上搜到?」**——near-real-time,靠 refresh(預設 1s)把 buffer 變成可搜的 segment;可調 refresh_interval 換寫入吞吐。
3. **「什麼時候不要用 ES?」**——當唯一真相來源(不可靠、非 ACID);真相放 DB/Kafka,ES 當可重建索引。追問:深分頁為何慘?(每 shard 撈 from+size 排序)

---

## 6. 物件儲存 S3

**一句話定位**:**便宜、近乎無限、極高 durability 的 key→object KV store**。它不是檔案系統(接 [os-02 §8 S3 vs POSIX](../../docs/cs-fundamentals/os-02-io-and-filesystems.md)),是資料湖、備份、大 blob 的預設地基。

### 內部機制

**(a) 11 個 9 的 durability 怎麼來**

99.999999999% durability(存一千萬個物件,平均一萬年才丟一個)不是靠單機可靠,是靠**冗餘 + 跨故障域**:

- **多副本 / erasure coding**:每個物件的資料被切片 + 加冗餘片,分散存到**多個 AZ(availability zone)的多台機器**。erasure coding(如把資料切成 k 片 + m 片冗餘,任 k 片可還原)比純複製省空間又抗多重失效。
- **持續巡檢修復**:背景不斷校驗、發現壞片就從冗餘重建。
- 關鍵認識:**durability(不丟)≠ availability(隨時可讀)**。11 個 9 是不丟,可用性是另一個數字(約 4 個 9)。

**(b) 一致性模型現況**:S3 早年 list-after-write 是最終一致(剛寫的可能 list 不到),**AWS 已於 2020 年底改為 strong read-after-write consistency**——寫完立刻 GET 保證讀到。但「S3 歷史上 list 不即時一致」塑造了整個生態的防禦設計(Delta/Iceberg 自維 metadata),很多工具邏輯還在。

**(c) 為什麼 list 慢、沒有 rename**(接 [os-02 §8](../../docs/cs-fundamentals/os-02-io-and-filesystems.md)):

- **沒有目錄**:`/` 只是 key 字串的一部分,「資料夾」是前綴幻覺,`list` = 掃前綴,海量物件下很慢。
- **沒有原子 rename**:改名 = copy + delete,非原子、非 O(1),大檔很慢。所以 **Spark 寫 S3 要特殊 committer**(預設 committer 靠 rename 提交,在 S3 上又慢又可能出錯)——用 S3A committer 或 Delta/Iceberg/Hudi。
- **沒有 append**:物件不可追加,只能整個重寫或 multipart 拼。

**(d) presigned URL 在 SD 的用法(高頻考點)**

上傳大檔時,別讓檔案流經你的 server:

```
  差:client → 你的 server(吃頻寬/記憶體)→ S3
  好:1. client 跟 server 要一個 presigned URL(server 用自己的權限簽一個限時 URL)
      2. server 回一個「限時、限這個 key、限這個動作」的 URL
      3. client 直接 PUT 到 S3,繞過 server
```

好處:server 不碰檔案本體(省頻寬、可水平擴展)、權限仍受控(URL 有期限和範圍)。「使用者怎麼上傳大頭貼/影片」→ presigned URL 直傳,是 SD 標準答案。下載同理(限時 GET URL)。

### 保證與不保證

| S3 保證 | S3 不保證 |
|---|---|
| 11 個 9 durability | 高可用到 11 個 9(可用性約 4 個 9) |
| strong read-after-write(現況) | POSIX 語意(無 rename/append/真目錄) |
| 近乎無限容量、便宜 | 低延遲隨機小 I/O(首 byte 延遲數十 ms) |
| 單物件操作原子 | 快速 list(前綴掃描,大量物件慢) |

### 失效模式與 tuning 直覺

- **small files problem**:海量小物件 → list 慢、每次請求固定開銷、metadata 壓力。DE 要 **compaction 成大檔(Parquet)**(接 [os-02 §8](../../docs/cs-fundamentals/os-02-io-and-filesystems.md))。
- **request rate 熱點**:同前綴的高並發請求會撞分區上限;高吞吐要讓 key 前綴有隨機性(現代 S3 已大幅緩解,但大規模仍要注意)。
- **成本陷阱**:請求數(尤其海量小檔的 GET/LIST)和跨區流量費常比儲存費還貴;冷資料轉 Glacier。

### 面試追問

1. **「S3 的 11 個 9 durability 怎麼做到?」**——跨多 AZ 多機的冗餘(複製/erasure coding)+ 持續巡檢修復;強調 durability≠availability。
2. **「使用者上傳大檔怎麼設計?」**——presigned URL 直傳 S3,繞過 server,server 不碰檔案本體。
3. **「Spark 寫 S3 為什麼要特殊 committer?」**——S3 沒有原子 rename(=copy+delete),預設 committer 靠 rename 提交會慢且可能出錯;用 S3 committer 或 Delta/Iceberg。

---

## 7. 關聯式 DB 在 SD 中的角色(短章)

**一句話定位**:**當你需要交易、join、和「一份強一致的真相」時,它常常就是對的答案**——別因為想顯得會 scale 就跳過它。

### 內部機制與重點

**(a) 什麼時候它就是對的答案**:需要 ACID 交易(轉帳、訂單、庫存)、需要 join(關聯查詢)、資料量中小(單機或加讀副本就夠,大多數業務其實在這區間)、schema 相對穩定。面試時**先問清楚規模**——「這裡其實一台 Postgres + 讀副本就夠」是成熟訊號,無腦上 NoSQL/分片才是紅旗。

**(b) read replica 與 replication lag 的坑**:讀多寫少時,加**讀副本**分攤讀是第一招。但主從複製通常**非同步**,副本會落後主庫(replication lag)。經典 bug:使用者剛送出(寫主庫)立刻查詢(讀副本)→ 看不到自己剛寫的。解法:關鍵的 read-after-write 走主庫、或 sticky 到寫入後短時間內讀主。

**(c) connection pool 上限是隱形瓶頸**(接 [cs-fundamentals fd/連線數](../../docs/cs-fundamentals/os-02-io-and-filesystems.md)):每條 DB 連線在 Postgres 是一個 process/後端,吃記憶體;`max_connections` 有限(常幾百)。應用層無腦開連線 → 撞上限 → 新請求全部等待/報錯,而此時 DB 的 CPU 可能還很閒。解法:**connection pooler(PgBouncer)** 復用連線;serverless/高並發場景這是必備。這是「DB 明明不忙但請求卡住」的頭號嫌疑。

**(d) 分庫分表是最後手段**:垂直擴展(加機器規格)、加讀副本、加快取都試過還不夠,才 sharding。分片一旦上,就失去跨片 join 和跨片交易,複雜度陡增。「能不分就不分」是正解。

### 保證與不保證

| 關聯式 DB 保證 | 不保證 |
|---|---|
| ACID 交易、join、強一致 | 無痛水平擴展(寫擴展要分片,代價大) |
| 成熟、可預測、工具齊全 | 無限連線(pool 上限是硬牆) |
| 讀副本擴讀 | 讀副本即時一致(有 replication lag) |

### 面試追問

1. **「什麼時候用 SQL 而不是 NoSQL?」**——要交易/join、規模中小、schema 穩定;先估規模,別過早分片。
2. **「讀副本能解決寫瓶頸嗎?」**——不能,只擴讀;且有 replication lag,read-after-write 要走主庫。
3. **「DB CPU 很閒但請求卡住,可能是什麼?」**——connection pool / max_connections 打滿;用 PgBouncer 復用連線。

---

## 8. 串流處理 Flink(短章)

**一句話定位**:**有狀態的分散式串流處理引擎**,提供事件時間語意 + exactly-once。深入實作見 [data-intensive-app-flink/README.md](../data-intensive-app-flink/README.md) 與 [dcard-interview-kappa/README.md](../dcard-interview-kappa/README.md),這裡只給面試摘要。

### 核心概念摘要

- **checkpoint**:Flink 定期對所有 operator 的狀態做一致性快照(Chandra-Lamport barrier 演算法:barrier 隨資料流動,每個 operator 收到 barrier 就存自己的狀態)。掛掉後從最近 checkpoint 恢復。
- **exactly-once**:靠 checkpoint(恢復狀態不重複計算)+ 對 source 可重播(Kafka offset)+ 對 sink 用交易/冪等(two-phase commit)。**注意:exactly-once 是「狀態/輸出的效果只算一次」,不是「訊息只處理一次」**——內部仍可能重播,靠去重達成效果一次。
- **watermark**:處理亂序/遲到事件的機制(接 [handling §10 廣告點擊統計](handling-unfamiliar-topics.md))。watermark = 「我認為 T 之前的事件都到齊了」的水位線,推進到超過 window 結束就關窗計算。遲到更久的走 side output 或觸發更新。核心 tradeoff:等越久越準但延遲越高。
- **何時 Kafka Streams 就夠**:不需要獨立叢集、輸入輸出都在 Kafka、狀態不大、團隊想要「就是個 Java library 嵌在 app 裡」→ Kafka Streams(或 ksqlDB)夠了。要跨 source/sink、超大狀態、複雜事件時間、要獨立擴展運算資源 → 上 Flink。

### 面試追問

1. **「Flink 怎麼做到 exactly-once?」**——checkpoint 快照狀態 + 可重播 source + 交易/冪等 sink;是效果一次不是處理一次。
2. **「watermark 解決什麼問題?」**——事件亂序/遲到下「window 何時能關」;水位線是「這時間前的都到齊了」的估計,等越久越準越慢。
3. **「Flink vs Kafka Streams?」**——Kafka Streams 是嵌入式 library、綁 Kafka;Flink 是獨立叢集、跨 source/sink、大狀態、獨立擴展。

---

## 9. ClickHouse / OLAP(短章)

**一句話定位**:**columnar + 向量化的 OLAP 引擎**,為「掃海量列做聚合分析」而生,不是為「查/改單筆」的 OLTP。實作見 [dcard-interview-kappa/README.md](../dcard-interview-kappa/README.md)。

### 內部機制與重點

**(a) columnar + 向量化為什麼快(接 [arch-01 cache line](../../docs/cs-fundamentals/arch-01-cpu-memory-and-numerics.md))**

```
  row store(OLTP):一列的所有欄位存在一起
    → 查「一個 user 的全部欄位」快;但「所有 user 的 age 平均」要掃過每一列的所有欄位
  column store(OLAP):同一欄的所有值存在一起
    → 算 avg(age) 只讀 age 那一欄,其他欄完全不碰
```

三個硬體級好處:
- **只讀需要的欄**:分析常只碰幾欄,columnar 直接跳過其餘,I/O 大減。
- **cache line 用滿 + SIMD**:同欄同型別連續存放,一條 [64-byte cache line](../../docs/cs-fundamentals/arch-01-cpu-memory-and-numerics.md) 裝滿有用資料,CPU 能用 SIMD 一次算多個(向量化)——不像 row store 每讀一列都夾帶用不到的欄位污染 cache。
- **壓縮率高**:同欄同型別、值相近,壓縮比行式好得多(省 I/O 又省儲存)。

**(b) MergeTree / ReplacingMergeTree**(接 [kappa README](../dcard-interview-kappa/README.md)):ClickHouse 的核心引擎家族,本質也是 **LSM 精神**——資料寫成不可變的 data part,背景 merge。`ReplacingMergeTree` 在 merge 時對相同排序鍵**去重保留最新**(做「最新狀態」表),但**去重只在 merge 時發生、非即時**,查詢要加 `FINAL` 或自己聚合才保證看到去重結果——這是 ClickHouse 常見誤解。

**(c) OLAP vs OLTP 判準**

| | OLTP(Postgres) | OLAP(ClickHouse) |
|---|---|---|
| workload | 大量小交易、查改單筆 | 少量大查詢、掃海量列聚合 |
| 儲存 | row store | column store |
| 寫 | 逐筆、要 ACID | 批次灌入、不擅長高頻單筆改 |
| 面試判準 | 交易系統、業務主庫 | 報表、分析、事件統計、儀表板 |

### 保證與不保證

| ClickHouse 保證 | 不保證 |
|---|---|
| 極快的大範圍聚合掃描 | 高頻單筆 update/delete(不擅長) |
| 高壓縮比、省儲存 | 完整 ACID 交易 |
| 水平擴展分析吞吐 | 即時去重(ReplacingMergeTree 靠 merge,非即時) |

### 面試追問

1. **「ClickHouse 為什麼分析快?」**——columnar 只讀需要的欄 + cache line 用滿 + SIMD 向量化 + 高壓縮;對照 row store 掃聚合要拖著全部欄位。
2. **「OLAP 和 OLTP 差在哪,怎麼選?」**——交易/查改單筆用 OLTP(Postgres);掃海量列做聚合報表用 OLAP(ClickHouse)。
3. **「ReplacingMergeTree 查出來還有重複?」**——去重只在背景 merge 發生、非即時;要加 `FINAL` 或查詢時聚合。

---

## 組件選型速查表

| 需求 | 首選 | 次選 | 判準(一行) |
|---|---|---|---|
| 事件流 / 解耦 / 可重播 | Kafka | Pulsar / Kinesis | 要持久 log + 多消費者重播就 Kafka;超簡單佇列才用 Redis/RabbitMQ |
| 快取 / 計數 / 排行榜 / 限流 | Redis | Memcached | 要資料結構(ZSET)和持久選 Redis;純 LRU 字串快取 Memcached 夠 |
| leader 選舉 / 分散式鎖(強) / config | etcd / ZooKeeper | Consul | 需要全體同意的一小塊強一致真相;寫量必須小 |
| 快 + 弱一致的鎖 / rate limit | Redis | — | 能容忍偶爾雙持有、要低延遲 |
| 寫重 / 水平擴展 / 多 DC / 無 join | Cassandra | DynamoDB / Scylla | 查詢模式固定、不需交易/join、寫吞吐是瓶頸 |
| 全文搜尋 / log 分析 | Elasticsearch | OpenSearch | 要 inverted index 搜尋;但真相另存,ES 只當可重建索引 |
| 大 blob / 資料湖 / 備份 | S3 | GCS / MinIO | 便宜高 durability、不需 POSIX;小檔要 compaction |
| 交易 / join / 中小規模真相 | PostgreSQL | MySQL | 要 ACID、關聯查詢;先估規模別過早分片 |
| 有狀態串流 / 事件時間 / EOS | Flink | Kafka Streams | 跨 source/sink、大狀態、獨立擴展用 Flink;綁 Kafka 的嵌入式用 KStreams |
| 分析報表 / 事件聚合 / 儀表板 | ClickHouse | Druid / BigQuery | 掃海量列聚合;不擅長高頻單筆改 |

---

## 自測 checklist(能口頭答出就過)

1. Kafka 高吞吐三件套是什麼?開了 TLS 為什麼會破壞其中一項?
2. `acks=all` 就保證不丟資料嗎?`min.insync.replicas` 補了什麼洞?unclean leader election 開/關各在 CAP 哪一邊?
3. consumer group 的有效平行度公式?為什麼 partition 只能加不能減、同 key 為何要進同 partition?
4. Redis 單執行緒為什麼夠快?列三個會卡死主執行緒的操作。做排行榜/延遲佇列各用什麼結構?
5. Redis Cluster 為什麼 multi-key 操作受限?hash tag 怎麼解?sentinel 和 cluster 各解決什麼?
6. 為什麼 ZK/etcd 的寫入量不能大?這對 K8s(etcd)和 Kafka(舊版 ZK)意味著什麼?
7. 用「過半(quorum)」故事講 Raft 怎麼避免 split-brain?3 台能容忍掛幾台、為什麼奇數?
8. 分散式鎖 ZK/etcd vs Redis 的判準是什麼?ephemeral node / lease 和 fencing token 各解決什麼?
9. LSM-tree 寫路徑為什麼寫快?代價(讀 + compaction)是什麼?對照 B-tree 的取捨?
10. W+R>N 為什麼保證讀到最新?ES 為什麼是 near-real-time、深分頁為什麼慘?S3 為什麼沒有原子 rename、presigned URL 解決什麼?
