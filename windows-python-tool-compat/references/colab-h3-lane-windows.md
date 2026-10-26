# Worked example：MiniMax H3 Colab 產線在 Windows 上從零到可用

第三方工具＝`killkli/minimax-h3-colab-skill`（clone 來的 repo，用 `colab` CLI 把 H3 Ref2VA 丟到 Google Colab 跑）。
通用技法見 SKILL.md；這裡記這條產線的具體值。

## 一次性安裝（Windows 原生，不需要 Docker／WSL）

```bash
uv python install 3.12
uv tool install --python 3.12 google-colab-cli        # → C:\Users\<user>\.local\bin\colab.exe
git clone --depth 1 https://github.com/killkli/minimax-h3-colab-skill.git ~/projects/tools/minimax-h3-colab-skill
```

- repo 的 `install.sh` 只裝 Codex skill 那層，**不用跑**；直接叫 `scripts/runner.py`（純標準庫，3.11+）。
- `runner.py` 子命令：`usage`（讀 CU 餘額）／`start`／`stop`／`batch`／`single`。

## 這條產線踩到的兩個 POSIX 坑（已補，重裝要重放）

1. `termios` / `tty` stub —— `colab_cli/console.py` 在 module 層 import，掃描結果全專案只有這兩顆、且只在互動 console 用到。
   stub 放 `C:\Users\<user>\AppData\Roaming\uv\tools\google-colab-cli\Lib\site-packages\{termios,tty}.py`。
2. `scripts/runner.py`：`os.killpg` → `_signal_child()`（Windows 走 `taskkill /T`）＋ `start_new_session=os.name != "nt"`。

驗收：`env -u PYTHONPATH colab --help` ✅、`env -u PYTHONPATH python3 .../runner.py batch --help` ✅。

## 授權（只有使用者能做的一步）

一次性檔 `~/projects/colab_h3/auth_colab.cmd`（雙擊）：內容＝`"C:\Users\<user>\.local\bin\colab.exe" --auth=oauth2 usage`。

- 流程是**遠端複製貼上**式 OAuth：redirect 到 `sdk.cloud.google.com/applicationdefaultauthcode.html`，**不開 localhost**
  → 任何瀏覽器（手機也行）、headless／容器環境都適用，不必開 port。
- token 落地：`~/.config/colab-cli/token.json`（Windows＝`C:\Users\<user>\.config\colab-cli\token.json`）。
- `--auth=oauth2 usage` 授權完直接印 CU 餘額 ＝ 同時驗證授權 ✅
- 額度＝Google AI Pro 附的 Colab CU（Pro 每月約 200 CU）；**消耗速率要實測**（跑前跑後各記一次 `usage` 差額），別信新聞寫的「1 CU 一支」。
- 🔴 **條款不允許的內容不要走這條**：違規的後果是整個 Google 帳號（訂閱＋雲端硬碟）一起出事，不只是這條運算節點。
  → 動手前先讀平台條款，把「這份工作適不適合走雲端免費額度」當成**路由決策**，而不是先送再說。

## 批次（省 CU 的正解）

manifest：
```json
{"jobs": [{"id": "a1", "title": "...", "output_name": "...",
            "prompt_file": "/work/prompts/a1.txt",
            "reference_images": ["/work/refs/a.png"],
            "duration_seconds": 12, "seed": 123}]}
```
- `prompt_file` 或 `prompt` 二選一；`reference_images`／`images` 同義；1–9 張對應 prompt 內 `<Picture 1..9>`；`duration_seconds` 預設 12（4–15）；另有 `output_path`。
- **一次 manifest 一個 session**：模型只載一次；別一支一 session（重載＝白燒 CU）。
- 導引式 prompt：shots 用 `start_seconds`／`description`／`dialogue`／`speaker`，外層 subject_definitions／summary／retention_analysis／overall_soundscape／non_diegetic_music。
- 產出含音軌，runner 會用 ffprobe 驗 video＋audio 兩條 stream。
- 推論端是 `Comfy-Org/MiniMax-H3` ＋ ComfyUI `MiniMaxH3ReferenceToVideo`（跟本機同家族，prompt 知識可沿用）；Ref2VA 走官方 ref2v **4-step** Turbo LoRA、HEIGHT 1376、預設 A100 high-mem。

## 驗證紀錄（拿來比對「裝好了沒」）

- 授權流程實跑到「吐授權網址＋等貼碼」後中止 ✅ —— 驗證整條路徑最省成本的方式（不完成登入、不耗 CU）。
- 離線測試 `python3 -m unittest discover -s tests`：8 項 4 綠 4 紅，**紅的全是 Windows 沒 POSIX exec 的 harness 問題**
  （假 CLI 是 `#!` shebang 腳本＋`chmod 0o755`，另有 1 項 PATH 上沒 colab），純 Python 邏輯那 4 項全過。
  → 不要為此改專案程式碼。
