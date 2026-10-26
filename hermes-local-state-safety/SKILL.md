---
name: hermes-local-state-safety
description: Use when 查 Hermes 本地狀態檔（state.db／WAL／config）或要用腳本撈裡面的紀錄。
version: 1.0.0
author: Drizzt Studio
license: MIT
tags: [hermes, state-db, sqlite, config, safety, devops]
---

# 🔒 Hermes 本地狀態檔安全操作（state.db / WAL / config）

## 觸發時機
- 想直接開 `state.db` 查「某工具／skill 最近被呼叫幾次」「過去對話紀錄」
- 要跑任何會讀 `state.db` 的分析／審計腳本（cost audit 屬這類）
- 要寫／改 `config.yaml`（`skills.disabled`、`auxiliary.vision`…）
- 懷疑 DB 卡住、gateway 拒寫、訊息轉 pending
- **使用者說「你昨天怎麼又沒回應」／回報「進程看不到但服務好像還在」** → 判真假活看下方〈三層存活判定〉

## 🔴 鐵律：不要直開「使用中」的 state.db
**實例（2026-09-16，他機）**：另一台機器上的 agent 用系統 python `sqlite3.connect(自己的 state.db)` 查紀錄 →
觸發 WAL recovery、`state.db-wal` 被重設 → gateway 判定「**WAL 世代遺失**」→ **永久拒寫**，
對話當場停掉、後續訊息被轉存到 pending。DB 本體通常沒事，但那個 profile 的寫入能力是永久壞的。

### ✅ 正確查法（二選一）
| 方法 | 指令 |
|:--|:--|
| **先做一致快照再查** | Python：`src=sqlite3.connect(f"file:{live}?mode=ro", uri=True); src.backup(dst)`（SQLite **Online Backup API**，快照一致、不需停服務）；或 `sqlite3 -readonly live "VACUUM INTO '<tmp>/snap.db'"` |
| **唯讀查** | `sqlite3 -readonly state.db "..."`；Python: `sqlite3.connect("file:<path>?mode=ro", uri=True)` |

⚠️ **「`cp state.db state.db-wal state.db-shm` 三檔一起複製」不是原子操作**：複製期間 gateway 若正在寫，三個檔會來自不同時間點，副本可能前後不一致（SQLite 官方文件也說這種複製只在有 lock 保護時才安全）。**不可把未停寫、未取得適當鎖保護的逐檔複製當成備援**。本腳本建立快照失敗時立即停止審計（SQLite／檔案系統錯誤回傳 exit 2），關閉連線並清除未完成副本；即使指定 `--keep-copy` 也不保留半成品。若清除因權限或鎖檔失敗，會明確報出路徑，且仍不繼續查詢。

### ❌ 不要做
- `sqlite3.connect(live_path)`（沒帶 `mode=ro` 的那種）
- 刪 `state.db-wal` / `state.db-shm`（那是 live 資料的一部分，不是垃圾）
- `hermes doctor --fix`、就地 FTS 修復、把備份複製回去覆蓋 live
- 在 gateway 還活著時對 DB 做任何「修復」

**已卡住的處置**：備份 → 停 gateway → 重啟（DB 本體通常沒事，**別自己動手修**）。

## 健檢（要證明「我的 DB 沒事」時照這個跑）
用 `mode=ro` 連線 + Online Backup API 做一份快照（或 `VACUUM INTO`），再開那份副本：
```python
con = sqlite3.connect("file:E:/<tmp>/state.db?mode=ro", uri=True)
con.execute("PRAGMA integrity_check").fetchone()[0]   # 要 'ok'
con.execute("PRAGMA journal_mode").fetchone()[0]      # 'wal'
con.execute("PRAGMA page_count").fetchone()[0]
# sessions / messages 筆數 sanity check
```
- 複製時 `state.db` 動輒 400MB+ → 查完把副本刪掉，別留在 C 槽。
- 只看檔案大小／mtime 的話不用開 DB：`ls -la state.db*` 就夠（WAL 有在滾動＝寫入正常）。

## 🩺 三層存活判定：「進程在」≠「平台連上」≠「turn 跑得動」

被問「妳現在到底活著嗎」時，這三層要分開驗；只看一層就會誤判（實例：進程活著、Telegram 連上，
但**每個 turn 一建 agent 就炸** → 使用者看到的是「一句話都不回」，跟「掛掉」看不出區別）。

