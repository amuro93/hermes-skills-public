---
name: cloud-gpu-lane-ops
description: Use when 跑雲端 GPU 產線（Colab CLI）：額度、session、Windows。
version: 1.0.0
author: Drizzt Studio
license: MIT
tags: [colab, cloud-gpu, credits, windows, oauth, ops]
metadata:
  hermes:
    tags: [colab, cloud-gpu, credits, windows, oauth, ops]
    related_skills: [minimax-h3-comfyui, systematic-debugging]
---

# 雲端 GPU 產線操作（Colab CLI 類）

> 📖 **範圍宣告：本文是「經驗文件」，不是下載即用的工具。**
> `runner.py` 屬第三方 repo（見下節），**沒有隨附**；本 skill 只記錄在 Windows 上要補哪些 patch、
> 以及額度／session／驗收的操作知識，沒有在公開版做過完整端到端重跑。

## When to use / 觸發時機
- 要用雲端 GPU 額度跑生成任務（例：Colab CLI 跑 MiniMax-H3 Ref2VA，本機只上傳參考圖＋prompt，跑完拉成品回來）
- 雲端 session 開不起來、額度怎麼算、要不要重試
- 要把一套 POSIX-only 的雲端 CLI 搬到 Windows 主機上跑

配套：花錢與送件紀律＝本 skill §1（額度與 session 生命週期）＋ §2（GPU 規格與額度層級）；
通用除錯紀律看 `systematic-debugging`。各模型自己的 prompt 結構與失敗模式，留在該產線的 skill。

## 本文範圍（缺什麼、你要自己補什麼）

