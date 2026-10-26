# Proximity Search
> 來源：https://www.hellointerview.com/learn/system-design/deep-dives/proximity-search ｜ 分類：deep-dives

## 一句話重點
一維排序無法保留二維鄰近性；解法有兩條路：幾何資料用 spatial tree（R-tree / BKD），會動的點用 encoded key（geohash / S2 / H3）塞進一般 index。index 只產生 candidate set，最後一定要用精確距離 post-filter。

## 它是什麼 / 核心機制

### 為什麼一般 B-tree 不行
- 年齡查詢快：B-tree 把相近 key 排在同一 page，range 查詢 = 一次 seek + 短 sequential read。
- 經緯度是兩個數字，B-tree 只能對一個維度排序。單欄 index 只拿到一條橫帶/直帶；composite index 也只是先排第一欄、再用第二欄打破平手，仍等於一維排序，帶子裡仍有數百萬 row 且未依距離排序 → 退化成逐列算距離的 brute force。
- 根本原因：一維排序無法保留二維的 closeness。
- 通則：spatial index 把「檢查每一列」變成「檢查小 candidate set」，再用精確距離/幾何運算收尾。

### 路線 A：Custom Spatial Trees
把樹做成像 B-tree 一樣適合 disk（balanced、page 大小的節點、可預測深度）。三者是一條「修補鏈」：

**Quadtree**
- 地圖 = root，切成 4 象限；象限內點太多就遞迴再切；點只存在 leaf。
- 查詢：從 root 往下比較中點，落到 leaf；candidate = 該 leaf + 鄰近 leaf（避免漏掉跨邊界的點）。
- 優點：自適應密度（Manhattan 很深、湖面一個粗格）。
- 問題 1 深度：永遠在幾何中點切、不是資料所在處，密集區要切十幾層，鄉下只要 2 層 → latency 取決於查詢位置，最忙的區域最慢，worst case 難推。
- 問題 2 磁碟：pointer structure，每個 pointer 可能是一次 random read；放 RAM 沒事，放 disk 就卡 I/O。
- 仍廣泛用於記憶體（Google Maps tiles、遊戲碰撞偵測）。

**k-d tree / BKD tree**
- 每層輪流切 x、y、x…，二元樹；在 median 切 → 永遠平衡、深度 log(n)。
- 與 quadtree 差異：切 median（點數對半）而非幾何中點（面積對半）；十個司機九個擠在東邊的例子，quadtree 要反覆切空地，k-d tree 一刀切在人群中央。
- 同樣的 disk 問題（全是 pointer）。
- BKD tree（block k-d）：點打包成 disk page 大小的 block，整棵樹一次建好 → 實質 write-once，適合不變的資料。Elasticsearch 的 geo field 用的就是它。

**R-tree**
- 第一個從頭為 on-disk database 設計的 spatial index，解決兩件事：形狀（線、多邊形，不只點）與 disk。
- Minimum Bounding Rectangle (MBR)：每個物件用平行座標軸的最小矩形包起來；點 = 寬高為零的退化矩形；附近矩形再被更大矩形包住，一路巢狀到 root。
- 像 B-tree：所有 leaf 同深度、節點大小 = 一個 disk page、insert/delete 以 split/merge page 維持平衡。
- 取捨：矩形可重疊 → 查詢點落在兩個矩形內就要兩邊都下鑽；插入策略差 → 重疊多 → 變慢。實務用 R*-tree（更聰明的 insertion heuristic 降低重疊）。
- 實作：PostGIS（Postgres GiST framework，R-tree 式 bounding box）、SQLite、Oracle Spatial。

### 路線 B：Encoded Keys
把 lat/long 轉成 cell ID / 可排序 key，用一般 index（B-tree）縮小到一小塊地圖。好處：重用每個 DB 都有的基礎設施，不需 spatial extension。

**Geohash**
- Space-filling curve：一條線穿過 2D 空間，地圖上近的點在線上也近。
- 世界切成 32 格，每格一個字元；再遞迴切 32 格。5 字元約 5 km 寬，9 字元約 5 m。
- 本質是 bits：每字元 5 bits，`dr5ru` = 25 bits；同樣 bits 讀成整數即可。故 Redis 存 52-bit integer，Postgres 存 text，行為一致。
- 共享 prefix 通常很近 → `WHERE geohash LIKE 'dr5ru%'` 就是 B-tree prefix scan。共享 5 字元 = 同一個約 5 km 的框，6 字元約 1 km。
- Redis：GEOADD 把 lat/long 交錯成 52-bit geohash integer 當 sorted set 的 score；nearby 查詢 = ZRANGEBYSCORE。
- 邊界陷阱：相距 1 公尺的兩點可能跨 cell 而 prefix 完全不同（例：`dr5ru` 邊緣的 rider，最近司機在鄰格 `dr5rg`）。
- 標準解 3x3 trick：算出自己的 cell + 8 個鄰格，9 格一起查，再用精確距離 post-filter 掉角落太遠的。

**S2**
- geohash 把經緯度當平面矩形，但 1 度經度在赤道約 111 km、極點趨近 0 → 赤道是胖方塊、北方是細長條；全球尺度需要等面積 cell。
- Google S2：把地球包進立方體、投影到六個面，cell 大小各地大致相同；64-bit 階層式 ID，截斷即得 parent cell。
- 理解球面，能處理平面格子處理不好的情況（如跨 antimeridian 的 polygon）。MongoDB 2dsphere index 的底層。

