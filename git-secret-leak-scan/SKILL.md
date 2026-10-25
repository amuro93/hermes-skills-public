---
name: git-secret-leak-scan
description: Use when 懷疑 API key 外洩或查 GitHub repo 含 secrets/DB。批次掃描、驗活、WSL2 git-filter-repo 歷史清理。
version: 1.0.0
author: Drizzt Studio
tags: [security, git, secret-scan, git-filter-repo, wsl2, devsecops]
---

# Git Secret Leak Scan（Git 倉庫機密掃描與歷史清理）

## 觸發時機
- 懷疑 API key 外洩（如 LLM 平台出現未知模型或異常呼叫）
- 準備將私人 repo 轉為公開（Public）前的全面資安體檢
- 定期檢查多個 GitHub repo 是否誤追蹤 `.env`、`*.db` 或硬編碼憑證

---

## 🔴 1. 掃描輸出鐵則：永不印出命中字串本身

掃描腳本的**輸出格式**本身就是外洩途徑。若腳本把命中的 key 原文印到終端機，真實金鑰就會直接落入 Agent session log、對話紀錄與雲端日誌。

**規則（無例外）**：
- 命中一律只印 **`<檔名>:<行號>` ＋ `[<類別>]` ＋ `<長度>`**，**絕不印命中字串**（連前幾碼都不要）。
- ✅ 正確：`[xai-key] config/settings.py:15 (len=52)`
- ❌ 錯誤：`[xai-key] config/settings.py:15 → xai-AZ6wi...`
- **最安全的脫敏是根本不把值取出來印**（只用 `len(m.group(0))` 計算長度）。

---

## 🔍 2. 掃描整個 GitHub 帳號的兩階段流程

### 第一階段：先用 GitHub API 列檔案樹（不要先全量 clone）

要盤點數十個 repo 裡有多少不該入庫的檔案時，第一趟只做「檔名層」盤點：

```bash
t=$(gh repo view <owner>/<repo> --json defaultBranchRef --jq .defaultBranchRef.name)
gh api "repos/<owner>/<repo>/git/trees/$t?recursive=1" \
  --jq '.tree[] | select(.type=="blob") | .path'
```

這招只打 trees API 拿檔名清單、完全不 clone，整個帳號幾十個 repo 也是幾十秒內掃完，直接抓出哪些 repo 追蹤了 `.env`、`*.db`、`*.sqlite`、`*credentials*.json`、`*.pem`。

| 檔名層命中樣態 | 判定 |
|:--|:--|
| 追蹤了真的 `.env` | 🔴 真外洩，走補救流程 |
| 追蹤了 `*.db`／`*.sqlite` | 🔴 **高風險** —— 文字正規表達式掃描器會跳過含 NUL byte 的二進位檔（**對 DB 完全是瞎的**），必須開 DB 檢查各表資料筆數 |
| 追蹤了 `.env.example`／`.env.template` | ⚠️ 用「值長度 vs 該平台真 key 長度」比對——真 key 長度請以各平台文件或後台實際 key 為準，範例檔的佔位符通常明顯偏短；低於真 key 六成者視為佔位符 |

### 第二階段：使用內建脫敏掃描器 `scripts/scan_repos_secrets.py`

針對 clone 下來的 repo 跑完整長度 pattern 掃描：

```bash
python scripts/scan_repos_secrets.py /path/to/cloned_repos -o secret_scan_result.json
```

**判讀順序（決定嚴重度，勿單看 hits 總數）**：
1. **先看 `db_tracked` 並開 DB 數筆數**：
   ```bash
   python -c "import sqlite3,os; p='<repo>/<x>.db'; print(os.path.getsize(p)); con=sqlite3.connect(p); [print(t, con.execute(f'SELECT COUNT(*) FROM \"{t}\"').fetchone()[0]) for (t,) in con.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")]"
   ```
   - `0 KB／無表` → 佔位空檔，無風險
   - `對話歷史／使用者表／記帳表有數百～數千筆` → 🔴 **最高優先級真資料外洩**
