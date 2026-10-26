---
name: comfyui-server-ops
description: Use when 用 HTTP API 操作共用 ComfyUI：佇列、輪詢、cron。
version: 1.0.0
author: Drizzt Studio
license: MIT
tags: [comfyui, api, queue, cron, ops, ffmpeg]
metadata:
  hermes:
    tags: [comfyui, api, queue, cron, ops]
---

# ComfyUI HTTP API 產線維運

給任何要 submit workflow / 輪詢結果 / 下載圖 / 排程批次的腳本參考。
**通用原則**：這類產線機幾乎一定不是你一個人在用（可能是你另一個 job、別的 agent、或使用者本人在上面測模型）。
所有設計都從「別人的任務也在排」這個前提出發。

> 📍 端點一律用環境變數（例 `COMFYUI_URL=http://<comfyui-host>:8188`）；文中 `$SCRIPTS` 指你自己的腳本目錄。

## 🔴🔴 佇列紀律：共用機的第一鐵律

- ❌ 不要把一批工作（例如「4 支影片」）當成一個單位塞進背景跑到底 —— 就算腳本是**一支跑完才送下一支**，
  它仍然連續霸佔 GPU 幾十分鐘，別人的任務只能等在後面。
- ✅ **一次只送一支**；每支跑完後**重新決策**：
  1. `curl -s "$COMFYUI_URL/queue"` 看 `queue_running` / `queue_pending`
  2. 有別人的任務（輸入檔名前綴不是自己的、模型不是自己常用的）→ **退讓，不要再送**
  3. 佇列空了才送下一支
- ✅ 送之前用 **模型名 / 輸入檔名前綴** 認一下佇列裡是不是自己的。
- ⚠️ 已經在跑的那支**讓它跑完**（中途 kill 反而浪費別人已排到的時段），但**不要再接下一支**。
- 🔴🔴 **序列批次也不行**：20 支 × 5.5 分 ≈ 2 小時，別人整個上午插不進來。
  → 正解＝**跑完一支就停手回報，使用者說繼續才送下一支**。
  他喊「停」＝立刻停手（kill 自己的批次），但**已 submit 到伺服器的那支讓它跑完**。

判別誰的任務：
```bash
curl -s --max-time 15 "$COMFYUI_URL/queue" | python3 -c "
import sys,json,re
d=json.load(sys.stdin)
for tag,items in (('執行中',d.get('queue_running',[])),('等待',d.get('queue_pending',[]))):
    for it in items:
        wf=json.dumps(it[2], ensure_ascii=False)
        print(tag, it[1], re.findall(r'\"(?:image|unet_name)\": \"([^\"]+)\"', wf)[:2])
"
```

- 🔴 **kill 掉批次腳本 ≠ 取消已送出的任務**：客戶端死了，伺服器那支照樣跑完，只是**沒人去下載**
  （本機 `raw/` 是空的，成品在 `/history` 裡）。別重跑（白燒一次 GPU），照 pid 接住：
  1. pid 就在批次 log 裡（例如 `[<key>] submitted <prompt_id>`）
  2. 寫一支「接住」腳本：import 母腳本的 `download()` / `conform()`，只重跑那兩步（母腳本不用改）
  3. ⚠️ conform 要用**被 patch 過的 wrapper**，直接 import 母腳本會拿到預設參數
  4. 抓回來後直接交付（那是使用者要的素材，不是廢片）

## 🔴 HTTP 呼叫一律要帶退避重試

**症狀**：批次跑到一半整批死、產物 0，traceback 尾巴是
`ConnectionResetError: [WinError 10054] 遠端主機已強制關閉一個現存的連線`。

**根因**：腳本自己拼 multipart 跟 POST，**完全沒有 try/except**；而共用的上傳模組早就補了退避重試 ——
但**沒被呼叫**，保護等於不存在。

**鐵律**：新增任何 HTTP 呼叫（`/upload/image`、`/prompt`、`/view`、`/history`）一律包退避重試 + 印 `FAIL(n/N)`；
**沒重試的版本＝批次地雷**（一次網路抖動就陪掉整批 GPU 時間）。
**驗證**：`python -m py_compile` ＋ `inspect.getsource()` 確認重試真的在裡面，不要只看 patch 回 success。

🔴 **但 `/prompt` 不是可以無腦重試的端點**（2026-10 補）：它**不是冪等**的——
請求送達、任務排進佇列、只是回應在路上掉了（`ConnectionResetError` 最常見的就是這種），
重試就會**再排一張**：多燒一次 GPU、多出一張同 prompt 但 seed 不同的圖，之後用檔名前綴抓還會抓到兩張。

✅ 正確形狀：
1. 重試**前**先查一次「這批是不是已經進去了」：`GET /queue` 看 `queue_running`／`queue_pending` 有沒有同一個 `filename_prefix`／client 標記；或用 `GET /history` 掃 prefix。
2. 有 → 當成成功，接回那個 `prompt_id` 繼續輪詢，**不要重送**。
3. 沒有 → 才重試，並把重試次數印出來（`FAIL(2/5)`）。
4. 送出時帶**唯一的 client id／prefix 尾碼**（例如 `<專案>_<鏡號>_r2`），這樣「同批重送」與「真的不同張」分得出來。

（同場加映：用 patch 工具改含 `\r\n` 字串的 Windows 檔會被喫成真換行 → SyntaxError；
改用 Python 做「函式級手術」：`t.index("def X(")` … `t.index("def Y(")` 整段換掉，再 `open(..., newline="")` 寫回。）

## 🖥️ 本機路徑坑（Windows + MSYS）

- **路徑語義**：`C:/app/data`（forward slash 原生路徑）給 bash／native 程式；`/app/data` 這種「當前磁碟機相對」路徑
  只在 cwd 落在 C: 時剛好等於 `C:\app\data`，**cwd 在別顆磁碟時會解析到不存在的路徑**。
- ⚠️ **盤點檔案別用 shell 的 `find`、也別用只列一層的工具掃 junction**：junction／symlink 指向另一顆磁碟時，
  兩者都可能**不遞迴、回 0 筆卻不報錯**（只有 `ls` 那一層看得到）→ 盤點一律用 **Python `os.walk`**。
- ⚠️ **native Python 的 `/tmp` = `C:\tmp`**，不是 bash 的 `/tmp`（`%LOCALAPPDATA%\Temp`）——「檔案明明寫了卻讀不到」先想這個。
- ⚠️ **在 junction 底下建目錄可能回 `WinError 183`（「檔案已存在」）但目錄其實沒建**：PATH 上的 `python3` 若是
  Microsoft Store 沙箱版，對「junction 指向另一顆磁碟」的路徑一律失敗（**已存在的目錄不受影響**，所以平日不炸、
  只有要新建目錄時才死）。
  → **正解＝一律用 venv python 跑腳本**；真要寫不靠 venv 的腳本，唯一有效的退路是
  `subprocess.run(["bash","-lc","mkdir -p '%s'" % p], capture_output=True)`。
- **raw 分析檔／輸出檔要落在真實檔案系統路徑**：native ffmpeg 讀不到 MSYS 的 `/tmp`（不產檔也不報錯）。

## 伺服器

- 常用 endpoint：`POST /prompt`（submit）、`GET /history`、`GET /history/{pid}`、`GET /view?filename=&type=`、
  `GET /queue`、`GET /system_stats`、`POST /interrupt`
