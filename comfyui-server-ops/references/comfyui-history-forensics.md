# ComfyUI 執行歷史鑑識：使用者 問「怎麼多出好幾張／怎麼有別的風格」時用（2026-09-10 實例）

## 症狀
使用者 在 ComfyUI 網頁看到 output 裡有一批預期外的圖（例：「早上出的 A 主題出了好幾張，而且還有一張 B 主題的？」），
但 cron 只交付 2 張。**不要憑猜回答**——ComfyUI `/history` 會留下每一輪 submit 的輸出檔名，可以完整還原。

## 方法
```bash
cd <hermes_home> && python3 scripts/list_comfy_history.py
```
- 腳本：讀 `GET /history`（帶 CF Access headers）→ 逐一列任務的 outputs 檔名（`images`/`videos`/`gifs` 三個 key 都掃）
- 判讀靠**檔名自帶的資訊**：`<prefix>_<slug>_<date>_<HHMMSS>_<slot>` 或 `<prefix>_<date>_<n>_00001_.png`
  - 時間戳 → 有幾輪、間隔多久（= 中間有重跑）
  - slug → 每輪跑出哪個主題
  - ComfyUI 同名 prefix 重複 submit 會自動加 `_00002_` 計數器，可區分「原產」vs「手動重跑 duplicate」

## 2026-09-10 實例（完整還原）
`rotation_script.py` 出圖（輪播型 cron）：
| 時間 | 產出 | 說明 |
|:--|:--|:--|
| 01:00:55 | `<prefix>_styleA_<date>_010055_1`（風格 A **1 張**）| 第一輪自動輪到的風格；第 2 張沒成功 |
| 01:03:58 | `<prefix>_styleB_…_010358_1/_2`（風格 B ×2）| 重跑 → 輪到下一個風格 |
| 01:09:57 | `<prefix>_styleB_…_010957_1/_2`（風格 B ×2）| 再重跑一次 |

→ 交付的是最後那批；風格 A 那張從沒下載、變成**廢圖留在 ComfyUI output**，使用者看到就困惑。

## 根因：順序輪（sequence/position 檔）的進度是累積的，重跑會推進一格
`rotation_script.py` 的 `pick_style()`：
- `_read_seq(path)` 只讀 `position`、**沒有每日重置**（`date` 欄位只是紀錄）
- `_write_seq()` 每次 +1
→ 所以「出圖失敗／候選不足 → 重跑」會直接跳到**下一個**風格，造成三個症狀：
1. 一天內跑掉 2 個以上風格
2. **交付的主題 ≠ 當天該輪到的主題**
3. 被跳過那格的圖變廢圖堆在 output

## 通則與修法
- ⚠️ **凡是靠 sequence/position 檔推進的 cron，重跑都會吃掉進度**——跟「被 timeout 吃掉好幾個名額」（見 SKILL.md「Wrapper timeout」段）是同一家族
- **修法①**：失敗重跑走「指定模式」而不是自動輪下一格（`rotation_script.py --style "<剛才那個風格>"` / `--role "<角色>"` 指定時**不推進序**，腳本要支援這個開關）
- **修法②**：手動把 sequence 檔的 `position` 退回去再重跑
- **收尾**：ComfyUI output **不會自動清**，被丟棄的候選會一直躺著 → 交付時主動說明或清掉，別讓 使用者 看到孤兒圖再來問

---

## 🔎 進階：反查「這一顆當時實際跑出去的 prompt／模型」（2026-09-21 實證）

要證明「這批是不是用對的模型跑的」、或「動作句逐字到底寫了什麽」，**唯一可信來源是 `/history` 裡那份 workflow**，
再用**輸出檔名**把那批過濾出來。這是**身分／數值驗證，不是 vision 判圖**，可以自己做。

```python
# urlopen 沒有 headers= 這個參數（會 TypeError）；要用 Request 包起來
from urllib.request import Request, urlopen

req = Request(f"{SERVER}/history?max_items=80", headers=H)
hi = json.loads(urlopen(req).read())
for pid, node in hi.items():
    outs = [it["filename"] for _, o in (node.get("outputs") or {}).items()
            for k in ("images", "videos", "gifs") for it in (o.get(k) or [])]
    if not any(f.startswith("<prefix>") for f in outs):        # ← 用檔名前綴鎖定那一批
        continue
    seq = node.get("prompt")
    seq = seq[2] if isinstance(seq, list) and len(seq) > 2 else seq  # 🔴 prompt 欄是 LIST，workflow 在 index 2
    for k, v in (seq or {}).items():
        if not isinstance(v, dict):
            continue
        if v.get("class_type") == "UNETLoader":
            print(v["inputs"]["unet_name"])
        if v.get("class_type") == "TextEncodeQwenImageEditPlus":    # 🔴 qwen-edit 的正向 prompt 在這裡
            print((v.get("inputs") or {}).get("prompt"))
```

