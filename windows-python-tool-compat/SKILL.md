---
name: windows-python-tool-compat
description: Use when 外部 Python 工具在 Windows 跑不起來。
version: 1.0.0
author: Drizzt Studio
license: MIT
tags: [windows, python, venv, porting, compat]
metadata:
  hermes:
    tags: [windows, python, venv, porting, compat]
    related_skills: [windows-app-install-verification]
---

# 在 Windows 主機上跑外部 Python 工具：標準相容處理

> 📖 **範圍宣告：本文是「經驗文件」，不是下載即用的工具。**
> 內容是「哪種錯要用哪種修法」的判讀與操作知識，**沒有附上任何可執行的修補腳本或測試套件**，
> 也沒有在公開版對某個特定工具跑過完整驗收。要照做的話，請把每一步套到你自己的工具上驗。

## When to Use

- `uv tool install` 裝的 CLI、clone 回來的第三方 repo、獨立 venv 的工具，在你的 Windows 機器上 import／執行失敗。
- 看到 `ModuleNotFoundError`（特別是 `pydantic_core._pydantic_core`）或 `No module named 'termios'/'tty'`。
- 要把 Linux/macOS 導向的 Python 工具（含它自己的測試）搬到 Windows 主機上跑。
- 工具的 OAuth／登入得由使用者本人完成，需要安排「他做那一步、我接手其餘」的交接。

適用範圍：任何**不是 Hermes 本體**的 Python 工具 —— `uv tool install` 裝的 CLI、clone 回來的 repo 腳本、獨立 venv。
在 Windows 上它們會踩到幾個固定的坑；照下面順序處理，通常一次就通，不必出動 Docker／WSL。

先決：環境是 git-bash（MSYS）+ native Windows Python；Hermes profile 目錄常被 junction 到別的磁碟，用哪個路徑寫都通（重點是前後一致）。

## 步驟 0：先用最便宜的方式驗它能不能被 import

不要一開始就跑真正的工作（可能花錢／佔佇列）。先：

```bash
env -u PYTHONPATH <tool> --help          # CLI 能不能進得去
env -u PYTHONPATH python3 <repo>/scripts/<entry>.py --help   # 純 stdlib 腳本的介面
```

`--help` 通過 ＝ import 層全綠（這是後面所有補丁的驗收點）。

## 步驟 1：脫掉 PYTHONPATH（先排除第一個病，不然後面全誤判）

**症狀**：`ModuleNotFoundError: pydantic_core._pydantic_core`，而且 traceback 裡的套件路徑落在
**Hermes 自己 install 的 venv**（`AppData\Local\hermes\installs\...\venv\...`）而不是那個工具自己的 venv。

**根因**：Hermes 的 terminal 會注入 `PYTHONPATH=<hermes venv site-packages>`（`echo $PYTHONPATH` 一看就知道）。
PYTHONPATH 的搜尋優先序在直譯器自己的 site-packages **之前** → 外部 venv 的工具載到 Hermes 的套件，ABI 不符就炸。

**修法**：呼叫外部 venv 的工具一律
```bash
env -u PYTHONPATH <tool> ...
```
別用 `PYTHONPATH=` 空字串（可能被當成空路徑項）；`env -u` 才是乾淨移除。

> 這個錯誤指紋跟 `hermes-windows-migration`（**本系列未收錄**）裡記的「`hermes update` 換 Python → ABI 不符」**一模一樣、病因不同**：
> 差別在 traceback 的套件路徑指向「誰的 venv」。別看到 pydantic_core 就直接往 ABI 那條查。

## 步驟 2：POSIX-only stdlib 模組缺失 → 補最小 stub

**症狀**：`ModuleNotFoundError: No module named 'termios'`（還有 `tty`/`pty`/`fcntl`/`pwd`/`grp`）。
關鍵：若它在 **module 層 import**，整個 CLI 連 `--help` 都進不去，即使那個功能你根本不會用到。

1. 先掃範圍，確認要補多少：
```bash
grep -rn "^import \(termios\|tty\|pty\|fcntl\|pwd\|grp\)" <tool-venv>/Lib/site-packages/<pkg> --include=*.py
```
2. 若只在互動式路徑（console attach、REPL）用到 → 寫最小 stub：
   常數給值（TCSANOW／TCSADRAIN／ICANON…），函式一律 `raise NotImplementedError('... is POSIX-only')`（不要靜默 no-op，否則行為錯得看不出來）。