- ⚠️ **暫時性 502 是常態**（實測全部 endpoint 回 502，等 15~30 秒重試即恢復 200）——先重試再判斷伺服器掛了。
- ⚠️ **但「固定時段的持續 502」＝機器關了，不是抖動**：桌機型產線機很常被拿去打電動或關機。
  判斷法：看現在幾點／星期幾，直接當關機處理，不要浪費 retry。
  處置：確認 `/history` 無新產物、輸出目錄無當天新檔 → 老實回報「機器沒開」，**不要編圖**。
- 🔴 **絕對不要把 ComfyUI 用 `nohup`／背景 detach 起著就放生**：使用者之後手動點捷徑會**開不起來**
  （port 已被佔、而那個進程沒有視窗，他完全看不到）。
  診斷三步：`netstat -ano | grep ":8188"` 拿 PID → `Get-CimInstance Win32_Process -Filter 'ProcessId=<pid>'`
  看 `CommandLine` → **父進程若是 `nohup.exe` 就是自己留下的殘留**（`MainWindowTitle` 為空＝無視窗）。
  處置：先 `GET /queue` 確認 running／pending 都是 0（不要砍正在跑的任務）→ `Stop-Process -Id <pid> -Force`
  → 回報「已清掉、現在埠是空的」。
- 🔴 **比兩台機器速度要分「冷啟動」與「暖機續出」，不可用暖機第二張代表整台**：
  實測冷啟動 18.69s vs 28.96s（差 55%），暖機續出 20.2s vs 26.4s（差 31%）。
  冷啟動差在「從磁碟把 unet＋text encoder 讀進 VRAM」的 I/O，暖機只剩算力差
  → **報出去的數字要講清楚是哪一種**，別拿暖機數字去總結「兩台差不多」（對方會自己量冷啟動打臉）。

## ⚠️ 輪詢坑：`/history/{pid}` 常回 `{}`

即使任務成功（圖已生成），單 pid 查詢 `/history/{pid}` 也可能回 `{}` → 腳本誤判 FAIL、重跑塞爆佇列。
✅ 解法：submit 後掃**全部 `/history`** ＋ `filename.startswith(prefix)` 匹配，再用 `/view` 下載：

```python
hi = json.loads(urlopen(SERVER + "/history").read())
for p, hv in hi.items():
    for n, o in hv.get("outputs", {}).items():
        for im in o.get("images", []):
            if im.get("filename", "").startswith(prefix):
                # 🔴 subfolder 一定要帶：輸出在子目錄時 /view 少了它會 404
                q = urlencode({"filename": im["filename"],
                               "subfolder": im.get("subfolder", ""),
                               "type": im.get("type", "output")})
                raw = urlopen(SERVER + "/view?" + q).read()
```

🔴 **用前綴抓「全部 history」會撈到舊批次的成品**（同一個 prefix 上次也跑過 → 你交付的是上一版的圖）。
下載前先確認兩件事，兩個都成立才算「這次的」：
1. **`prompt_id` 是這次 submit 拿到的那個**（或至少 `hv` 的提交時間晚於你 submit 的時間）；不要只比 prefix。
2. 檔名帶**這次的尾碼**（`prefix_r2`／日期時間），或同一 prefix 重跑時以 server 自動加的 `_00002_` 序號為準。
拿到的檔案再用 `stat().st_mtime` 對一次「晚於 submit 時間」，不然「成功交付舊圖」是靜默錯誤（沒有任何錯誤訊息）。

🔴 **逾時判死 ≠ 任務失敗（共用機必看）**：機器在跑別人的長任務時，自己的圖會**乖乖躺在 `queue_pending`**——
只看 `/history` 等不到就判死，下一步就是走雲端 fallback：**多花錢 ＋ 產出跟本地不一樣的第二張**，
而交付往往挑到錯的那張。
→ 判死前**一定同時讀 `/queue`**：pid 還在 `queue_running`／`queue_pending` ＝ 正常排隊，繼續等。
→ fallback 前再撈一次 `/history` 掃 `startswith(prefix)`，命中就直接下載。
→ 建議實作：`timeout=1200`、連續失聯 6 次才算死、`/queue` 讀不到不計 miss。

## ⚠️ VRAM 吃緊時出圖超慢

HD（1088×1920）+ 3 LoRA 在 VRAM 被佔（其他 job 併跑 / 模型殘留）時，每張 10~15 分鐘：
- 輪詢上限設 **1500 秒+**（300×5s），不要用 360 秒
- `/system_stats` 顯示 VRAM free 只剩 2GB 是常態（模型沒卸載），不代表任務會失敗
- submit 後先看 `/queue` 確認有沒有排隊；失敗先去 `/history` 撈 `prefix*`，別急著重跑

## ⚠️ Wrapper timeout 太短會砍掉整個 subprocess

分層 wrapper（外層 shell → 內層 python → 每張圖輪詢 300s）在佇列塞車時必爆：
timeout 一到 subprocess 被殺，**圖沒下載、MEDIA 沒送出、JSON stdout 遺失**。
✅ 解法：**每一層 wrapper 的 timeout 都要 ≥ 內層 worst case**。
⚠️ 只修了 where 爆掉的那一層，另一層會再爆一次——**改完要確認每一顆都改到**。
⚠️ 若 sequence／進度檔在**出圖前**就推進，timeout 後那幾個名額被吃掉但沒有圖；重跑前要先把 position 退回去。

### 🔴 只是「拉長 timeout」治不了塞車：改成 partial 落盤

child 每張圖自己輪詢上限 600s × 4 張 = **worst case 2400s**。外層 `timeout=900` 在佇列塞車時必爆：
當天前面卡著一支影片任務 ＋ 9 支 pending，第 1 張 20:39 才出圖（>600s，child 已放棄它）、
第 2 張 21:00 才出圖 —— **外層 20:35 就被砍、`capture_output` 讓 stdout 整個消失，4 張成果全丟**。

✅ **正解＝成果即時落盤 ＋ 外層逾時改讀狀態檔**（不需要重跑、不燒 GPU）：
1. child：每張下載完就 `json.dump(results, <partial>.json)`（開跑先清空成 `[]`，避免讀到上一輪殘值）。
2. 外層：`timeout = child worst case` ＋ `except subprocess.TimeoutExpired` 時讀 partial 檔印出來
   → 逾時至少送出「已完成的張數」，不再整批歸零。
3. **名額／sequence 已經被吃掉**時，想補完當天那幾項：**不要重跑腳本**（會變下一輪主題），
   照原本的 seed 公式自己組缺的那幾支 submit，出圖後從 `/history` 撈回。
   ⚠️ 同名 prefix **每輪會重複用到** → 撈回時要比 bytes／mtime 確認是新的那顆，別把舊檔交出去。
4. 診斷起手：`/queue` 看 running 是不是**別線的重活** ＋ 已完成的圖其實躺在 `/history`，先撈再判斷。

### 🔴🔴 長批次不要跟「回報」綁在同一個 agent session

整批 GPU 要跑 2~3 小時的 cron，**不要設計成「同一輪 agent 邊等腳本邊交付」**：
那輪 agent 的 LLM provider 一斷（實測連續 6 次 600s stale／`WinError 10053/10058` →
`Provider has been unresponsive`），session 以 `cron_incomplete_no_output` 收場，兩個後果同時發生：

