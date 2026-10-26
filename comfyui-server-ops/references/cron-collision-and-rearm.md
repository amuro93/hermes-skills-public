# 2026-09-17 凌晨三點：16 支批次整批歸零的對帳

事件：使用者 早上問「凌晨三點的影片排程有問題都沒執行？」
→ 真相：**有執行、跑起來就掛、而且掛完自己把自己關掉**（所以後續什麼都沒有）。

---

## 1. 時間軸（兩邊 log 對出來的）

| 時刻 | 事件 | 證據來源 |
|:--|:--|:--|
| `03:00:13.894` | H3 深夜出片（`e12b0970b0ee`）起火 | `cron/executions.db` `started_at` |
| `03:00:13.896` | 站姿互轉批次（`a4e168f76d46`）起火 ← **同一個兩毫秒內** | 同上 |
| `03:00:14` | 批次印出第一行 log 後，**第一個動作（上傳 `stand.png`）就被 reset** | `stand_trans_batch.log` 最後一行 |
| `03:00:33` | 批次收屍：`ConnectionResetError [WinError 10054]`，**0/16** | `cron/output/a4e168f76d46/2026-09-17_03-00-33.md` |
| `03:02:37` | H3 那支才進 prompt、開始載 20GB 模型 | 5080 `/internal/logs/raw` |
| `03:05:43` | 5080 端：**來自 `gpu-box-2`（本機）的 upload 請求吃 `WinError 121`** | 同上 `Error handling request from …` |
| `03:21:41` | H3 跑完（`Prompt executed in 00:19:04`），CPU 曾在 97.7% | 同上 |

客戶端 traceback（節錄）：

```
  File "<hermes_home>\scripts\gen_transition_stand_batch.py", line 136, in one
    up_f = G.upload_image(first, f"st_{label}_first.png")
  ...
ConnectionResetError: [WinError 10054] 遠端主機已強制關閉一個現存的連線。
```

伺服器端（`WinError 121` 是 Windows 的 socket 等待逾時，不是腳本錯）：

```
[ERROR] Error handling request from gpu-box-2
  File "D:\…\ComfyUI\server.py", line 466, in upload_image
    post = await request.post()
  ...
OSError: [WinError 121] 訊號等待逾時。
```

同一小時內 `01:32:03`、`01:33:10` 也各有一筆 `WinError 121`（`/view` sendfile 回傳時）。
→ **這台機器在重載下會掉 socket，不是單一偶發。**

## 2. 為什麼腳本會整批歸零（我的錯）

`gen_transition_stand_batch.py` 的 docstring 寫著：

> 單支失敗不炸整批（try/except + 下載重試）

**但 code 裡只有「下載」有重試，`upload_image` / `submit` 完全沒有，且 `one()` 沒有 try/except**
→ 第一個 upload 吃一次 reset，例外直接穿出 `main()` → 16 支歸零。

**教訓：docstring 有寫不代表 code 有做；修批次腳本要讀 code。**

## 3. 修法（實際 diff 的行為）

```python
def retry(fn, n=4, wait=15, what=""):
    last = None
    for i in range(n):
        try:
            return fn()
        except Exception as e:
            last = e
            log(f"  {what} 失敗({i+1}/{n})：{type(e).__name__}")
            if i + 1 < n:
                time.sleep(wait * (i + 1))
    raise last

def preflight(max_wait=2400):
    # 輪詢 /queue 到 running+pending 連續兩次為 0 → 緩衝 20s 才開跑；逾時照跑
```

- `one()`：`upload_image` 包 4 次退避、`submit` 3 次；整支 try/except 回 `error:<Type>`
- `main()`：非 dry 時先 `preflight()`
- 腳本已支援「成品存在就 skip」→ **補跑＝直接重跑同一支**

## 4. 排程修復（terminal job 的坑）

`a4e168f76d46` 是 `repeat.times=1` 的一次性 job → 跑失敗後 `state=completed`、`enabled=false`、`next_run_at=null`
→ **永遠不會再跑**（使用者 說「都沒執行」的真身）。

三條路全被守門擋掉：

```text
hermes cron edit a4e168f76d46 --schedule "0 4 * * *"
  → Cannot activate terminal cron job '…' through update_job; use cron resume --run-now or --at.
hermes cron resume a4e168f76d46 --at 2026-09-18T04:00:00+08:00
  → Cannot re-arm recurring jobs: re-arm is one-shot-only; use plain resume or cron run.
hermes cron resume a4e168f76d46            # 想先 resume 再 edit
  → Cannot activate terminal cron job '…' through update_job; use cron resume --run-now or --at.   # 迴圈
cronjob_manage(action=update, …)
  → Cannot activate terminal cron job '…' through update_job; use cron resume --run-now or --at.
```

✅ **解法＝建新 job 接手（舊的留著當紀錄，`cron_incidents` 還指著它）**：

```
cronjob_manage(action=create, name="本機-站姿互轉過渡-04:00",
               schedule="2026-09-18T04:00:00+08:00",   # 絕對 ISO ＝ 一次性
               no_agent=True, script="gen_transition_stand_batch.py", deliver="origin")
→ job_id 5a74f6bf05cc, next_run_at 2026-09-18T04:00:00+08:00, repeat once, state scheduled
```

重點：**`next_run_at` 要自己讀回來對（`+08:00` 且與名稱相符）**，不要只看 API 回 `success`。

## 5. 順手學到的診斷反射

- `GET /internal/logs/raw` = 伺服器的環形 log（JSON，約 300 筆），**用 Python 解析後按 `t` 過濾時間窗**，
  比 `grep` 整個 dump 快很多（dump 是單行 JSON，`grep` 一次吐一萬字）。
- 判斷「腳本邏輯錯」vs「socket 被掉」：**客戶端 reset ＋ 伺服器端查無此請求 = 請求沒進 handler**。
- `cron/executions.db` 讀之前先 `shutil.copy2` 到 `%LOCALAPPDATA%/Temp`（live 檔不能直開）。
- 檔名要看清楚：本機在 `gpu-box-2`，5080 在 `gpu-box`（**不是** `10.0.0.x`，
  一開始 ping 錯網段會得到「機器掛了」的假結論）。