**H3**
- Uber 開源，用於 dispatch 與 surge pricing；六邊形。方形有兩種鄰居（4 邊鄰 + 4 角鄰，距離不同），讓「N 圈內」查詢與熱力圖雜亂；六邊形 6 個鄰居距離大致相同。
- 同樣是 64-bit 階層 ID。
- 關鍵差異：geohash/S2 沿 space-filling curve 排列，numeric range scan 能一次掃出一個鄰域；H3 不是，ID 相近不保證地圖上相近。改用 grid math 直接算出周圍 ring 的 cell ID，再逐一查。
- Dispatch 模式：driver snap 到 H3 cell（例 200 m）→ rider 開 app 取自己的 cell + 周圍 ring（不夠再多一圈）→ `WHERE h3_cell IN (...)`（一般整數 index）→ 精確距離 post-filter。寫入便宜、候選產生便宜、不需 spatial extension。

## 何時用 / 何時不用
- 資料是幾何（polygon、道路、配送區、containment / intersection）→ Custom spatial tree；PostGIS（GiST R-tree）是預設，R-tree 點線面通吃。代價：spatial extension + 較貴的寫入。
- 資料主要是持續移動的點（driver、user、device）→ Encoded cells（geohash/S2/H3）。移動的司機 = 一次整數更新，可擴展到每秒數百萬寫入。代價：基本只限點；因 cell 邊界永遠要查一圈鄰格。
- 口訣：Spatial tree for shapes. Encoded cells for moving points. And always post-filter.

## 面試常考的進階點
1. **為什麼不能用 composite index (lat, long)**：B-tree 實質只對單維排序，帶狀結果沒有距離排序 → 這是開場必答。
2. **寫入頻繁的位置更新**：R-tree 重平衡矩形有成本；BKD 實質 write-once，都不愛 churn 的資料。encoded key 的移動 = 改一個整數（原文結論）。
3. **邊界問題**：geohash 的 3x3 查詢 + post-filter；H3 的 ring lookup；所有 encoded-key 索引都做某版本的「查一圈 + post-filter」。
4. **Cell 精度選擇**：geohash 字元數 / H3 resolution 決定 cell 大小；cell 大小應與查詢半徑匹配，不夠再擴一圈（H3：多取一個 ring）。
5. **全球一致性**：geohash 在高緯度變形 → 全球系統考慮 S2 / H3。
6. **Quadtree 的 worst-case**：密集區深度大導致 latency 不均；median split (k-d) 才能保證 log(n)。（補充）實務上 quadtree 常用「每格容量上限」來決定何時分裂。
7. **Elasticsearch geo = BKD tree**：不是專用 quadtree；批次建構、不可變 segment。
8. **面試策略**：不必硬背 H3 vs S2 vs geohash 名稱；重點是說明為何一般 index 失敗，挑「無聊但可用」的 production 選項並口述取捨。
9. Redis geospatial：本質是 sorted set + 52-bit geohash score，GEOADD / 範圍查詢。

## 關鍵數字
- Geohash：5 字元 ≈ 5 km，6 字元 ≈ 1 km，9 字元 ≈ 5 m；每字元 5 bits（32 選項）。
- Redis geohash = 52-bit integer。
- 1 度經度赤道 ≈ 111 km，極點 → 0。
- S2 / H3 ID 為 64-bit；H3 dispatch 範例 cell ≈ 200 m。

## 相關題目
- [Uber](../../hellointerview-breakdowns/uber.md)
- [Yelp](../../hellointerview-breakdowns/yelp.md)
- [Gopuff](../../hellointerview-breakdowns/gopuff.md)
- [Tinder](../../hellointerview-breakdowns/tinder.md)

## 自測問題
1. 為什麼 (lat, long) composite B-tree index 無法有效回答「2 km 內的司機」？
   答：B-tree 只依第一欄排序、第二欄僅打破平手，等於一維排序；回傳的帶狀區域含數百萬列且無距離順序，退化成逐列算距離。
2. Quadtree 與 k-d tree 的切法差在哪？各自的問題？
   答：quadtree 切幾何中點（面積），密集區要切很深、latency 隨位置不同；k-d tree 切 median，維持 log(n) 深度。兩者皆為 pointer 結構，不適合 disk；BKD 以 page 大小 block + 一次建好解決。
3. Geohash 的邊界問題是什麼？如何處理？
   答：相鄰兩點可能落在不同 cell、prefix 完全不同；查自己 cell + 8 鄰格（3x3）再用精確距離 post-filter。
4. H3 與 geohash/S2 查詢方式有何根本差異？
   答：geohash/S2 沿 space-filling curve，range scan 可掃鄰域；H3 的 ID 相近不保證地圖相近，改用 grid math 算 ring 的 cell ID 再 IN 查詢。
5. 司機位置高頻更新，選 PostGIS 還是 H3？
   答：以點為主、寫入密集 → encoded cells（整數更新、不需 extension）；需要 polygon containment（配送區）才用 PostGIS/R-tree。