1. **使用者收到的是「失敗」通知，其實片子早就出完了**——不要跟著「失敗」兩個字去重跑，先撈產物。
2. 🔴 **session 結束會把子程序樹一起帶走** → 最後一支（session 死後才在伺服器上跑完的）永遠不會被 harvest。

✅ **兩條結構性修法**（不要再靠拉長 timeout）：
- **產物先落盤、後回報**：每支完成就寫 partial JSON（開跑先清空）。
- **把重活與交付拆開**：長腳本 detach 成背景程序，或另開一個短命交付 job 只負責讀 partial JSON＋送 MEDIA。
- ✅✅ **最乾淨的解＝`--no-agent` 純腳本班**（連 LLM 都不叫 → 根本沒有 provider 可以斷）。
- 🔴 **安心點：submit 出去的任務跑在伺服器上，跟你的 session 死活無關**——只要 pid 在 `/history`，
  就算 agent 早就死了，`/history` → `/view` → conform 照樣把成品撈回來。

## ✅ 出圖失敗的完整救援 SOP

腳本 timeout / FAIL 時**先別重跑**，照這個順序救：
1. `GET /queue` → 看 running／pending：別線的重活或別台 agent 的 cron 併跑 = 塞車主因。
2. `GET /history?max_items=100` → 找 `filename.startswith(prefix)`：**常常 server 其實已出圖**，只是本地沒下載到。
3. 有圖 → `GET /view?filename=...&type=output` 直接撈回來。
4. 沒圖或只出部分 → 進度檔倒回，換 seed 重跑（避免同天重複圖）。
5. 重跑後逐張 vision QA：**自動交付的圖，交付前一定要視覺抽驗**（使用者細看每張圖，瑕疵會被抓）。
6. 撈回／重跑的圖全數落地後再出 MEDIA，別只送 JSON。

### SaveImage 同名 prefix 重複 submit → server 自動加計數器

`xxx_01_00001_.png`（第一次 = cron 原產）vs `xxx_01_00002_.png`（手動重跑 duplicate）。
救援時撈 `_00001_` 系列，別把 `_00002_` duplicate 交出去。
🔴 **不要為 debug 手動重跑 tier script**：它會在出圖前就推進 sequence → 吃掉名額 ＋ 產生 duplicate
＋ vision QA 會驗到錯的角色。要驗「這張是哪個角色」：從 `/history/{pid}` 的 prompt 抓。

### ComfyUI 的 history `prompt` 欄是 LIST 不是 dict

（實測 0.31.1 起）→ 掃節點的 parser 會空手而歸。用
`re.search(r'<關鍵字> ([^,]+)', json.dumps(prompt))` 抓內容、`filename_prefix.?[:=] ?"?([a-z0-9_]+)` 抓 prefix。

## 🔴 Cron／agent 環境下被 lifecycle guard 擋 python 時

cron session 裡 `terminal("python3 /path/xxx.py ...")`、`bash wrapper.sh`、甚至 `cp ... && python3 ...`
都可能被 lifecycle guard 以 `ValueError: open: embedded null character in path` 擋下
（guard 解析 command 裡的 script 路徑時爆掉，與腳本內容無關，檔案本身沒 null byte）。

**正確處理原則**：這是**防護層的正常行為**，不是要繞過的障礙。

1. **先回報**：把 guard 的原始錯誤訊息留著，告知機器主人「這個 session 的終端被 guard 擋住」，
   不要自己改成別的指令形式去試探 guard 的判定規則。
2. **改用 API／檔案介面做事**，這是本來就該走的路（也讓流程可審計）：
   - 需要讀資料：`curl` 拿 JSON（`/history`、`/queue`、`/object_info`）→ `write_file` 落檔 → 解析
   - 需要送任務：`write_file` 寫好 workflow JSON → `curl -X POST -d @file /prompt`
   - 需要收成品：`curl /view?...` 下載 → 檢查 magic bytes（如 PNG `89504e47`）→ QA
3. **要跑本機腳本**：請機器主人在他自己的終端執行，或由 cron 的 `script:` 欄位直接指定
   —— 這兩條都是正式支援的路徑，不必與 guard 對抗。
4. 🔴 **不要**為了讓指令過關而改寫成「不含路徑」的形式、把腳本內容塞進 `-c`、或改走別的解譯器
   —— 那是繞過防護，不是解決問題；在別人的機器上更不可行。

以下這套「純 API」做法同時也是**沒有 shell 權限時**的通用解法：
1. `curl /history` 全 dump 到檔 → 找目標 prefix 的 pid
2. 撈原 prompt + seed（`prompt` 欄是 LIST，iterate 找 dict 再掃 node）
3. `write_file` 寫新 workflow JSON → `curl -X POST -d @file /prompt`（回 `node_errors:{}` = 成功）
4. 輪詢 `curl /history/{pid}` grep filename（重複 prefix 重 submit → server 自動加 `_00002_` 計數器）
5. `curl /view?...` 下載 → 檢查 PNG magic bytes（`89504e47`）→ QA → 交付
6. 🔴 **重出 prompt 只改會翻車的元件**（例如取景範圍），服裝／場景／角色維持一致，換 seed 即可
   —— 不要整段重寫，否則跟同批其他張風格脫節

## ⚠️ 新腳本別硬寫模型路徑／LoRA 名

自寫 workflow 時手打 `unet_name`（例如猜 `krea2\muse_v1.0.safetensors`）→ **HTTP 400 Bad Request**。
正確路徑一律從既有的 `MODEL_MAP`（或等價的常數表）拿，不要憑印象打。

- **手寫 workflow 的 LoRA 名稱也要 normalize**：`lora_name` 直接寫 `"<subdir>\\\\<custom_style_lora>.safetensors"` 字面值
  → **HTTP 400 Bad Request**（跟 model 路徑 400 同症狀）。套 `re.sub(r"\\+", r"\\", name)` 壓成單一反斜線。
- 🔴 **JSON 用單一反斜線 escape 寫入即正確**（write_file 對 JSON 不炸）；`.py` 檔裡的 4 反斜線問題只在 Python 字串。

## ⚠️ 交付「文稿腦補」坑

若輪次要求 agent「附上一段介紹」，但同時又禁止 vision QA —— agent 沒看圖就會**瞎掰描述**，跟實際圖完全對不上。
✅ **解法**：腳本 stdout 輸出**真實 prompt 摘要**（`{name}|{path}|{prompt[:220]}`，`|` 換成全形 `｜` 避免切欄），
交付 prompt 明確寫「文稿必須照摘要寫、禁止腦補摘要沒有的細節」。
**通用原則**：任何禁止 vision 的出圖 cron，只要交付文需要描述圖內容，腳本 stdout 就必須帶 prompt 摘要。

### 交付 MEDIA 被丢：兩個獨立死因，兩個都要查

1. 🔴 **路徑形式**：`Path("/app/data/x.png").is_absolute()` 在 Windows Python 是 **`False`**
   （`/c/opt/...` 同樣 False）→ 第一關就 `return None`，**檔案明明在磁碟上也照丢**。
   → 一律給**絕對原生路徑**（`C:/...`）。