3. **stub 要放進那個工具自己的 venv site-packages**（`C:\Users\<user>\AppData\Roaming\uv\tools\<tool>\Lib\site-packages\`）。

⚠️ 要 shadow 的是 stdlib 名 → **只能放該 venv 的 site-packages，不能塞 PYTHONPATH**（會污染所有 python 行程，連 Hermes 自己都遭殃）。
⚠️ uv tool 重裝／升級會蓋掉 stub，第三方 repo 的補丁會被 `git pull` 蓋掉 → 重裝後要重放，並在該產線的 skill 記一筆。

## 步驟 3：subprocess 的 POSIX 專屬參數

- `os.killpg()` 在 Windows 不存在，**而且只在 timeout／清理路徑炸** —— 平常跑得順會讓你以為移植成功。
- `Popen(start_new_session=True)` 是 POSIX 專屬。

修法：抽一個 helper，別散在呼叫點
```python
def _signal_child(child, *, force):
    if os.name == "nt":                      # Windows：沒有 process group
        cmd = ["taskkill", "/T", "/PID", str(child.pid)]
        if force:
            cmd.insert(1, "/F")
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return
    os.killpg(child.pid, signal.SIGKILL if force else signal.SIGTERM)
```
＋ `start_new_session=os.name != "nt"`。

## 步驟 4：需要使用者本人完成的互動式認證

外部工具要 OAuth 時（登入他自己的雲端帳號）：

- **做一個雙擊就能跑的 `.cmd` 給他**，不要讓他手打落落長的一行指令（完整路徑加引號、`chcp 65001` 以免中文亂碼、結尾 `pause` 讓他看得到結果）。
- 在 `.cmd` 裡就把三步講清楚：開網址 → 授權 → 把碼貼回**這個視窗**。
- 🔴 **授權碼／憑證不進聊天**：碼貼他自己的視窗，我只看驗證輸出（例如餘額、`whoami`）。
- 事前自己先跑一次同樣的指令（跑到「吐網址＋等輸入」就中止）確認整條路徑通 —— 這是最省成本的端到端驗證，不完成登入、不耗額度。

## 步驟 5：判讀第三方 repo 的測試失敗

Windows 上第三方測試 harness 很常整批紅 —— **別因此改專案程式碼，也別判定專案壞掉**。先分類：

- 失敗集中在「exec 一個假 CLI／shell 腳本」的測試：假 CLI 是 `#!` shebang 腳本＋`chmod 0o755`，Windows 沒有 POSIX exec → 環境問題。
- 失敗包含 `FileNotFoundError: <cli> is not installed or is not on PATH`：PATH 沒帶上（跑測試前 `export PATH="$HOME/.local/bin:$PATH"`）。
- 純邏輯測試（解析、驗證、字串處理）若全綠 → 專案本身沒問題。

## 步驟 6：OpenCV 靜默讀不到中文路徑

**症狀**：`cv2.imread()` 回 `None`，下一行 `img.shape` 就炸 `AttributeError: 'NoneType' object has no attribute 'shape'`，但檔案明明存在。**PIL 開得起來、cv2 讀不到** —— 這個對比就是指紋。

**根因**：Windows 的 `cv2.imread` / `cv2.imwrite` 走 ANSI 路徑，非 ASCII（中文、日文、全形字）一律失敗，而且**不報錯、直接回 None**。

**修法**：腳本一開始就用 buffer 版 wrapper，不要等炸了才改：

```python
import os, cv2, numpy as np

def imread_u(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)

def imwrite_u(p, img, q=96):
    ok, buf = cv2.imencode(os.path.splitext(p)[1], img, [cv2.IMWRITE_JPEG_QUALITY, q])
    if not ok:
        raise RuntimeError("imencode failed: " + p)
    buf.tofile(p)
```

`cv2.FaceDetectorYN` 吃 numpy array，只要圖是 imdecode 進來的就不受影響；`cv2.VideoCapture("中文.mp4")` 也一樣要繞（先確認能不能開，失敗一樣是靜默的）。

## 附：references／worked example

- `references/colab-h3-lane-windows.md` —— MiniMax H3 Colab 產線（uv tool CLI + clone 來的 runner + 遠端複製貼上 OAuth）
  在 Windows 上的建置步驟與**當時的**驗證紀錄，可當同類工具的模板。
- `references/colab-lane-ops.md` —— **附錄**：同一條產線的雲端側操作知識（額度／session 生命週期、GPU 規格分層、
  平台條款與工作負載分流、OAuth 交接）。想知道「這份工作該不該走雲端」看這份。

⚠️ **那份紀錄不是「已完全可用」的證明，請照實讀**：
- OAuth 只驗到「吐授權網址＋等貼碼」就中止（刻意不完成登入、不耗額度）→ **token 落地那段沒有實測過**
- 專案自帶的離線測試是 8 項中 4 綠 4 紅，紅的全是「Windows 沒有 POSIX exec」的 harness 問題
- 🔴 **`--help` 跑得起來 ≠ import 全綠**：`--help` 只證明「這條 import 路徑在當前這部機器上過得去」。
  真正的驗收要跑一次**會走到目標程式碼**的命令（例如 `runner.py usage`），或對每個要用的模組 `python -c "import <mod>"` 逐一驗。
