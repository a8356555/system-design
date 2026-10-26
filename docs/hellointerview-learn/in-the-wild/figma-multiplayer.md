# How Figma Built Multiplayer Editing on Simplified CRDTs
> 來源：https://www.hellointerview.com/learn/system-design/in-the-wild/figma-multiplayer ｜ 分類：in-the-wild ｜ 原始 eng blog：Figma Engineering（Evan Wallace），2019-10-16（https://www.figma.com/blog/how-figmas-multiplayer-technology-works/）

## 一句話重點
Figma 不用 OT 也不用完整 CRDT：文件是 object tree，每個 property 是 last-writer-wins register（「後到 server 者贏」），並讓每份文件由單一 server process 處理所有編輯，把「演算法難題」換成「基礎設施難題」。

## 背景與問題（規模、痛點）
- Figma 2016-09 推出 multiplayer；3 年後 Evan Wallace 發表同步機制說明。
- 需求：所有 client 最終收斂到相同文件；編輯要即時（client 立即套用本地變更，之後再同步，期間兩份副本短暫不一致）；支援離線（不同步窗口從秒拉長到數小時）；文件是樹（frame 含 shape 含 text），兩人同時重構樹可能把同一物件移到兩個不同 frame，不能出現複製或遺失。
- OT 被排除：要把每個編輯表示成 operation 並對並行操作做 transform，正確性證明複雜易錯（引 Li and Li：連只有 insert/delete 兩種 primitive 的 OT 都很難證明），設計文件的操作種類遠多於兩種。
- 完整 CRDT 的複雜度大多是為了去中心化環境（timestamp、刪除要留 tombstone 等 metadata），但 Figma 有中央 server。

## 演進過程（舊架構 → 哪裡爆 → 新架構，保留原文數字）
原文是設計推導，非舊新架構遷移：
1. 選項：OT vs CRDT。
2. CRDT 的 LWW register：每次寫入帶 timestamp，merge 取較新者。
3. 因所有編輯都經過中央 server，由 server 決定順序 -> 去掉 timestamp 與大部分 bookkeeping；「last」改為「最後到達 server」。
4. 結果：文件 = `Map<ObjectID, Map<Property, Value>>`，每個 property 是無 timestamp 的 LWW register = simplified CRDT。
5. 後續產業演進（原文結論）：此設計成為慣例並成為產品類別，如 Zero、Linear 的 sync engine（server 排序 optimistic mutation + per-property LWW）；一個文件一個 process 現在是 Cloudflare Durable Objects 的原語；並行文字編輯仍需真正 CRDT（Yjs 是預設）。

## 關鍵設計決策與取捨（這是主體，寫細）
- **Property 為原子單位**：不同 property 的並行編輯都保留（改顏色 + 改大小皆成功）；同 property 衝突則後到 server 者贏。文字 property 一邊改成 AB、一邊改成 BC，結果是 AB 或 BC，絕不會是 ABC。對文字編輯器不可接受，但對視覺物件合理（紅藍沒有合理的合併）。
- **Client 端閃爍問題**：本地先套用但 server 尚未 ack，可能先看到對方舊值覆蓋自己，ack 後又變回來。解法：client 丟棄與自己「未確認寫入」衝突的 incoming 變更。
- **建立 / 刪除**：建立 = map 新增 entry，client 自己產生 object ID 並內嵌 client ID，確保不碰撞（可離線建立）。刪除 = 直接移除整個 entry（不留 tombstone，因為文件存活多年，記住所有刪除會無限膨脹）。property write 永遠不能創建物件，所以對已刪除 ID 的過期編輯會落空被丟棄。誤刪靠 client 端 undo history 保留的 properties 還原。
- **Reparenting（Wallace 稱最複雜）**：不是 delete + recreate（會產生新 ID，並行的改色就遺失），而是把 parent 當成子物件上的普通 property。移動只是一次 property write、物件身分不變，其他 property 的並行編輯不受影響；一個 property 只有一個值，所以不可能有兩個 parent（不會複製）。
- **防循環**：A.parent=B 與 B.parent=A 各自合法但合起來成環；逐 property 檢查抓不到，所以 server 拒絕會造成 cycle 的 parent 更新；client 樂觀套用時暫時隱藏成環物件，等 server 回應。
- **兄弟排序**：用 1,2,3 整數排序，插入中間要重編號一堆（易衝突）。改用 0~1 之間的分數 position，插入兩兄弟之間取平均（0.25 與 0.5 之間 -> 0.375），其他不用改寫。parent 與 position 一起原子寫入：`set("parent", { parentID, position })`。
- **每份文件一個 server process**：「最後到達 server」只有在單一地方看到所有寫入時才有意義。開文件時下載完整副本，之後一條 WebSocket 連到該 process。無跨 server 協調。
- **重連 = 重新下載**：斷線不嘗試 resume，重新下載文件、把離線期間的編輯 replay 在新副本上、開新 socket。離線 4 小時與斷線幾秒沒差別，離線支援免費。
- **核心取捨**：用基礎設施複雜度換演算法簡單。要處理 process 的啟停、client 找到正確 process、node 掛掉時文件換家而不能有兩個 process 同時接受寫入；但問題縮小為「每個文件由誰擁有」（每個 session 一次），而不是「每個編輯的跨 server 排序」。
- **明確放棄**：同時的文字編輯不最佳化。

## 面試怎麼用（這個案例可以拿來支撐哪類題目的哪個論點）
- 協作編輯題（Google Docs / 白板 / 設計工具）：為何選 central server + LWW 而非 OT/CRDT；依「資料型態」決定衝突解法（文字 vs 結構化 property）。
- Real-time updates：「同文件路由到同一 server」vs「pub/sub 讓 client 連任一 server」的取捨。
- 樹狀資料的並行修改：parent 當 property、server 驗證 invariant、fractional indexing。
- 離線支援：重連即重新同步，簡化 session 狀態。

## 相關題目
- [Google Docs](../../hellointerview-breakdowns/google-docs.md)（OT vs CRDT 的文字編輯對照）
- [Dropbox](../../hellointerview-breakdowns/dropbox.md)（同步與衝突）
- [FB Live Comments](../../hellointerview-breakdowns/fb-live-comments.md)（real-time 推送）

## 自測問題（3-5 題附簡答）
1. Figma 為何不用 OT？ 答：OT 要 transform 並行操作，case 覆蓋複雜、證明易錯，設計文件操作種類遠多於文字的 insert/delete。
2. 為何能省掉 CRDT 的 timestamp 與 tombstone？ 答：有中央 server 排序，「last」就是最後到 server；刪除直接移除 entry，stale 編輯找不到 ID 即丟棄。
3. 為何 reparent 不用 delete + recreate？ 答：新 ID 會讓並行編輯遺失；把 parent 當 property 則身分不變，且單值保證不會有兩個 parent。
4. 逐 property LWW 保證不了什麼？怎麼補？ 答：保證不了樹無環；server 拒絕造成 cycle 的 parent 更新，client 暫時隱藏成環物件。
5. 一份文件一個 process 的代價？ 答：要做路由、process 生命週期管理、故障轉移且不能有兩個 writer；換得的是不必跨 server 排序每個編輯。