2. 🔴 **最常見的真死因就是 missing file**：搬遷當天、檔案被搬走、腳本寫錯目錄都會長成同一個症狀。
   排查：`cron/jobs.json` 的 `last_delivery_error` → `cron/output/<job_id>/最新.md` 看 MEDIA 實際字串 →
   **手動照那個字串讀一次檔**（存在＝不是路徑問題，改去查交付時序）。

- 送圖「Timed out」多半是**併發衝突**（agent 長回覆同時在送），不是 bug 也別去改 timeout。
  ⚠️ 但**檔案太大也會 Timed out**：實測同一條 cron，**2.78MB 的 PNG 掛掉、1.25MB 那張過**。
  → 交付用圖先壓到 **~1.5MB 以內**（縮圖或轉 JPG）。⚠️ 兩者症狀一樣、死因不同：**先看檔案大小**，再懷疑併發。

## ⏰ cron 排程時區 = **profile 時區的牆上時間**

Hermes cron 表達式的解析順序：`HERMES_TIMEZONE` env → `config.yaml` 的 `timezone` → server 本地時間。

- 🚨 **從 UTC 容器搬到本機機器時**（例如 Asia/Taipei），若不改 expr，**所有 cron 全部早 8 小時**
  （凌晨 02:00 出圖、晚上 20:00 才跑 10am 場）。
- ✅ 修法：全部 expr **+8 小時（mod 24）** 改成本地時刻，並 `hermes config set timezone Asia/Taipei` 把時區釘死
  （以後換機器不會再漂）。全庫現況 = 名稱寫的時刻 = `Next run` 的 `+08:00` 時刻。
- ⚠️ **`config.yaml` 不能直接手改**：會被拒（`Refusing to write to Hermes config file …`）
  → 一律走 `hermes config set <key> <value>`，再 `hermes config get <key>` 驗。
- **no_agent 哨兵 cron（watchdog pattern）**：要監控「別的服務靜默失效」就用 `no_agent=True` + script-only
  —— **stdout 空 = 不發訊息、有異常才印一行** → 正常時完全零 token、不吵人。
- 驗證方式：`hermes cron list` → 每顆 job 的 `Next run` 必須是 `+08:00` 且與 job 名稱相符。
- 批次改：`hermes cron edit <job_id> --schedule "0 10 * * *"`（一次一顆，跑迴圈）。
- 遷移偵測：`cron/timezone_migration_catchups.jsonl`（offset 被改寫時會補跑一次）。
  **搬機器後第一件事就是對 offset。**
- cronjob 的 `script` 參數必須放 `~/.hermes/scripts/` 並用相對檔名（絕對路徑會被拒）。

## 🔧 cron 的 `script` 欄位：空的＝每輪靠 agent 自己補跑

`hermes cron list` 看不到 `script`，要看 `cron/jobs.json` 的欄位或用 `hermes cron runs <job_id>` + `cron/output/<job_id>/`。

- 🔴 **`script: null` 的出圖 job ＝ 排程本身不跑腳本**，而是靠 agent 在那一輪自己補跑。
  症狀：log 裡 agent 自己講「排程本身沒把圖生完，是我剛剛自己補跑一輪」、完成時間晚 6~10 分鐘。
  → 修正：`hermes cron edit <job_id> --script <script.py>`。
- `--script` 模式＝**排程先跑腳本，stdout 注入 prompt**，agent 只負責交付。
- **腳本 timeout**：預設 **3600s**（`cron.script_timeout_seconds` 可調）→ 長批次要先估 worst case。
- 🔴 **改 script 模式時，prompt 必須同步加一句「不要自己重跑腳本」**（重跑＝重複扣錢／重複燒 GPU）：
  「排程已自動執行 X.py，不要自己重跑；沒有圖就直接回報失敗與原因。」
  沒寫這句，agent 看到 0 產出就會自己再跑一遍。
- 停／開：`hermes cron pause <id>`（保留可 resume，優於 remove）／`resume`。
  ⚠️ **paused 的 job 不能 `run`**（回 `execution_skipped`）→ 要立刻 fire 一次就先 resume 再 run。
- 新 job 建完**一律 `hermes cron list` 讀回**：確認 `Next run` 是 `+08:00`、時刻與名稱相符、`script` 有值。

## ⏰ 排「自己的夜間批次」：先撈空窗，再掛 `--no-agent` 純腳本班

「排凌晨」不等於凌晨有空——**每次現查，不要沿用上一次的空窗**（夜間班表會變：
`0 4 * * 0`、`30 2 * * 0` 這種只在特定星期 fire 的班，平日根本不存在）。

- 撈法：`hermes cron list | grep -E "Name:|Schedule:"` → 把**那一晚所有會 fire 的班**疊成時間軸
  （含只在某星期 fire 的），挑完整空檔再留 buffer。
- 排法：
  ```bash
  hermes cron create "30 3 * * *" --name "<看得懂的名字，含時刻>" \
    --script <我的腳本.sh> --no-agent --deliver origin
  ```
  - 🔴 **`--no-agent` ＝ 純腳本班**：不叫 LLM 起來、不會被 provider 斷線咬，**stdout 直接當交付**。
    小時級的長批次一律用這個模式。
  - **stdout 空 ＝ 完全不發訊息**（watchdog pattern）→ 做完了就印空，不要每次 fire 都送一句噪音。
  - 🔴 **純腳本班的 `.sh` 裡不要靠 `$HOME`／PATH 推導任何路徑**：cron 的環境變數比互動 shell 少，
    互動跑得過、排程一 fire 就在第一行死掉。venv python／目標腳本／輸出目錄**一律寫絕對路徑**。
    就地驗法：`bash -n <腳本>` 過語法 ＋ 手動 `ls` 每個寫死的路徑一次。
  - ⚠️ 純腳本班 stdout 會被送去交付 → 要留 log 就在 `.sh` 裡 `| tee -a <log>`。
- 🔴 **批次腳本必備七件**：
  1. **一次只送一支**：submit → 等 → 下載 → conform 才送下一支
  2. **單支失敗 try/except**，不炸整批；下載重試 4 次（`/view` 偶發 timeout）
  3. **成品已存在就 skip** → 中斷後重跑只補缺的
     ⚠️ **「每 fire 跑表上下一項」的輪播型批次擋不住重複**：隔天再 fire 會拿**新 seed** 出同主題的另一版
     → skip 不命中、白燒一輪。正解＝**另維護一份完成清單**（每成功一項就 append），排程開頭先比對。
     🔴 **不要把防重複放在「同一天」這種隱性條件上**。
  4. 🔴 **上傳與 submit 也要重試**——只重試下載不夠。實測腳本**第一個 upload** 吃一次連線 reset
     → 16 支全部歸零；它 docstring 明明寫著「單支失敗不炸整批」，code 裡卻沒有 try/except
     → **修批次腳本要看 code，不要信 docstring**。
  5. **開跑前 preflight**：輪詢 `/queue` 到 running+pending 連續兩次為 0、再緩衝 20s 才動手。
  6. **靜圖差分生成器同樣要吃這一套**：`/view` 下載裸的 → 第 3 張吃一次 `TimeoutError` 就整批歸零。
  7. **已生成、但沒下載到的圖直接從 `/history` 撈回**（不用重燒 GPU）。
     🔴 **檔名 parse 要吃掉 SaveImage 的尾碼**：`^(prefix)_(\d+)_\.png$`——用 `rsplit("_",1)[0]`
     會把 `_00001` 留在 key 裡 → 比對全 Miss，白撈一輪還以為伺服器沒紀錄。
