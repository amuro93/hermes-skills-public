# 附錄：雲端 GPU 產線（Colab CLI 類）的操作知識

> 這是 `windows-python-tool-compat` 的**附錄**，不是獨立 skill。
> 主文談「外部工具在 Windows 上怎麼才跑得動」；這裡放**雲端額度／session／授權／條款**這一層的操作知識，
> 因為那條產線正好是「Windows 上的 POSIX-only CLI」的實例，兩者一起讀才完整。

## 這份附錄的範圍

⚠️ **不含 `scripts/runner.py`**。它來自第三方 repo
[`killkli/minimax-h3-colab-skill`](https://github.com/killkli/minimax-h3-colab-skill)（`--depth 1` clone 即可）。
本附錄只記錄操作知識與驗收標準，沒有在公開版做過完整端到端重跑。

要重現的完整條件：
1. clone 該 repo（`install.sh` 只裝 Codex skill 那層，**不用跑**），直接呼叫 `scripts/runner.py`
2. `termios.py`／`tty.py` stub 與 `os.killpg` → `taskkill /T` 的補丁照**主文 §2／§3** 做
3. 用 `env -u PYTHONPATH` 執行，避免吃到外層 venv
4. 授權（OAuth）由使用者本人完成一次，憑證只留在本機 `~/.config/colab-cli/token.json`

驗收標準仍以本文列的四項為準（檔案本體＋`ffprobe`＋`progress*.json`＋餘額），與 runner 由誰實作無關。

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

---

## Windows 移植三件套

這一節已升級為主文：見 SKILL.md §2（POSIX-only stdlib stub）、§3（subprocess 的 POSIX 引數）、§1（`env -u PYTHONPATH`）。