### 🔴 三個一定會踩的解析坑
1. **`prompt` 欄是 LIST 不是 dict**（`[number, pid, workflow_dict, …]`，ComfyUI 0.31.1~0.34 都一樣）→ 直接 `.items()` 會炸，先取 `seq[2]`。
2. **正向 prompt 的節點型別看圖譜**：
   - **Qwen-Image-Edit 圖譜＝ `TextEncodeQwenImageEditPlus`**，文字在 `inputs.prompt`（**不是 `inputs.text`**）。
   - 一般 KREA2／SD 圖譜才是 `CLIPTextEncode` + `inputs.text`。
   - ⚠️ **qwen-edit 圖譜裡也有 `CLIPTextEncode`（那是別的東西）→ 只認 `CLIPTextEncode` 會全部抓到空字串，
     還以為「伺服器沒紀錄」**（第一次就是這樣印出 11 個空行、白忙一輪）。
     保險寫法：兩個型別都試，取抓到且含關鍵字（例：`image1`）的那段。
3. **`max_items` ＝最近的 N 筆，舊的會被後面的 cron 擠掉**：要查**隔天以前的**任務（例：昨天傍晚那顆）常常早就沒了 →
   **要驗就當天驗**，或退而求其次看腳本 log 裡那行 `models: UNET=… | CLIP=…`。

### 用途實例
- 確認「這批是哪一版模型跑的」：看 `UNETLoader.unet_name` 是否等於你預期的那顆檔名。
  不同版本／量化的出圖風格差很多，而這是**事後唯一能確認的方法**（成品已經沒有 config 可查）。
- 確認「動作句裡到底寫了哪句」：把 `TextEncodeQwenImageEditPlus.prompt` 逐字拉出來，才能跟 使用者 對帳
  （例：抓到「全身從頭頂到腳底完整入鏡」那句＝母圖是半身、公式卻寫全身的直接矛盾證據）。

---

## 🔁 使用者 自己重出了幾支／幾張（出現 `_00002_`）→ 逐項 diff 反查他改了什麼（2026-10-02 實證）

使用者 只會說「我有重出兩個，放在 <資料夾>」——**他改了什麼不會講，而且不該問**（問了像在推責任）。
`/history` 裡有他那輪的完整 workflow，**用檔名把他那輪挑出來、跟你自己那輪逐欄位相減**即可。

```python
# 同一支片會有兩個 prompt_id：你的 _00001_ 與他的 _00002_
import hashlib
for pid, ent in d.items():
    graph = ent["prompt"][2]                     # 🔴 prompt 欄是 LIST，workflow 在 [2]
    outs  = [f["filename"] for _, o in (ent.get("outputs") or {}).items()
             for k in ("images", "videos", "gifs") for f in (o.get(k) or [])]
    if not any("_00001_" in f or "_00002_" in f for f in outs):
        continue
    h3 = next(v["inputs"] for v in graph.values()
              if str(v.get("class_type", "")).startswith("MiniMaxH3ImageToVideo"))
    lora = {str(n["inputs"].get("lora_name")): n["inputs"].get("strength_model") for n in graph.values()
            if n.get("class_type") == "LoraLoaderModelOnly"}
    print(outs, "prompt_md5=" + hashlib.md5(str(h3["prompt"]).encode()).hexdigest()[:12],
          "length=" + str(h3.get("length")), "WxH=" + f'{h3.get("width")}x{h3.get("height")}', lora)
```

**要相減的四欄（順序就是判斷順序）**：
1. **`prompt` 的 md5**——相同＝他**沒有**動文字，那問題就只可能在參數（這次兩支 md5 全等 → 一秒排除「是不是我 prompt 寫錯」）。
2. **LoRA 名稱＋`strength_model`**——使用者 親手調的通常是這個（這次兩顆都被**往下**調）。
3. **`length` / `width` / `height`**——長度與畫幅。
4. **`SigmaShift` / sampler / seed**——同前幾欄都一樣才往下看。

**收尾（比查到更重要）**：
- 反查完要**回報「你動了哪幾欄、我動了哪幾欄」**，並把結論寫回配方（例：`minimax-h3-comfyui` 的
  「動作量低 ≠ LoRA 強度不夠」就是靠這次同 prompt 對照實驗定案的）。
- **收他的檔要留兩份**：`*_00002_raw.mp4`（原檔，附完整 sha256）＋ conform 後舞台規格版；
  **不要直接覆蓋你自己的 `_00001_`**，兩版並存才能繼續對照。
- 使用者 重出的檔在 OneDrive，**尺寸通常是未 conform 的原始輸出**（如 768×1152）→ 要進素材包就得自己 conform。
- ⚠️ **同 prompt 不同 `length` 會得到不同幀數，且 `length` 與實際幀數不是 1:1**（實測 length=194 → 209 幀，
  但另一輪 length=192 → 192 幀）→ **一律 `ffprobe` 驗實際幀數，不要相信 length 字面值。**