- 🔴 **多小時長批次再補兩件**：
  1. **停止線**：腳本自己帶「超過 HH:MM 就不再開新的下一支」，不然一班拖過下一個 job 的時段 ＝ 撞車。
  2. **進度狀態檔**：每支完成就落盤 → 交付段掛掉、session 死掉都救得回來。

### 🛑 「全停」SOP：使用者喊停時的三步（共用機鐵律）

「先全停」／「全部下來」＝**立刻停手**（不要先問、不要想把這一輪跑完），照這個順序做：

1. **kill 自己的批次程序** —— 但這只殺了**客戶端**：已 submit 的任務還在跑，**GPU 還沒讓出來**。
2. **讀 `/queue` 認人**：取 `queue_running` 那筆的 workflow，抓 `filename_prefix` 與 `unet_name`，
   **確認那是我自己的 job 才動它**。共用機上**跳過這一步就會誤殺別人的任務**（踩過）。
3. **`POST /interrupt`（只停 running）** → 讀回 `/queue` 必須 **running 0 / pending 0**。
   ⚠️ **interrupt 不含 pending**：還有 pending 要另外清（`POST /queue {"delete":[...]}`）。
4. 回報三件事：**「running 那支是我的、沒誤殺別人」＋ 現在時間 ＋ 現場檔案狀態**
   （哪些在、哪些被抽走、封存的放哪）。使用者停手通常是為了「自己去看」——他要的是**可判讀的現場**，不是你重跑。

- 🔴 **停手後不要再自動補跑**：他會自己看、自己決定哪支要重跑。
- 🔴 **停手≠刪**：抽掉的版本一律移進 `_v2_<原因>/` 留底（他常回頭說「舊的其實可以」）。
- 🔴 **深夜批次跑到一半他說停**也一樣：先停、先回報，不要搶在停之前「搶救最後一支」。

### 🔴 節奏：序列跑，不要自己加排程層

「不要一次上 14 支」時，他要的不是節奏控制器：
- ✅ **正解＝一支一支序列跑**（批次腳本本來就 submit→等→下載→下一支，佇列永遠只有 1 個任務）＋ 跑完開一個背景程序收尾交付。
- ❌ 多做一層「每 30 分鐘一組」的 cron 分片 → 被一句「**不需要做成 cron，直接出**」打回。
- ⚠️ **例外＝使用者自己發起要排班**（他會直說時間窗）→ 那才要做。差別在「排程層是他交代的，不是你自作聰明加的」。
- 想加自動化框架／排程層／額外 job 之前 → **先用一兩行問**。

### 🔴🔴 撞到別人的 cron **不是「只是排隊」**

舊說法「撞到別人的 cron 時你的 job 只會排在對方後面，不是卡死」——**是錯的，會害死整批**。
實測：兩支吃同一台機器的 job 在同一秒起跑，**先送出的那個 upload 直接被打掉**
（客戶端 `ConnectionResetError [WinError 10054]`），而**伺服器端連一筆 log 都沒有**（請求根本沒進 handler）；
重載中（載 20GB 模型、CPU 97%）伺服器端還會吃 `WinError 121`（socket 等待逾時）。

→ **寧可錯開，不要賭佇列**：長批次一律排在別線專屬時段之後，並留 buffer（16 支 × 5~6 分 ≈ 1.5 小時）。

📎 完整對帳（時間軸／兩邊 log 逐字／修法 diff）→ `references/cron-collision-and-rearm.md`

### 🚑 排程 job 掛掉之後：證據在哪、怎麼復活

**先撈證據，不要先重跑**：

| 證據 | 位置 | 看什麼 |
|:--|:--|:--|
| 有沒有起火、exit code | `cron/executions.db`（**先 copy 到 Temp 再開**，不要直開 live） | `status`／`started_at`／`error` |
| 失敗分類 | 同檔的 `cron_incidents` 表 | `failure_type`（script／agent／timeout）／`state` |
| 腳本 stdout+stderr | `cron/output/<job_id>/<時間>.md` | traceback 第一行 ＋ stdout 最後一行 |
| **伺服器端對帳** | `GET /internal/logs/raw` | JSON `{"entries":[{"t":…,"m":…}]}` 環形緩衝，按 `t` 過濾時間窗 |

- 🔴 **客戶端 reset ＋ 伺服器端查無此請求 = 請求沒進 handler**（傳輸層就斷了）。兩邊都要看，
  才分得出「腳本邏輯錯」與「socket 被掉」。
- 🔴 **job 一旦 repeat 用盡就變 `state=completed` + `enabled=false`**：那次失敗就是它最後一次，
  **之後永遠不會再跑**（「怎麼都沒執行」的真身就是這個）。這種 terminal job 被守門擋住、改不動
  （`cron edit` / `cron resume` / `cronjob_manage update` 全部拒絕）
  → **解法＝建新 job 接手**（絕對 ISO ＝ 一次性）。舊 job **留著當紀錄別刪**。
  建完 `action=list` 讀回：`next_run_at` 必須是 `+08:00` 且與名稱相符。
- 補跑不用改腳本：有「成品存在就 skip」的批次，**直接重跑同一支就是補缺**。

### 🌐 同一時段「全部 cron 一起掛」→ 先分辨是哪一層掛

「今天早上的 cron 全部失敗」時，**先分層，不要先重跑**：

1. **讀 `cron/output/<job_id>/<時間>.md`**：檔內固定三段 `## Prompt` / `## Script Output` / `## Error`。
   🔴 **`## Error` 是「agent 那一輪 LLM 呼叫掛掉」≠ 腳本沒跑** —— 出圖 job 的圖**可能已經躺在磁碟上**：
   先看 `## Script Output` 有沒有 JSON、再逐檔 `exists()` ＋ size 驗，**有檔就直接補送，不要重跑**。
2. **`hermes cron runs <job_id>`** 看歷史 → 分辨「今天第一次炸」還是常態。
3. **`logs/errors.log` 抓那個時段**，看 `provider=` / `base_url=` / `error_type=`：
   🔴 **多個不同家 provider 同時失敗 ＝ 不是 Hermes、也不是單一 provider 的鍋，是本機對外網路／DNS**。
   （**`WinError 10060` 常是 DNS 逾時的表現**，`getaddrinfo failed` 是同一件事的另一張臉。）
   交叉訊號：**區網照常**（`/system_stats` 200、圖照樣生成）＋ **雲端出圖回 `[]`** → WAN/DNS 實錘。
   ⚠️ 別把「某個即時通訊平台還活著」當反證——它可能走固定 IP，**不吃 DNS**。
4. **機器層對帳**：`logs/gateway-exit-diag.log` ＋ Windows 事件（`LastBootUpTime`、`User32` 1074 重啟）。
5. **恢復順序**：① pre-run 已出圖 → 補送（不重跑）② 產物為空 → 背景重跑腳本（一次一支）
   ③ 純報告型（清理）→ 確認 pre-run script 已執行就＝無損失，如實回報。
6. 🔴 **脆弱點盤點（要提出來，別自己動設定）**：fallback 鏈只有一段雲端 ＝ WAN 一斷全滅；
   被 pin 在單一 provider 的 job 連 fallback 都沒有；DNS 只有路由器一台 → 可建議加公共 DNS 或掛一條地端模型。
   ⚠️ 改 DNS／網路設定會動到全區網 → **一律先問**。