⚠️ **本文不含 `scripts/runner.py`**。它來自第三方 repo
[`killkli/minimax-h3-colab-skill`](https://github.com/killkli/minimax-h3-colab-skill)（`--depth 1` clone 即可），
本 skill 只記錄「在 Windows 上要補哪兩個 patch 才跑得動」，以及額度／session／驗收的操作知識。

要重現的完整條件：
1. clone 該 repo（`install.sh` 只裝 Codex skill 那層，**不用跑**），直接呼叫 `scripts/runner.py`
2. 依 §4 補 `termios.py`／`tty.py` stub，並把 `os.killpg` 換成 `taskkill /T`
3. 用 `env -u PYTHONPATH` 執行，避免吃到外層 venv
4. 授權（OAuth）由使用者本人完成一次，憑證只留在本機 `~/.config/colab-cli/token.json`

驗收標準仍以本 skill 列的四項為準（檔案本體＋`ffprobe`＋`progress*.json`＋餘額），與 runner 由誰實作無關。

## 0. 首次建置 runbook（從零到能跑一支片）— Windows 實測 2026-09-29

**A. 一次性建置**
1. `uv python install 3.12`（CLI 需要 3.12；用 3.14 會爆）
2. `uv tool install --python 3.12 google-colab-cli` → 執行檔在 `C:\Users\<user>\.local\bin\colab.exe`
3. 補 Windows stub：在 `%APPDATA%\uv\tools\google-colab-cli\Lib\site-packages\` 放 `termios.py`、`tty.py`（見 §4）
4. **跑 CLI 一律用這個前綴**：`export PATH="$HOME/.local/bin:$PATH"; env -u PYTHONPATH <cmd>`
5. 驗證（唯讀）：`colab usage`

**B. 登入（使用者本人做一次，約 2 分鐘）**
- 給一支可雙擊的 `.cmd`（例：`$HERMES_HOME/colab_h3/auth_colab.cmd`），內容是 `colab --auth=oauth2 usage`
- 它會**即印授權網址**（複製貼上授權碼的遠端流程，可手機授權、不走 localhost）→ 使用者登入、複製授權碼、貼回**他自己的視窗**
- 完成後畫面上出現 `Current balance: N compute units` → 這就是授權成功的證據（憑證不進聊天、不落地）
- 之後開 session／跑片全由 runner 自動處理，**不需要再登入**

**C. 跑一支片（日常操作）**
1. 準備 `refs/<參考圖>.png` ＋ `prompts/<name>.txt`（結構化分鏡表）
2. 寫 `manifest_<name>.json`（單支 `{"jobs":[{...}]}`；多支放同一個 jobs 陣列＝共用一次模型載入，最省）
3. 送：
   `cd "$HERMES_HOME/tools/minimax-h3-colab-skill" && env -u PYTHONPATH python3 -u scripts/runner.py batch --manifest <manifest>.json --stop-on-complete --no-high-mem --progress <progress>.json --timeout 3600`
4. 驗收四項：檔案本體存在＋`ffprobe` 尺寸/時長/音軌 ＋ `progress*.json` 的 `session_status: stopped` ＋ `colab usage` 餘額

**D. 建議工作區結構**
- 工具：`$HERMES_HOME/tools/minimax-h3-colab-skill`（本機 clone、已 patch runner.py）
- 工作區：`$HERMES_HOME/colab_h3/`（`refs/` `prompts/` `out/` `manifest_*.json`）
- notebook：`<repo>/assets/MiniMax_H3_Turbo_Colab.ipynb`（`WIDTH, HEIGHT` 常數＝尺寸旋鈕；改完先驗 `json.load` 再上傳）

## 1. 額度與 session 生命週期
- **create session 失敗（503 Service Unavailable／搶不到容量）＝不計費**：實查餘額不會動、session 自動關閉、job 標 cancelled
  → **直接重試就好，不要改任務內容**。連續失敗才動規格（先 `--no-high-mem` 退回標準記憶體 → 再換 GPU 型號）；
  最後一步才是**降任務長度**——那會改內容，**要先問使用者**。
  - 實測 2026-09-29：A100 **high-mem 先 503**，退標準記憶體成功一次後又遇到**連標準版也 503**（A100 整段時間被佔滿）→ 解法就是**換 L4**（各型號容量分開搶，不必等）。
- **計費延遲入帳**：跑完馬上看餘額會少扣，要隔一次再讀才準 → 報成本時說「實扣」並註明讀取時點。
- **一律帶「跑完自動關 session」的旗標**（如 `--stop-on-complete`）；**一次只開一個 session**——同時兩個會搶 capacity，成本也失控。
- **驗收一律驗檔案本體**：背景批次回 exit 0 但 stdout 可能是空的 → `search_files (target='files')` + `ffprobe`（尺寸/時長/音軌）+ 讀 `progress*.json` + 查餘額，四項都對才算成功。
- 額度查詢用**唯讀**指令（如 `colab usage`）；**有些「探測腳本」會真的提交任務扣錢**，別拿它當查詢工具。

## 2. GPU 規格與額度層級
- `colab new --gpu` 支援 **T4 / L4 / G4 / H100 / A100**；H100 要更高階訂閱。
- `--high-mem`（大記憶體機型）要 Pro/Pro+ 額度，而且**是最容易 503 的那個規格**——搶不到就先退標準記憶體版。
- 額度是使用者的資產 → 出手前實查餘額（不要用他口述的舊數字），送完回報實扣。

## 3. 雲端平台服務條款（ToS）與工作負載分流
- **免費雲端 GPU 額度通常有嚴格的內容與用途審查**：使用者的雲端帳號往往綁定核心雲端硬碟與個人資產
  → 觸發風控是**整個帳號被鎖**，而不只是單一運算節點中斷。
- 因此雲端免費通道**僅用於標準公開素材與一般運算任務**；需無審查或載入自訂私有權重的工作負載，應配置於本地 GPU 或專為高自由度推論設計的專屬雲端 API。
- 部署初期即應明確劃分工作負載路由規則，避免混用導致帳號風險。

## 4. 把 POSIX-only CLI 搬到 Windows（實測三件套）
1. **`termios` / `tty`**：POSIX 專屬模組，import 就爆（通常只有互動 console 路徑用到）
   → 在該 CLI 的 venv `site-packages/` 放 stub（常數定義＋函式 `raise NotImplementedError`），非互動指令就過得去。
2. **`env -u PYTHONPATH`**：Hermes 的 terminal 會把 `PYTHONPATH` 指向自己的 venv → 蓋掉 uv tool venv 的套件
   （症狀：`pydantic_core` 載錯／`No module named 'pydantic_core._pydantic_core'`）。
   **跑任何 `uv tool install` 裝的 CLI 一律加 `env -u PYTHONPATH`。**
3. **`os.killpg` / `start_new_session`**：Windows 沒有 `os.killpg` → patch 成 `os.name == "nt"` 時走 `taskkill /T /PID`，並在 Windows 關掉 `start_new_session`。
- 執行前記得 `export PATH="$HOME/.local/bin:$PATH"`（uv tool 的 bin 位置）。
- 這些修在**本機 clone**，上游更新會蓋掉 → 把「動過哪些檔、改了什麼」列在產線 skill 裡，升級後重打。
- 先跑**離線測試**（不耗額度）驗邏輯層：Windows 上「測 POSIX exec」的測試紅是預期（假 CLI 是 `#!` shebang 腳本、`chmod 0o755`），**純 Python 邏輯那幾項才是判斷點**。

## 5. OAuth／授權流程（憑證不落地）
- 給使用者一支**可雙擊的腳本**（Windows `.cmd`）去開授權網址，**授權碼貼在他自己的視窗**——憑證不進聊天、不寫檔。
- 授權完成後立刻用唯讀查詢印一次額度，當作**授權成功的證據**（他看得到數字才安心）。
- 要他擴權時把每個 scope 的實際用途講清楚（他會問「全選嗎」）。

## 6. 與既有產線的關係
- 雲端＝**第三條備援**：本地 GPU 免費但一次一支、晚上會被關機；付費雲端 API 有幣別成本。
- **能力邊界自己量一次再寫成表**（同素材 A/B：本地 vs 雲端），使用者會逐支給判定——他的判定就是結論，不要用抽幀＋vision 推翻他。

## 坑
- 背景程序 exit 0 ＋ 空輸出 ≠ 成功（見 §1 驗收四項）。
- **不要用 `patch` 直接改遠端 notebook 的 JSON**：會把引號吃進去、JSON 破損 → 用**行級修補腳本**改（先驗 `json.load` 再上傳）。
- notebook 裡**硬編的尺寸／長度常數就是可用旋鈕**（例如 `WIDTH, HEIGHT`——通常 32 的倍數都可），但**參考圖比例最好跟輸出同比例**。
- 上游 repo 可能**沒有 license**：記錄下來給使用者判斷，不要拿它當「所以不要用」的理由。