| 層 | 看什麼（以 profile 為單位的正本） | 判準 |
|:--|:--|:--|
| ① 進程／平台 | **`<profile>/gateway_state.json`** | `gateway_state: "running"` ＋ `platforms.telegram.state` / `platforms.api_server.state` = `connected`；`listener_base` 對不對 |
| ② 有沒有在回話 | **`<profile>/logs/gateway.log`** | 比對「最後一筆 `inbound message:`」與「最後一筆 `response ready:`」的時刻——**inbound 後面沒有 response ready 就是卡了** |
| ③ 有沒有在炸 | **`<profile>/logs/errors.log`** | `grep -E "Agent error in session|Failed to initialize"`——每個 inbound 配一行 ERROR ＝ 典型靜默死亡指紋 |

- 🔴 **`hermes gateway status` 會誤報「✗ No gateway process detected」**：新版啟動器會把 argv 改寫成
  `… gateway run --force`（**`--profile` 不見了**），status 靠 argv 認領就認不到；`gateway_state.json` 裡卻寫著
  `gateway_state: running`。→ **別把 status 當唯一依據**，兩邊都看。這是真 bug，不是你的服務掛了。
- 🔴 **只打 `/health` 證明不了什麼**：api_server 的 `/health` **不需 key** → 回 200 只證明「端口有人聽」。
  要證明「認證還在、服務真的可用」要打 **`/health/detailed` 帶 key**（401＝認證層擋住了，也是活著的證據）。
- 停損判準：**②有 inbound 沒 response + ③有 ERROR 指紋** 才叫「死」；只有①可疑（status 說沒進程）但
  ②③都乾淨 → 那只是**判定工具騙人**，服務其實正常。
- 回報時把三層分開講（例：「進程＋平台都 connected，但 20:46 起的 inbound 全部沒有 response ready，
  errors.log 每個 turn 一行 Agent error」），這比「掛了」有用得多。

## 🔎 審計：「某個工具／某顆模型這幾天真的被叫用了幾次」

觸發：使用者冷不防直接問「**妳這幾天有用 vision 嗎? 用的是哪個模型?**」／
「這個你是不是沒用過」／要查某支 cron 到底跑了幾次。
→ 要當場交得出**逐筆清單**（日期／圖／問句＋模型來源），不要靠印象答。

### 一條命令（推薦）
```bash
python3 scripts/audit_tool_usage.py vision_analyze --days 14 --dump-args
python3 scripts/audit_tool_usage.py vision_analyze --profile "C:/Users/<user>/AppData/Local/hermes/profiles/<name>"
```
它自己會「`mode=ro` 連線 → `backup()` 做一致快照 → 查完刪快照」，任何工具名都能查（`terminal`、`comfyui`…）。只計 `role='assistant'` 的 `tool_calls`，不會把工具結果列重複算一次。

### 手動查法（腳本不夠用時）
- `messages` 表關鍵欄位：`timestamp`（**epoch 秒**，不是 ISO 字串）、`role`、`tool_calls`（**JSON 字串**）、`tool_name`、`content`
- 🔴 **只數 `role='assistant'` 的 `tool_calls`**：`role='tool'` 那幾筆是「結果」，內容也含工具名 → 一起數會**重複計數**
- 解析：`json.loads(tool_calls)` → 逐個 function 比 `name`，參數在 `function.arguments`（也是 JSON 字串）
- 有 `--dump-args` 的好處：能說出「那次問的是哪張圖、問句是什麼」，不只給次數

### 重建「某一天的對話」（要照當天真發生的事寫紀錄／補寫日誌時）

補寫事件軌跡、寫日誌、回報「那天到底做了什麼」時**不要憑印象**——把那天逐筆撈出來：
```sql
SELECT datetime(m.timestamp,'unixepoch','+8 hours') AS tw, m.role, substr(m.content,1,400)
FROM messages m JOIN sessions s ON s.id = m.session_id
WHERE m.timestamp >= <epoch> AND m.timestamp < <epoch+86400>
ORDER BY m.timestamp;
```
- ⚠️ **day 邊界要先 `+8 hours` 再切**：`timestamp` 是 UTC epoch 秒，直接 `date(timestamp)` group 會把台灣凌晨的事算到前一天（跨夜工作最容易踩）。
- `sessions` 表帶來源／平台欄位 → 可只撈某一條入口；**別條 session 的動作不要算成自己的**。
- 寫紀錄的取材原則是「**有真實互動證據才寫**」：撈不出東西的那天就跳過，別為了填滿日曆硬生一筆（機械生成的空事件會反過來壓掉真事件該有的效果）。