📎 分層鑑識通則與逐層證據表 → `references/cron-provider-outage-triage.md`

## 🖐️ 互動式出圖批次：用前景跑、一項一項測

使用者在線的互動式出圖（多模型開箱、A/B、挑圖）用這個節奏：

- **前景 `timeout 560` 分段跑，一次一顆模型**：用背景程序跑出圖腳本時遇過**兩次行程靜默死亡**
  ——log 沒錯誤、`ps` 找不到、`/queue` 空的、圖也沒出。改成前景分段跑最穩（4 張約 1.5~2.5 分鐘）。
  **背景跑掛掉就直接前景重跑同一 tag**（同 prefix 覆蓋，不要留兩版混淆）。
- **一項一項測**：**一個假設跑一輪、MEDIA 交他判完再跑下一輪**，不要一次把多個變因全丟上去。
- **slider／新 LoRA 首張冷載很貴**：實測單張卡到 **315 秒**（之後回 10 秒）——看到一張 5 分鐘不要當成模型慢。

## 🎛️ 出圖池盤點（先查再回答）

- **LoRA 全清單實查**：`curl -s "$COMFYUI_URL/object_info/LoraLoader"` →
  `LoraLoader.input.required.lora_name[0]` 就是**所有可用 LoRA 檔名陣列**。
  任何「還有沒有新東西可加」的問題**先做差集再回答**，不要憑印象。
- 🔴 **全類別盤點用 `/models` 家族**：`GET /models` 回類別清單（`checkpoints`／`diffusion_models`／`loras`／
  `text_encoders`／`vae`／`clip_vision`…）→ `GET /models/<類別>` 回該類**檔名陣列**（含子目錄前綴）。
- 🔴🔴 **`/models/<類別>` 只給檔名**（無 mtime／size）→ 查不出「哪幾顆是新的」；
  也**不要**拿自己的文件／筆記做差集判斷新舊 —— 那些只記「我用過的」，差集會把一大堆舊模型全列成新的
  （實測 77 顆被判 60+ 顆新下載＝全假陽性）。
  → 正解＝**問使用者檔名**（他下載時就知道）或請他講落到哪個資料夾。
- ✅ **`/api/experiment/models/<類別>` 才有 metadata（size／mtime）**：
  `[{"name":"...","pathIndex":0,"modified":…,"created":…,"size":620285648}, …]`。兩種用途：
  1. **判斷新舊**：`modified` 就是落檔時間。
  2. 🔴 **未知模型檔的溯源**：拿本機 size **byte-exact** 比對 HF 清單
     （`https://huggingface.co/api/models/<repo>?blobs=true` → `siblings[].size`）＝**不用 SSH 也能證出「這顆哪來的」**。
     **先溯源再決定要不要重新下載**，不要重複佔空間。
- ✅ **`/object_info/LoadImage` 的 `image` enum ＝ 伺服器 `input/` 的檔案清單**：
  出片前先查參考圖**在不在伺服器上** → 在就不要再上傳（省一次 `WinError 10054` 的風險）。
  解析法：`object_info['LoadImage']['input']['required']['image'][0]` 是**檔名陣列**（不是 combo dict）。
- ✅ **每支的耗時與「每步成本」可以從 `/history/<pid>` 反推**：`status.messages` 裡
  `execution_start` / `execution_cached` / `execution_success` 都帶 unix ms 時間戳 → 差值 ＝ 該支總耗時。
  **只改步數跑兩支**（例 4 步 vs 8 步），差值 ÷ 步數差 ＝ **每步取樣成本**，剩下的就是解碼／存檔的固定開銷
  → 用來判斷「某個加速方案值不值得」：實測非取樣部分只佔 ~40~60 秒
  → 專打 VAE 解碼的加速方案在 8~10 秒短片上只有個位數 % 效益，**不要急着裝**。
- 🔴 **池子大小 vs 每天張數**：每日 4 張 + 池子 10 顆 → **10 天全輪一遍**，選圖滑窗去重再怎麼寫都擋不住撞圖
  （實測近 6 天 24 張，某幾項天天重複）。
  → 判定式：**池子 < 每日張數 × 3 就別用每日節奏**（改成週更）。
- 🔴 **上游改頻率 → 下游依賴鏈必須同步改**：上游由日更改週更後一週只有 4 張新圖，
  日更的下游第 5 天就沒素材 → 一起改週更。
- 🔴 **paused job 的成本真相**：paused **不會被 fire → 0 inference／0 token**，它只是 `jobs.json` 裡幾行字。
  固定成本來自 system prompt／skills 索引／tool schemas，**跟 cron job 存不存在無關**。
  ⚠️ 「刪 paused job 省固定成本」**是錯的說法，別再講**。
- 🔴 **代辦清單會過期**：引用安全類待辦（防火牆／憑證／指紋）之前**先實查一次**再回報。
  查法：`Get-NetFirewallRule`／`Get-NetConnectionProfile`／`Get-NetFirewallProfile`。

## 🧩 新增一條出圖產線時的隔離規則

「把 X cron 停掉、改出 Y」時，新腳本**不要共用舊線的狀態檔**：

- **順序檔獨立**：每一條線自己的 `.xxx_seq.json`。共用同一個 seq → 兩條線互相推移，
  兩邊的「今天該輪到誰」都跟預期不一致。
- **場景／鏡頭池也要自己的**：舊線的池是為了舊尺寸／舊構圖寫的——共用只會出錯。
- **輸出目錄用實體目錄**（不要沿用別條線的 symlink 目錄）→ 投遞政策、日後清理都比較單純。
- 🔴 **不要為了新線去改共用的出圖腳本**：它存自己的固定 OUTDIR，新線要在外層接一手搬檔
  —— 動共用腳本會一次弄壞所有 caller。
- 新 job 一律：`--script <自己的腳本>` ＋ **pin model/provider** ＋ `hermes cron list` 讀回驗。
- 停舊線用 `hermes cron pause`（不刪）——使用者很可能回頭要它。

## 📦 外來的 workflow 能不能跑？先做「節點＋模型」盤點再回答

別人丟一支 workflow JSON 問「我們能用嗎、缺啥節點」時，**不要看 JSON 猜**，用 API 實查。

### 🔴🔴 最大的坑：`/object_info/<節點名>` 對「不存在的節點」也回 HTTP 200

```bash
curl -s "$COMFYUI_URL/object_info/ThisNodeDoesNotExist12345"
# → HTTP 200，body 只有 2 bytes：{}
```
→ **逐顆問的檢查法會全部誤判成 ✅**（我真的先報了一輪假的「全部都有」，改用整包比對才抓到缺件）。
正解＝**抓整包再比對 membership**（很快，不要怕大）：

```python
import json, urllib.request
d = json.loads(urllib.request.urlopen("$COMFYUI_URL/object_info", timeout=480).read())
# 實測 6.7 MB / 3249 個節點 / 約 1 秒
avail = set(d.keys())
need  = {v["class_type"] for v in json.load(open(wf, encoding="utf-8-sig")).values() if isinstance(v, dict)}
print("缺:", sorted(need - avail))
```

### 缺件報告的四個欄位