2. **排除常見假警報**：
   - `hardcoded-password` 命中 `UPDATE users SET password=''`（SQL 清空語句）或 `declare -x PWD="/home/..."`（shell 快照環境變數）
   - `auth.json` 內僅存 `secret_fingerprint: "sha256:..."`（不可逆雜湊指紋，非明文 secret）
   - 教學 `.md` 文件中的官方範例佔位 key

---

## 🧪 3. 金鑰驗活與撤銷（Rotate vs Revoke）

1. **驗活只印 HTTP 狀態碼**：
   - DeepSeek：`GET https://api.deepseek.com/user/balance`
   - GitHub PAT：`GET https://api.github.com/user`
   - SendGrid：`GET https://api.sendgrid.com/v3/user/account`
   - 回 `200` ＝ 仍有效（高風險，立即處理）；回 `401` ＝ 已撤銷失效。
2. **注意 CDN 快取與傳播延遲**：
   - 部分平台（如 SendGrid `/v3/scopes`）有邊緣快取，刪除 key 後仍會在短時間內回 `200`。應改打 `user/account` 端點，並在執行 `DELETE` 後等待 60~90 秒再複測確認轉為 `401`。
3. **無法登入後台時的自救撤銷法（API Self-Revoke）**：
   - 若忘記平台後台密碼、但外洩的正好是一把具備管理權限（Full Access）的 API key，可直接用該把 key 呼叫平台的列出與刪除端點（例如 `GET /v3/api_keys` 取得 ID 後，打 `DELETE /v3/api_keys/<id>` → `204`），不需登入網頁後台即可將帳號下所有有效 key 徹底銷毀。

---

## 🧹 4. Windows 上清理 Git 歷史：透過 WSL2 執行 `git_filter_repo`

`.gitignore` 只擋未來新增，**拔不掉已進入歷史 commit 的 `.db` 或 `.env`**。必須改寫整個 Git 歷史。

### ⚠️ Windows 原生環境的坑
- 在 Windows（git-bash）直接跑 `python -m git_filter_repo --invert-paths` 會在 `fast-export` 階段噴 `OSError: [Errno 22] Invalid argument`。
- 用 `git filter-branch` 則會因 MSYS 路徑自動轉換把 `/d` 當成參數而失敗。

### ✅ 可靠解法：在 WSL2 直接呼叫 `git_filter_repo.py` 單檔

`git_filter_repo.py` 是純 Python 標準庫單檔腳本，不需在 WSL2 額外裝 `pip`，直接用 WSL2 的 `/usr/bin/python3` 指過去執行即可：

```bash
# 1. 必須做完整 clone（不可用 --depth 1，否則無歷史可重寫）
git clone https://github.com/<owner>/<repo>.git clean_work
cd clean_work

# 2. 透過 WSL2 從全歷史移除目標檔案（WSL2 因 CRLF 會認定 dirty，必加 --force）
wsl.exe -d Ubuntu -- bash -c "cd /mnt/c/path/to/clean_work && python3 /mnt/c/Python311/Lib/site-packages/git_filter_repo.py --force --invert-paths --path 'data/chat_history.db'"
```

### 🔴 歷史重寫後的三項必查（防漏網之魚）

1. **先查 Default Branch 名稱再 Force Push**：
   不要假設預設分支一定叫 `main`。若原 repo 是 `master`，推到 `HEAD:main` 只會新建分支，遠端 `master` 依然留著髒檔案：
   ```bash
   DEFAULT_BRANCH=$(gh repo view <owner>/<repo> --json defaultBranchRef --jq .defaultBranchRef.name)
   git remote add origin https://github.com/<owner>/<repo>.git
   git push --force origin HEAD:$DEFAULT_BRANCH
   ```
2. **檢查遠端是否有其他舊備份分支**：
   `git-filter-repo` 只重寫本地有 checkout 的分支。若遠端還有 `backup-*` 等舊分支，舊 commit 裡的 DB 仍會留在遠端倉庫中。用 `git branch -r` 檢查，將無用的舊備份分支刪除。
3. **驗收一律「重新 clone 到新目錄」**：
   不要在剛跑完 filter-repo 的本地目錄驗收。重新 `git clone` 一份全新的下來，確認：
   - `find . -name "*.db"` 為空
   - `git log --all --oneline -- <檔案路徑>` 輸出為 **0 筆**