### 「用的是哪顆模型」怎麼查（2026-09-22 實戰）
| 要查 | 怎麼查 | 坑 |
|:--|:--|:--|
| vision 用哪顆 | `config.yaml` 的 **`auxiliary:` → `vision:`（provider/model）** | `hermes config get vision` 回「Config key not set」是**假警報**（真 key 是 `auxiliary.vision`）；`grep '^vision:'` 也找不到 |
| 這條路由何時被改的 | profile 目錄下的 `config.yaml.bak_visionfix_<日期>` diff 前後 | 備份檔名就是時間軸（實例：`google/gemini-3.8-flash` → `custom/deepseek-flash`）|
| 每次對話真的用哪顆 | `logs/agent.log`：`agent.turn_context: conversation turn: ... model=<m> provider=<p>` | 這行是**最可信**的（每次 turn 都印） |
| 有沒有偷偷落到 fallback | `grep "Fallback activated" logs/agent.log`（`gemini-3.8-flash → grok-4.6 (xai)`） | fallback 是**真的花錢**（見 `hermes-provider-failover`）|
| vision 那次用哪顆 | `logs/agent.log`：`tools.vision_tools: Processing image with vision model...` | ⚠️ **這行不含模型名** → 要回 config 對；另 log 只記開始/完成＋字元數，不記 provider |

- 相關 log 位置：`<profile>/logs/agent.log`（主）、`gateway.log`、`gateway-stdio.log`（auxiliary/vision 的 WARNING 在這）、`errors.log`
- 🔴 **grep provider 名（`xai`／`grok`）會命中「使用者訊息的本文」**：使用者問「有沒有跑 xai api?」那句話本身就會被 grep 到 →
  拿它當證據會誤報。要嘛排除 `msg='...'` 的行，要嘛直接鎖 `API call #`／`Fallback activated` 這類真呼叫行。
- **vision 是獨立一條路由**（`auxiliary.vision`），跟 `fallback_providers` 那條**無關**；設到不可用的 provider 會噴
  `Vision provider <x> unavailable, falling back to auto vision backends` 並讓 `vision_analyze` 直接 error。
- 這條同時是**花錢審計**：被問到「你有沒有花到 X 家的錢」時，看的是 `Fallback activated` 與 `API call ... provider=xai`，
  不是看 config 裡有沒有那家。
- 🔴 **`provider=xai` 與 `provider=xai-oauth` 是兩種帳**：前者吃 **API 帳**（按 token 計費），後者走 **OAuth／訂閱**。
  2026-09-22 使用者親自更正（他看到某個 profile 的主模型是 grok-4.6 就走 OAuth，跟 API 帳無關）
  → 查「誰在燒錢」時**先確認 provider 字串**，不要看到模型名就定罪。
- 跨 agent／跨機的完整對帳流程（憑證指紋盤點、非 Hermes 消費者、peer fan-out、回報四件套）→ 屬作者內部的 `api-spend-forensics`（**本系列未收錄**；
  它附的 `scripts/audit_provider_calls.py` 會掃所有 profile 的 `agent.log` 按日／provider／session 聚合 calls 與 tokens）。

## 用別人的審計工具前：先看它怎麼開 DB
```bash
grep -n "sqlite3\|mode=ro\|immutable" <script.py>
```
✅ 合格實例：`hermes_cost_audit.py`（共用 repo）兩處都是 `sqlite3.connect(f"file:{db}?mode=ro", uri=True)` → 可以放心跑。
自己寫工具時一律照這個寫；**不要相信「它只是讀取」** —— 沒帶 `mode=ro` 的讀取一樣會踩 WAL recovery。

## config.yaml 的寫入紀律
- **不吃 patch/write**（工具會擋）→ 走 CLI：`hermes config set <key> "<json 陣列或值>"`
- 改前先 `cp config.yaml config.yaml.bak_<reason>_<date>`；改後**讀回來驗**（`search_files` 看 key 真的在檔案裡 —— `hermes config get` 的輸出不好 parse）。
- ⚠️ CLI 可能警告「`<key>` is not a recognized config key … may not read it」——**這個警告不一定是真的**。先去原始碼確認誰讀那個 key（實例：`skills.disabled` 由 `agent/skill_utils.get_disabled_skill_names()` 讀，警告是假的；詳作者內部的 `hermes-fixed-cost-trim`，**本系列未收錄**）。

## 檔案在哪（Windows 地端）
- `state.db` / `state.db-wal` / `state.db-shm` 都在 **profile 目錄**（`<hermes_home>/profiles/<name>/`；有些人會把 profile 目錄 junction 到別的磁碟，只要路徑指得到都可以）。
- 輸出／素材目錄可以 junction 到別的磁碟，但 **DB 本身不要跟著搬**（不要順手搬 —— 搬動中的 DB 是最容易壞的狀態）。

## 相關
- `local-path-migration`、`hermes-fixed-cost-trim`：路徑／junction 與 Windows 路徑坑、固定成本瘦身 —— **皆屬作者內部 skill，本系列未收錄**
- 本系列可搭配：`windows-python-tool-compat`（外部工具的 import／路徑坑）、`sqlite-cjk-fulltext-search`（DB 查詢與索引）