1. **缺哪些 class_type ＋ 各自屬於哪個 custom pack**：節點的 `category` 欄位會洩漏來源
   （例：`KJNodes/experimental` → KJNodes、`😺dzNodes/LayerUtility/*` → dzNodes）。
   拿到節點名 + 類別再去搜 GitHub repo，比瞎找快很多。
2. **模型缺哪些**：逐 loader 取 enum 做 membership（不是看檔名眼熟）：
   `UNETLoader.unet_name` / `CLIPLoader.clip_name` / `VAELoader.vae_name` / `LoraLoaderModelOnly.lora_name` /
   `UpscaleModelLoader.model_name`。
   🔴 **模型常放在子目錄**（`krea2\…`、`MMH3\…`）→ 對方寫裸檔名一定「找不到」，
   先確認是不是**同一顆、只是要補目錄前綴**，再判定「真的缺檔」。
3. **哪些缺件有現成替代**（例：`AudioCrop` → 已有 `TrimAudioDuration`；只是拿音長的可繞）。
4. **環境版本**：`GET /system_stats` → `comfyui_version`／torch（外部 workflow 常綁新版節點，
   **別替對方保證**）。

### 其他兩支好用的唯讀端點

- `GET /internal/logs/raw` → JSON `{"entries":[{"t":…,"m":…}]}`；查某個 pack **有沒有裝／import 失敗**
  （grep `IMPORT FAILED`／pack 名。全 0 命中＝根本沒裝）。
- `GET /object_info/<既有節點>` 回的是完整 schema（`input.required/optional`）→ 用它確認欄位名與 enum，
  不要照抄別人的欄位寫法。

## 🛰️ 只有 HTTP API、沒有 shell 時，怎麼讓伺服器自己把模型抓下來

情境：要裝新模型，但 SSH／SMB／WinRM／RDP 全關，對外只有 `:8188` 與另一個服務埠。
目標＝把 HF 上的大檔弄進 `models/`。

### 🔴 裝 custom node（節點包）比裝模型更難：兩道閘門

| 端點 | 實測結果 | 條件 |
|:--|:--|:--|
| `POST /api/manager/queue/install` | 403 | `security_level` 必須是 weak/normal；**strong/block 一律擋，UI 按 Install 走同一支** |
| `POST /api/customnode/install/git_url` | 403 | 要 `allow_git_url_install=true` **且** `args.listen` 是 loopback → **遠端監聽的機器永遠不會過** |
| `POST /api/manager/customnode/install/git_url` | 405 | 路徑錯（customnode 路由沒有 `manager` 前綴） |

- 兩者都在 **ComfyUI 啟動時讀一次** → 改 `config.ini` 要停機重啟，不是遠端能繞的。
- 不在 registry 的社群新 repo **從 HTTP API 裝不進去**，別再排列組合試端點。
- ✅ 正路：① 請使用者在機器上手動 `git clone <repo>` 到 `custom_nodes/` ＋ 重啟；
  ② 若那台機器另有可執行的 agent／shell 通道 → 可以請它裝，但**先問使用者願不願意**。
- ⚠️ 兩個假訊號別誤讀：`GET /api/manager/installed` 回**空字串**、`POST /api/manager/queue/install`
  空 body 回 **500** —— 都不代表「裝好了」或「可以裝」。

### 三條路，只有一條真的通

1. ❌ **Manager `POST /api/manager/queue/install_model`**：有**白名單閘門**
   （要求 `save_path + base + filename` 三欄完全命中 registry 的 model list）→ 社群檔一律回
   **400 `Invalid model install request is detected`**。
   ⚠️ **端點探測別誤判**：空 body POST 回 **500**、GET 回 **404** —— 500 只代表「route 存在但缺欄位」，
   **不代表社群檔裝得進去**。**不要拿 500 當可用證據**（我因此報錯過兩次）。
   ⚠️ **來源站鎖登入時，閘門過了也抓不到**：civitai 對作者鎖定的檔回
   `401 "The creator of this asset requires you to be logged in"` → 一律請使用者手動下載。
   放 civitai token 只解 **401 鎖登入**、**解不了 400 白名單**。
2. ⚠️ **userdata API 寫檔**：`POST /api/userdata/{file}` 可寫 user 目錄，但
   🔴 **含 `/` 的路徑回 405** → 子目錄要 **URL-encode 成 `%2F`**；`..` 一律 403。
   它只能寫 `user/default/` 底下——Manager 的目錄不在那裡。
   ⚠️ **前提限定**：這招只適用「你自己擁有、或機器主人明確授權你操作」的實例；在別人的機器上寫檔＝越權，不要做。
3. ⚠️ **`FL_HFDatasetDownloader` 節點**（Fill-Nodes）：`repo_id` + `repo_type` + `local_dir`（絕對路徑）
   + `download_trigger=True` → 抓整個 HF repo。**只適合小而快的下載；>10GB 不要走它**。
   - 🔴 **它下載整個 repo，不能挑檔** → 選 repo 前先量總大小
     （`curl -s "https://huggingface.co/api/models/<repo>?blobs=true"` 看 `siblings[].size`）。
     同一份權重有 4 個 quant 的 repo 可能合計 60GB，**改挑「只有你要那一顆」的單檔 repo 才划算**。
   - 🔴 **它會長時間佔住佇列** → 先 `GET /queue` 確認空的、判斷使用者沒在用再送，**並且主動告知他**。
   - 🔴 沒接 output 節點 → `prompt_no_outputs`，要掛一個 `PreviewAny` 之類的接收端。

### 🔴🔴 大檔（>10GB）的結論：請使用者手動下載，不要走節點

同一顆 **22.13GB** 的權重，節點下載**連兩次失敗**，最後是使用者自己抓才成功：

| 嘗試 | 結果 |
|:--|:--|
| 第一次 | 抓到 **18.9GB 就完全停止**（時間戳不再更新、網路流量歸零）；節點**不報錯也不重試**，掛在 `queue_running` 假死 |
| 重啟 ComfyUI 後續傳 | **跑 1 小時 0 進度** |
| 最後 | **使用者手動下載 → 一次成功** |

- 🔴 **中斷過的 HF 下載會留「孤兒 `.lock`」**：`.cache/huggingface/download/` 裡除了一顆 `<hash>.incomplete`，
  還有一顆 `<檔名>.lock`。**它會讓之後的續傳卡在等鎖**（那 1 小時 0 進度的真身）。
  → 要重試**先把整個 `.cache` 砍掉**，不要傻等；模型完成後那包 `.cache` 也是純垃圾。
  ⚠️ 判別法：只有 `*.metadata` 的子目錄＝內容根本沒下載下來，不用留。
- 🔴 **它會佔死執行佇列，而且 `/api/interrupt` 對它無效**（節點是阻塞式 I/O、不理 interrupt flag），
  `/api/queue {"delete":[...]}` 也刪不掉 running 中的 → **唯一手段是重啟 ComfyUI**
  （`GET /api/manager/reboot`，POST 會 405），代價是使用者排隊中的任務全掉。
  → 送之前先 `GET /queue` 確認空，**並主動告知「會佔佇列多久、這段時間他不能出圖」**。
- ✅ **診斷「下載還活著嗎」的正解：請使用者看檔案大小。**
  `/api/models/*` 只列完成的檔，`.cache` 裡的 `.incomplete` 從 API 根本看不到 →
  **人在機器前時，他那句「停在 18.9G、網路幾乎沒在動」比你在旁邊猜一萬次都準。**
  另：**API 秒回不代表任務正常** —— 那只是節點在 await。

