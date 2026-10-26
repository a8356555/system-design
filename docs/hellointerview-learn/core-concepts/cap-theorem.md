# CAP Theorem
> 來源：https://www.hellointerview.com/learn/system-design/core-concepts/cap-theorem ｜ 分類：core-concepts

## 一句話重點
分散式系統中 partition tolerance 是必選，所以 CAP 實務上只是一個問題：網路分區時要一致性還是可用性？在 non-functional requirements 階段就該問，且常「依功能分開選」。

## 核心內容

### 什麼是 CAP
分散式系統三項只能取二：
- **Consistency**：所有節點同一時間看到相同資料；對任一節點寫入後，之後任何節點的讀取都回傳更新值。（注意：與 ACID 的 consistency 不同。）
- **Availability**：對每個未故障節點的請求都會得到回應，但不保證是最新版本。
- **Partition Tolerance**：即使訊息任意遺失或部分系統故障（節點間網路分區），系統仍能運作。

關鍵洞察：網路故障一定會發生，P 是必須的，所以實際上 = **分區發生時選 C 還是 A**。

### 範例：美國 / 歐洲兩台 server
- 使用者 A 在美國 server 改顯示名稱 → 複製到歐洲 server → 歐洲的 B 看到新名字。
- 網路分區（美歐連線斷）時，B 要看 A 的 profile：
  - Option A：回傳錯誤，因為無法保證最新（選 Consistency）。
  - Option B：顯示可能過期的資料（選 Availability）。
- 此例答案很明顯：寧可看到舊名字也不要錯誤 → 選 A。

### 何時選 Consistency
- **訂票系統**：A 訂了 6A，分區時 B 仍看到可訂並訂走 → 兩人搶同座位。
- **電商庫存**：Amazon 只剩一支牙刷，分區期間多人看到有貨 → 超賣。
- **金融系統**：交易平台 order book 必須準確，stale 資料導致錯誤價格成交。

### 何時選 Availability
多數系統可容忍不一致，採 **eventual consistency**（幾秒到幾分鐘後一致）：
- 社群媒體（舊大頭貼看幾分鐘無妨）、Netflix 影片描述、Yelp 營業時間（略舊的資訊好過沒有）。
- 判準問題：「使用者短暫看到不一致資料是否會造成災難？」是→C；否→A。

### 面試中的使用
- 在 non-functional requirements 階段就把它當起點：「這個系統優先 consistency 還是 availability？」

**偏 Consistency 的設計**
- Distributed transactions（如 two-phase commit，讓 cache 與 DB 等多個 store 同步）：複雜、延遲較高。
- Single-node 方案：單一 DB instance，沒有傳播問題，但限制 scalability。
- 技術：傳統 RDBMS（PostgreSQL, MySQL）、Google Spanner、DynamoDB（strong consistency mode）。

**偏 Availability 的設計**
- 多個 read replicas + 非同步複製：任一 replica 可服務讀取，換取可能 stale。
- Change Data Capture (CDC)：追蹤主 DB 變更非同步傳播到 replicas、caches 等，主系統保持可用。
- 技術：Cassandra、DynamoDB（multi-AZ 配置）、Redis clusters。
- 多數現代分散式 DB 兩者皆可設定，重點是知道自己的 use case 要哪個。

### 進階（senior / staff）
**同一系統不同功能選不同取捨**
- Ticketmaster：訂位需強一致（防重複訂位）；瀏覽活動詳情可偏可用性。話術：「訂票交易優先 consistency，瀏覽與檢視活動時優化 availability。」
- Tinder：配對需一致（雙方幾乎同時右滑應立刻都看到 match）；看 profile 可偏可用（舊頭貼可接受）。

**一致性光譜**
| 模型 | 說明 | 備註 |
|---|---|---|
| Strong | 所有讀取反映最新寫入 | 效能成本最高；銀行餘額等需絕對準確 |
| Causal | 有因果關係的事件對所有人順序一致 | 例：留言必須出現在貼文之後 |
| Read-your-own-writes | 使用者馬上看到自己的更新，別人可能仍看舊的 | 社群平台常用 |
| Eventual | 隨時間趨於一致，期間可能不一致 | 最寬鬆；DNS；多數分散式 DB 預設；選 availability 即隱含此項 |

## 面試怎麼用
- 何時：NFR 階段的第一批議題之一。
- 怎麼說：「Does every read need to read the most recent write?」是→consistency，否→availability。然後說明對應設計（transactions / 單節點 vs replicas / CDC）。
- 加分：依功能拆分（booking 強一致、browse 高可用）；提 read-your-own-writes 這類細緻模型。
- 陷阱：把 CAP 的 C 與 ACID 的 C 混為一談；說「CA 系統」（P 不可放棄）；整個系統一刀切選一邊；選了一致性卻不說會增加延遲/降低可用性的代價。

## 關鍵數字
原文無具體數字。

## 相關題目
- [ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)（booking vs browse）
- [tinder](../../hellointerview-breakdowns/tinder.md)（matching vs profile）
- [yelp](../../hellointerview-breakdowns/yelp.md)
- [payment-system](../../hellointerview-breakdowns/payment-system.md)

## 自測問題
1. 為何說 CAP 實務上只是 C vs A 的選擇？答：分散式系統網路分區必然發生，P 必選，所以分區時選一致或可用。
2. CAP 的 consistency 與 ACID 的 consistency 一樣嗎？答：不同；CAP 指各節點看到相同最新資料。
3. 何時必須選 consistency？答：訂票、庫存、金融等 stale 會造成災難性後果的場景。
4. 偏可用性的設計手段？答：多 read replicas + async replication、CDC、Cassandra / DynamoDB multi-AZ。
5. Ticketmaster 如何同時有 C 與 A？答：訂位走強一致防重複訂位；瀏覽活動資訊走高可用，容忍輕微過期。
