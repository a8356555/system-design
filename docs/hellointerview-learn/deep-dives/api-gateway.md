# API Gateway
> 來源：https://www.hellointerview.com/learn/system-design/deep-dives/api-gateway ｜ 分類：deep-dives

## 一句話重點
API Gateway 是微服務架構的單一入口：核心是 request routing，順帶處理 auth / rate limiting 等 middleware。面試中一句話帶過（"I'll add an API Gateway to handle routing and basic middleware"）就走，花太多時間講它反而是錯誤。

## 它是什麼 / 核心機制
- 比喻：飯店櫃檯。客戶端不需要知道內部微服務結構，gateway 集中管理路由與橫切關注點（cross-cutting concerns）。
- 隨微服務興起而出現；是 thin、相對簡單的元件，通常 stateless。
- 原文提醒：很多候選人只強調 middleware，卻沒提到引入 gateway 的核心理由——request routing。

### 一個 request 的流程
1. Request validation：檢查 URL、必要 header、body 格式；格式錯誤或缺 API key 直接擋掉，省下後端資源。
2. Middleware：auth（JWT）、rate limiting、SSL termination、logging/monitoring、response compression、CORS、IP whitelist/blacklist、request size 驗證、timeout、API versioning、throttling、service discovery 整合。面試最相關的是 authentication、rate limiting、IP 黑白名單。
3. Routing：routing table 依 URL path、HTTP method、query parameter、header 的組合對應到後端服務（例：`/users/*` -> user-service:8080）。
4. Backend communication：多數 HTTP；後端若用 gRPC，gateway 可做協定轉換（實務上較少見）。
5. Response transformation：把後端回應轉成 client 要的格式（例：client 發 HTTP GET，gateway 轉內部 gRPC 呼叫，再把 gRPC 回應轉 JSON）。
6. Caching（選用）：適合常讀、少變、且「非 user-specific」的資料。策略：full response caching、partial caching、cache invalidation（TTL 或 event-based）；可放 in-memory 或 Redis 等 distributed cache。

## 何時用 / 何時不用
- 用：微服務架構。沒有 gateway，client 要知道並直接呼叫多個服務，造成耦合與複雜的 client code。
- 不用：簡單 monolith 或單一 client 類型的 client-server 架構，加 gateway 只是多餘複雜度。
- 結論：gateway 不是最有趣的元件；講太多的風險遠大於講太少。

## 面試常考的進階點
- **水平擴展**：gateway stateless，多開 instance 放在 load balancer 後面。
- **兩層 load balancing 的區別**：
  - Client -> Gateway：專用 LB（AWS ELB、NGINX）。
  - Gateway -> Service：gateway 自己可對後端 instance 做 LB。
  - 面試中可畫成單一方塊「API Gateway + Load Balancer」，不必糾結入口細節。
- **全球分散部署**：像 CDN 一樣把 gateway 放近使用者。Regional deployments + GeoDNS 導到最近 gateway + 跨區 configuration sync（路由規則與政策需一致）。
- **Middleware 要有目的**：提到時說明為什麼（auth、rate limit、IP 黑白名單最常見），不要逐項羅列。
- **Caching 的邊界**：只快取非 user-specific、同輸入同輸出的結果。
- **Gateway 與 LB 的角色分工**常被追問：gateway 做 L7 路由與 middleware，LB 做流量分配（分工說明為原文整理）。
- （補充）Gateway 本身是 SPOF 與延遲增加點，所以要多 instance + 健康檢查；auth 邏輯集中也意味著 gateway 掛了整個入口掛掉。

## 常見產品
- Managed（最省事但最貴）：AWS API Gateway（REST/WebSocket、throttling、API key 與 usage plan、Lambda 整合、CloudWatch）、Azure API Management（OAuth/OpenID Connect、policy 設定、developer portal）、Google Cloud Endpoints（GCP 整合、gRPC、自動 OpenAPI 文件）。
- Open source：Kong（基於 NGINX、plugin 生態）、Tyk（原生 GraphQL、analytics、multi-data center）、Express Gateway（Node.js、輕量）。

## 關鍵數字
原文無特定數字。

## 相關題目
- [WhatsApp](../../hellointerview-breakdowns/whatsapp.md)
- [Uber](../../hellointerview-breakdowns/uber.md)
- [Distributed Rate Limiter](../../hellointerview-breakdowns/distributed-rate-limiter.md)
- （補充）幾乎所有微服務題都會出現 gateway，原則是一句帶過。

## 自測問題
1. 引入 API Gateway 的核心理由是什麼？
   - Request routing；middleware（auth、rate limiting 等）是附加價值。
2. 什麼情況不該加 API Gateway？
   - 簡單 monolith 或單一 client 類型的 client-server 架構。
3. 如何擴展 gateway 並降低全球使用者延遲？
   - Stateless 水平擴展 + LB；多區域部署 + GeoDNS + 路由設定同步。
4. Gateway 的 response caching 適用什麼資料？
   - 常讀、少變、非 user-specific 的資料；用 TTL 或 event-based invalidation。
5. 面試中該花多少時間講 gateway？
   - 一句話：負責 routing 與基本 middleware，然後繼續往下。