### 反查伺服器真實路徑的三支招

- `POST /api/manager/component/save {"name": "x", "workflow": {...}}` **回應就是它寫入的絕對路徑**
  → 才知道 Manager 檔案落在哪個目錄（寫錯位置白忙一場）。
- `GET /api/lm/settings`（有裝 ComfyUI-Lora-Manager 時）直接吐 `default_lora_root` / `default_checkpoint_root`。
- `GET /system_stats` 的 `argv` 會洩漏啟動參數（含 `--output-directory`）→ 查磁碟配置先看它。

### 寫檔節點的三個坑

- WAS **`Save Text File`**（可吃絕對路徑）在 **`path` 與 output 目錄不同磁碟時直接爆
  `ValueError: Paths don't have the same drive`**。
- ComfyUI 內建 **`SaveText`** 只能寫 output 目錄（`filename_prefix` 想含子目錄會撞 `commonpath` 檢查）。
- 只想寫「文字」時上述都可能不夠用 → 退一步想：**能不能別寫檔**（改走節點自帶的下載能力）。

### 唯讀探測的節奏

- 查「有沒有這個節點」**逐顆問 `/object_info/<name>` 要小心**（不存在的也回 200 `{}`）；
  但**要 schema（欄位名／enum／output_node／python_module）就該逐顆問**——
  整包 6.8MB 抓一次有 90s 逾時的紀錄，查 3~5 顆用逐顆問快得多。

### ☁️ 模型檔最後一哩：本機暫存 → 驗 sha256 → 雲端同步碟或隨身碟

- 伺服器的 SSH／SMB 全關時，agent 沒有直接寫 `models/` 的路；但**使用者所有機器搬檔常走雲端同步資料夾**。
- 流程：下載到本機資料槽 → `sha256sum` 對來源 hash → 複製進同步資料夾（或隨身碟）→ 他自己拖進 `models/` 對應子目錄。
- ❌ 不要邊下邊寫同步資料夾（同步半成品會鎖檔、拖慢）；也不要從 agent 這端硬傳大檔（沒通道）。
- 🔴 **同步資料夾空間可能不夠（實例：18GB 模型包直接卡住）→ 直接改走隨身碟，不要等同步失敗**。
  查磁碟：`Get-Volume | Select DriveLetter,FileSystemLabel,SizeRemaining` → 看到外接碟就複製過去，
  複製完**在目的地重跑 `sha256sum -c`**（讀回驗，不是只看來源複製成功）。先問一句「是不是這顆」。
- 📦 **交付包裡一定要放一張「放這裡_目標位置.txt」**：每個檔該去的 `models/<類別>/`、
  載入器參數（steps／CFG／trigger word）、四個 sha256 全寫在同一張紙上 → 使用者插上目標機就能自己照著搬。
  ⚠️ **portable 版多一層 `ComfyUI\models\`**：目標是 `<..._portable>\ComfyUI\models\{...}`，
  寫成 `<..._portable>\models\` 會載不到檔。
- 🔴 **雲端「檔案隨選」會讓目標機拿到 0 byte 空殼**：搬之前 `attrib <檔>`，只有 `A` ＝本機實體完整；
  出現 `O`（離線）就先設「永遠保留在此裝置」等它抓下來。
- ✅ **HF 檔的 sha256 不必猜**：`curl -sL "https://huggingface.co/api/models/<repo>/tree/main?recursive=true"`，
  每筆 `lfs.oid` 就是 sha256 → 跟本地 `sha256sum` 逐碼比對。
- 🔴 **要承諾「叫伺服器自己抓」之前先驗白名單 membership**：抓 Manager 的 `model-list.json` 比對
  `save_path + base + filename`；命中才有機會 200，沒命中就別開這個口。

### 🔑 civitai 下載：一律用 query token，不要用 Authorization header

- key 位置：civitai 帳號頁 → **Security & Apps** → API Keys → Add API key，**只顯示一次**。
  ⚠️ 文件站右上那個 `Token: ••••` 是**測試用輸入框**，不是金鑰管理 → 在那頁找不到「Add API key」是正常的。
- key 存 `.env` 的 `CIVITAI_TOKEN=`。⚠️ 路徑要寫**絕對原生路徑**，不然 grep 不到 → 變數空 → 下載 401。
- 下載 URL：`https://civitai.com/api/download/models/<verId>?fileId=<fid>&token=$TOK`。
  🔴 **用 `Authorization: Bearer` 會在 307 轉到 R2 預簽網址後變 403**（簽名只涵蓋 host，多帶 header 被拒）
  → query 形式才穩。
- 驗證順序：`GET /api/v1/me`（看 tokenScope）→ `-r 0-4000000` 試 **206** → 全速下載 →
  `sha256sum` 對 `/api/v1/model-versions/<id>` 的 `files[].hashes.SHA256`。

📎 ComfyUI API 呼叫／出圖腳本撰寫的通用知識（`/prompt` 契約、`/object_info` 反查、`SaveVideo` 輸出鍵、批次 A/B seed）→ `references/api-scripting.md`

📎 端點探測與無 shell 下載的通用做法 → `references/remote-model-download-no-shell.md`

📎 兩支外部 workflow 的逐項缺件表（節點來源 repo ＋ 可用替代）→ `references/external-workflow-port-audit.md`

## 🔧 ComfyUI 升級／改版後的功能回歸檢查

在**共用產線**的機器上升版 ＝ 最高風險的動作。升完**不要憑「程式還開得起來」就交差**：

1. **節點集合 diff（最硬的一條）**：升版前先存一份整包 `/object_info`，升完再抓一份，兩邊相減。
   實測：**3,249 → 3,299（+50）、消失 0 個**。官方 release note 寫「node names and categories were
   cleaned up across the graph」時，**這是唯一能證明沒斷線的方法**。
2. **抽驗既有產線的關鍵 class_type**（不要只信 diff 的總數）。
3. `GET /internal/logs/raw` 抓 `IMPORT FAILED` 清單。⚠️ **要跟「升級前的 log」比對才算數**——
   升級前的 ring buffer 若沒有 import 區段，就**沒有基準**：只能講「功能沒斷（靠節點 diff）」，
   **不能斷定某個 pack 的失敗是升級造成的**（實例：升級後 5 包失敗，其中幾包是缺 Python 套件、
   與版本無關）。
4. 回報分三塊：**版本**／**節點增減**／**IMPORT FAILED 清單（含能不能歸因）**——
   使用者要的是「有沒有壞、壞在哪、你怎麼知道的」。
5. 升版前的必做：記下現行版本／custom_nodes 清單／**本機 core patch**（升級會蓋掉）。

## 偵錯 SOP

1. 腳本 FAIL → curl `/history` 找 prefix 圖是否存在（**常常其實有出圖！**）
2. `/queue` 看 running／pending（其他 agent 的 cron 會塞車）
3. `/system_stats` 看 VRAM free（殘留模型正常）
4. 確認後手動 `/view` 撈圖，再決定是否修腳本
5. 📎 **`/history` 進階鑑識**（還原「這顆實際用什麼模型／prompt 出去」＋孤兒圖對帳）→ 見
   `references/comfyui-history-forensics.md`
