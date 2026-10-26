> 併自 `comfyui-api-scripting` skill：ComfyUI API 呼叫／出圖腳本的通用知識。
> 維運面（共用機佇列、逾時判讀、history 陷阱）見上層 `SKILL.md`。

# ComfyUI API 腳本撰寫（通用）

寫 ComfyUI 出圖/影片腳本（POST /prompt + 輪詢 + 下載）的通用知識。跨 KREA2/H3/任何模型都適用。

## 基本流程
1. `POST /prompt`（JSON: `{"prompt": {node_id: {class_type, inputs}}}`）→ 拿 `prompt_id`
2. 輪詢 `GET /history/{完整 prompt_id}` 等 outputs
3. 從 outputs 找 filename → `GET /view?filename=...&type=output` 下載

## 鐵則（全部實測踩過）
- **`urlencode` 在 `urllib.parse`，不在 `urllib.request`**！寫錯拋 AttributeError，被 `except: pass` 吞掉 → 腳本無限輪詢到超時誤報 FAIL（伺服器端任務其實秒完成）
- **except 不許空 pass**——至少 `print(e)`，不然 bug 永遠查不到。出問題先看 except 吞了什麼
- **submit 後印 pid** 供 debug
- 輪詢用 `/history/{完整 pid}`（0.5s 小請求）；**截斷 pid 會回 `{}`**；掃 `/history` 全部很大易 timeout
- **`/history/{pid}` 與完整 `/history` 的 `prompt` 欄是 LIST 不是 dict**（ComfyUI 0.31.1 實測）——想掃節點找 CLIPTextEncode / SaveImage 會空手而歸。改對 `json.dumps(prompt)` 下 regex（`cosplaying as (...)`、`filename_prefix`）就能認出角色/prefix
- **同名 filename_prefix 重複 submit → server 檔名自動加 `_00001_`/`_00002_` 計數器**：`_00001_` = 首次提交（cron 原產），`_00002_`+ = 手動重跑 duplicate。救援/交付時要認這 suffix，別交錯
- 診斷「出圖超慢/腳本 FAIL」：先查伺服器 `/history` 有沒有圖——有圖 = 出圖成功，是腳本等/下載 bug；沒圖才懷疑伺服器（佇列/VRAM）
- **write_file 寫含反斜線路徑的腳本 → 反斜線多包一層 → submit 400 `value_not_in_list`**：`write_file` 寫出的 `MODEL = "krea2\\\\\\\\muse....safetensors"` 檔案實際 4 層反斜線，Python 解析成雙反斜線，而 server object_info 清單要的是單反斜線（手寫檔只有 2 層 → 解析成單反斜線 ✅）。診斷看 400 body `node_errors[1].errors[].received_value`；修法用 python heredoc `read().replace()` 改檔案層數，或直接複製已知可用腳本的路徑字串
- **submit payload 必須包 `{"prompt": wf}`（2026-08-16 實測）**：直接把 workflow dict `json.dumps(wf)` 丟 `/prompt` → 伺服器回 400 `no_prompt`「No prompt provided」。外層 `{"prompt": wf}` 不能省；submit 失敗要把 response body 印出來（HTTPError code 看不出原因）
- **SaveVideo 輸出掛在 history 的 `images` key，不是 `videos`（2026-08-16 實測）**：任務 status=success、outputs 有值，但 `out.get("videos", [])` 撈不到 → 下載邏輯 `for key in ("videos", "images")` 兩邊都掃，且檢查 filename 結尾 `.mp4`/`.webm`（SaveVideo 把 mp4 塞在 images 陣列）

## 常用端點
| 端點 | 用途 |
|:---|:---|
| `POST /prompt` | 提交 workflow（JSON） |
| `GET /history/{pid}` | 查單任務結果（完整 pid！） |
| `GET /history` | 全部歷史（大，勿高頻掃） |
| `GET /view?filename=&type=` | 下載圖/影片 |
| `POST /free` `{"unload_models": true, "free_memory": true}` | 清模型快取（VRAM 不夠時） |
| `GET /system_stats` | VRAM/佇列狀態 |
| `GET /object_info/{node}` | 查節點 schema（required/optional 參數名） |
| `POST /upload/image`（multipart `-F "image=@圖"`） | 上傳參考圖到 input 目錄 |

## SaveVideo 節點參數（影片輸出）
- **必給 `format`（"mp4"）+ `codec`（"auto"）**——缺 format 驗證 400；缺 codec 採樣跑完才卡 `SaveVideo.execute() missing codec`（浪費 3 分鐘！）
- filename_prefix 可用 `video/xxx` 子目錄格式

## 節點 inputs 格式
- 一般輸入：`["<node_id>", <slot>]`
- dict 輸入（如 `ref_images`）：`{"ref_image_0": ["<node_id>", 0]}`
- 動態 combo（如 SaveVideo codec）：直接傳 key 字串 `"auto"`

## 排程 cron 出圖
- cron script 參數要放 `~/.hermes/scripts/` 用相對檔名
- 排程是 **UTC**：台灣 21:00 = UTC 13:00、台灣 02:00 = UTC 18:00
- 日期驅動 seed + run_offset 參數（同天補跑不重複構圖）

## 批次出圖 + 模型 A/B 對比
- 大數量批次（如服裝詞庫 45 款全出）：JOBS list 存 `(prefix, seed, prompt)`，逐張 subprocess 呼叫生成腳本，background 跑 + notify_on_complete，不需要並行（熱機 ~5.7s/張）
- **同 seed 換模型重跑做 A/B**：若 A 版肢體表現不佳 → 改 MODEL 常數為 B 版重跑，**seed 全部不變**、OUTDIR 換獨立目錄（`output_a` vs `output_b`），兩版並存以便同構圖對比
- 批次時間實測（RTX 5080 熱機、queue 空）：45 張 = 4.3 分鐘（平均 5.7s/張）
- ⚠️ **wrapper import 改 OUTDIR 的坑**：寫 wrapper import 另一支批次 script（`import batch_gen as g`）後改 `g.OUTDIR` / `g.MODEL` 重跑時，**原 script 的 `os.makedirs` 只在 import 當下執行一次（建的是原目錄）**，wrapper 改完 OUTDIR 沒補 `os.makedirs(g.OUTDIR, exist_ok=True)` → `shutil.move` 直接 FileNotFoundError
- 模型速度知識：所有 KREA2 都是 Krea2-turbo 架構，**快慢看量化版本**——NVFP4（50 系 Blackwell 優化）最快（~5.7s/張），不是「turbo 版」的差別；估時程先看檔名格式

## 相關
- MiniMax H3 影片 workflow 見 `minimax-h3-comfyui`
