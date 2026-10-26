# GitHub Apps JWT 認證（Generating a JWT for a GitHub App）
> 來源：https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app ｜ 類別：Auth / Token 設計（非 Hello Interview 題目，為 GitHub 官方文件）

## Threads 貼文觀點
來源：https://www.threads.com/@chunhao2026/post/Dejwd3WgWIM

- **兩層 token**：
  1. **RS256 JWT**（最長 10 分鐘）：證明「我是這個 app」（身分）。
  2. 用 JWT 交換 **installation token**（1 小時）：授權「能對哪些資源做什麼」（範圍）。
- **Private key 只在交換（簽 JWT）時使用**，日常 API 呼叫用短效 token，降低 private key 曝險面。
- **iat 往回推 60 秒**，處理 clock drift（伺服器與 GitHub 時鐘不同步）。
- 備註：官方這份文件只涵蓋 JWT；「installation token 1 小時」來自貼文與其他 GitHub 文件，不在此來源文字內。

## 一句話核心
用長效、極少使用的非對稱私鑰簽出短效 JWT 證明 app 身分，再換成短效、有範圍限制的 installation token 去做實際工作，使可外洩的東西都是短命且低權限的。

## 問題情境
- 一個 GitHub App 要以「app 本身」身分呼叫部分 REST API，或要產生 installation access token 去存取某個 installation（安裝在某 org / repo）的資源。
- 限制與風險：
  - 不能把長效 secret 放在每個請求中傳送。
  - 驗證方（GitHub）要能用公鑰驗證，而不持有 app 的私鑰。
  - 簽發端與驗證端時鐘可能不一致。
  - token 外洩時，損害要被時間與範圍雙重限制。

## Core Entities & API
**Entities**：GitHub App（有 client ID / app ID 與 private key）、Installation、JWT、Installation access token。

**JWT 必要 claim（原文）**

| Claim | 意義 | 規則 |
|---|---|---|
| `iat` | Issued At | 建議設為 60 秒前以防 clock drift，並確保伺服器時間準確（例如用 NTP） |
| `exp` | Expires At | 不得超過未來 10 分鐘；過期後不能再用來要 installation token |
| `iss` | Issuer | app 的 client ID 或 app ID，GitHub 用它找對應公鑰驗簽；建議用 client ID |
| `alg` | 簽章演算法 | 必須是 `RS256` |

**使用方式**：放在 `Authorization: Bearer <JWT>`。一般 token 可用 `Bearer` 或 `token`，但 **JWT 一定要用 `Bearer`**。範例：`GET https://api.github.com/app`。

**前置**：需要 private key 與 app ID（可用 `GET /app` 查 app ID）。

## High-Level Design
```
[Your server]                                  [GitHub]
 private key (PEM) --RS256 sign--> JWT(iat=now-60, exp<=now+600, iss=clientId)
        |  Authorization: Bearer JWT
        v
   POST /app/installations/{id}/access_tokens ---> 以 iss 找公鑰驗簽
        <------------- installation token (約 1 小時，限定 installation 的權限範圍)
        |  之後的 API 用 installation token，private key 不再參與
```
（上方 installation token 端點與 1 小時效期為補充，原文本頁未列。）

官方範例語言：Ruby、Python、Bash（用 openssl 手工簽）、PowerShell；也可直接用 Octokit SDK，會自動產生並在過期後重新產生 JWT。

## Deep Dives

### 1) 為什麼用 RS256（非對稱）而不是共享 secret（HS256）
- 問題：GitHub 需要驗證你的身分，但不應持有你的簽章 secret。
- 好解：RS256，你持私鑰簽，GitHub 用 `iss` 找到公鑰驗證。私鑰從不離開你的環境。
- 取捨：私鑰管理責任在你（儲存、輪替）；簽章比 HMAC 稍慢，但低頻使用可忽略。

### 2) 為什麼要兩層 token
- 爛解：每次 API 呼叫都用 private key 簽的長效憑證 -> 曝險面大、洩漏等於永久失陷。
- 好解：JWT 只證明身分且最多 10 分鐘。
- 最佳解（貼文觀點）：JWT 再換 installation token（1 小時，限定範圍）。日常呼叫只用 installation token。
  - 身分（authentication）與授權範圍（authorization）分離。
  - 每個 installation 各自的 token，範圍隔離（補充）。
- 取捨：多一次交換與 token 快取 / 刷新邏輯；token 過期要重簽。

### 3) 為什麼 exp 上限 10 分鐘
- 限制被截獲 JWT 的有效時間；JWT 只用來換 token，不是長期使用的 session。
- 取捨：用戶端需要在每次要換 token 前重簽（Octokit 自動處理）。

### 4) Clock drift：iat 往回推 60 秒
- 問題：若你的時鐘比 GitHub 快，JWT 的 `iat` 在 GitHub 看來是「未來」，可能被拒。
- 做法：`iat = now - 60`；同時用 NTP 確保時間準確。
- 取捨：實際有效窗口被 60 秒吃掉一小段，且 `exp` 仍須在 `now + 10 min` 內（官方範例 `exp = now + 600`；`iat` 往前推，所以 exp 計算仍從當下算）。
- 備註：官方 Python 範例 `iat` 用 `int(time.time())` 沒有往回推，PowerShell 範例用 -10 秒；而 Ruby 與 Bash 範例用 -60。文件的「建議」是 60 秒。

## 關鍵數字
- JWT 最大效期：10 分鐘（`exp - now <= 600s`）。
- `iat` 偏移：60 秒（回推）。
- Installation token：1 小時（來自貼文，非本頁原文）。
- 演算法：RS256。

## 面試官期待
（此為官方文件非面試題，以下為補充的面試延伸）
- Mid：能說明為何用短效 token、非對稱簽章。
- Senior：能設計 token 交換流程、快取與刷新、處理時鐘誤差、私鑰儲存（KMS / HSM）。
- Staff：能討論 key rotation、撤銷、多租戶 / 多 installation 範圍隔離、洩漏後的 blast radius。

## 可遷移的 pattern
1. **長效憑證只用於換取短效憑證**：根 secret 只出現在低頻的交換步驟（OAuth refresh token、AWS STS、service account token）。
2. **身分與授權範圍分層**：JWT 證明「你是誰」，installation token 決定「能做什麼」。
3. **非對稱簽章讓驗證方不持有秘密**：驗證端只有公鑰，降低多方系統中的信任面。
4. **時間窗口容忍 clock skew**：`iat` 回推、leeway，並搭配 NTP（任何帶時間戳的簽章都適用）。
5. **最小化曝險 = 縮短壽命 + 縮小範圍 + 縮小使用頻率**。

## 常見追問
- **為什麼 JWT 一定要用 `Bearer`？** 官方規定 JWT 必須用 `Authorization: Bearer`；其他 token 可用 `Bearer` 或 `token`。
- **`iss` 的作用？** 讓 GitHub 找到對應 app 的公鑰來驗證簽章。
- **JWT 洩漏的影響？** 最多 10 分鐘內可用來換 installation token / 以 app 身分呼叫部分 API；不像 private key 洩漏是長期失陷。
- **為何 iat 要往前 60 秒？** 避免你的時鐘領先 GitHub 導致 JWT 被視為尚未生效；同時應用 NTP 校時。
- **不想自己簽怎麼辦？** 用 Octokit SDK，自動產生並在過期後重生 JWT。
