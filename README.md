# Hermes Agent Skills — Public Collection

**English** | [**繁體中文說明 (Traditional Chinese)**](#hermes-agent-skills--公開精選集-繁體中文)

A curated set of [Hermes Agent](https://hermes-agent.nousresearch.com) skills extracted from real projects built at **Drizzt Studio**.

Most of these were written after hitting an actual wall — a provider that silently timed out, a model that ignored its own prompt, a cron job that fired at the wrong hour — and encode the fix plus the trap that caused it. Where something was **not** fully verified, the skill says so explicitly (see each skill's scope section); nothing here claims more than was actually tested.

One entry is derived from upstream work and is labelled as such: **`systematic-debugging`** is adapted from an existing MIT-licensed project, marked in both its frontmatter and its entry below.

## What's Inside (15 Skills)

### 🛡️ Agentic Engineering, Security & Data
- **`systematic-debugging`** — Four-phase root-cause discipline for AI coding agents, tracing masked errors across silent `except: return []` chains, and project-wide post-fix sweeps. **Adapted from [obra/superpowers](https://github.com/obra/superpowers) (MIT — see `author` / `license` in its frontmatter); the method is upstream, the source-specific notes in `references/` were added from our own projects.**
- **`git-secret-leak-scan`** — Two-pass GitHub account secret & SQLite DB auditing designed for AI agents (zero-plaintext output by design to prevent LLM context leakage, live key verification, API self-revocation, and WSL2 `git-filter-repo` history purging).
- **`sqlite-cjk-fulltext-search`** — Chinese/CJK full-text search using SQLite FTS5 `trigram` tokenizer, handling the silent `<3` character query blind spot via automatic `LIKE` fallback, and WAL isolation rules.
- **`hermes-local-state-safety`** — Safe handling of a live agent state DB (`state.db`/WAL): copy-then-open or `mode=ro` only (a bare connect triggers WAL recovery and can permanently break the gateway's write ability), three-layer liveness checks that separate "process is up" from "platform connected" from "turns actually complete", and auditing which tool/model was really called from `state.db` instead of guessing.

### 🖥️ Local LLM & Cloud GPU Infrastructure
- **`mac-mlx-ollama-deployment`** — Running LLMs on Apple Silicon via Ollama's native MLX engine (2× faster decode than GGUF/llama.cpp), importing custom safetensors weights with `--experimental`, and fixing Cloudflare Tunnel 403 Host header rejections.
- **`cloud-gpu-lane-ops`** — Operating headless cloud GPU lanes (Colab CLI): quota lifecycle, automatic session teardown, and porting POSIX-only Python CLIs to Windows (`termios` stubs, `PYTHONPATH` isolation).

### 🪟 Windows Agent Operations
- **`windows-python-tool-compat`** — Why external Python tools break on Windows and how to fix each failure mode: POSIX-only imports (`termios`/`tty`/`fcntl`) stubbed into the tool's own venv `site-packages`, MSYS-vs-native path confusion, and `PYTHONPATH`/process-tree handling.
- **`windows-app-install-verification`** — Verifying a third-party app/driver install on Windows before calling it done: UAC and reboot expectations surfaced up front, vendor launcher residue checks, and checking resource ownership before grabbing a shared GPU/service.

### 🎬 ComfyUI & Multimodal Video Generation
- **`comfyui-server-ops`** — Running a *shared* ComfyUI box over HTTP: queue discipline so you don't monopolise the GPU, the `/history/{pid}` returning `{}` trap, why a timeout is not a failure (read `/queue` first), why `/prompt` is **not** safe to blind-retry, partial-result persistence so a killed wrapper doesn't lose the batch, cron scheduling and timezone pitfalls, downloading models when you have no shell on the box, and node-set diffing after a ComfyUI upgrade. The API-scripting basics (`/prompt` contract, `/object_info` inspection, `SaveVideo` output keys, batch A/B seeds) live in its `references/api-scripting.md`.
- **`ltx25-video-generation`** — Lightricks LTX-2.5 22B audio-video generation on 16GB VRAM (NVFP4 transformer + INT8 Gemma-4, duration-head auto-length, and NAG + DualCFG workflows).
- **`minimax-h3-comfyui`** — MiniMax H3 24fps audio-video generation on 16GB/12GB GPUs: pruned GGUF vs safetensors quantisation, FastH3 8-step V2 distillation, `BlockSparseAttention` dotted-key API syntax, and verified HuggingFace download scripts.
- **`autoip-video-api`** — AutoIP MSR video API integration: multi-subject reference face locking, single-person shot splitting, and ffmpeg `atempo` voiceover pacing fixes.
- **`ai-video-qa`** — How to actually verify AI-generated video: frame-sampling density that matches the claim you want to make, the four ways sampling fakes a false negative, `SSIM`/seam-ratio acceptance gates that must be calibrated per source lane, first/last-frame traps (objects spawning out of nowhere, walls fading, camera geometry overriding prompt), closed-loop via ping-pong, a vision-model capability boundary that stops you trusting thumbnails, and the symptom→root-cause table. Ships four reusable ffmpeg measurement scripts.

### 📚 Long-Form Chinese Fiction Engineering
- **`longform-novel-zh`** — Chapter-by-chapter drafting workflow using a bounded context memory card (Story Bible + ≤300-char rolling summary + chapter outline). Cross-chapter consistency auditing (forms of address, spatial layouts, timelines, character knowledge chains) is included as `references/cross-chapter-consistency.md`.
- **`fiction-chapter-qc`** — Automated pre-submission quality gate (includes `scripts/verify_chapter_qc.py`): style-tic frequency thresholds, curated Simplified-Chinese leakage detection, and longest-contiguous-shared-segment detection against previous chapters (default ≥8 characters).

## Layout

```
<skill-name>/
├── SKILL.md          # the skill itself — description, when to use, how
└── references/       # optional deeper notes (API tables, worked examples)
```

## Using these

Drop a directory into your Hermes Agent skills path (typically `~/.hermes/skills/`), or point your own agent at the `SKILL.md` files directly — they are plain markdown with YAML frontmatter and read fine as documentation.

⚠️ If you redistribute these (or a subset), keep the `LICENSE` file with them: it carries the MIT notice for this collection **and** the upstream notice for the one adapted skill.

## Notes

- All skills are in Traditional Chinese or English as originally written. Mixed-language is intentional: the author's working language is Chinese, and API documentation quotes stay in their original form.
- No credentials are included. Hostnames, paths and account-specific details have been generalised (`example.com`, `~/projects/`, `<user>`); internal topology, incident logs and private asset names were deliberately removed rather than rewritten.
- Each skill states its own scope: what was actually exercised, and what still has to be supplied or verified by you (some skills reference a client/runner that is **not** bundled).
- Some skills reference hardware (RTX 5080, Apple Silicon, 4070). Those are performance notes, not requirements — the techniques are portable.

## Licence

MIT — use them, fork them, ship them.

---

# Hermes Agent Skills — 公開精選集 (繁體中文)

這是一套提煉自 **Drizzt Studio** 實際開發與運行經驗的 [Hermes Agent](https://hermes-agent.nousresearch.com) 技能庫（Skills）。

大部分內容是撞牆後寫下的：被多層 `except: return []` 靜默吞掉的錯誤、在 720p 下 FP16 注意力溢位冒出綠點、把真實金鑰印進對話紀錄的掃描腳本。**沒驗證過的部分會在各支 skill 的「範圍」段落明講**，不把推論寫成實測。

其中一支有明確上游出處：**`systematic-debugging`** 改寫自一個 MIT 授權的既有專案，frontmatter 與下方條目都標了。

## 收錄內容（共 15 支實戰 Skill）

### 🛡️ AI Agent 工程、資安與中文檢索（4 支）
- **`systematic-debugging`** — 專治 AI Coding Agent「亂猜亂改」的四階段根因除錯紀律：追蹤被多層 `except: return []` 靜默吞掉的錯誤鏈，以及修復後的跨專案同型態問題清查。**改寫自 [obra/superpowers](https://github.com/obra/superpowers)（MIT，見該檔 frontmatter 的 `author` / `license`）—— 方法論是上游的，`references/` 裡的專案案例筆記才是我們自己補的。**
- **`git-secret-leak-scan`** — 專為 AI Agent 設計的 GitHub 全帳號機密與 SQLite DB 兩階段稽核（內附 `scripts/scan_repos_secrets.py` 預設零明文脫敏掃描器，防止真 Key 落入 LLM Context 外洩）、金鑰驗活與無後台權限時的 API 自我撤銷、以及 Windows 透過 WSL2 `git-filter-repo` 清洗歷史的完整 SOP。
- **`sqlite-cjk-fulltext-search`** — SQLite FTS5 `trigram` 中文全文檢索實作：解決預設分詞器搜不到中文的問題、自動分流 `<3` 字短詞回退 `LIKE`（避開 `trigram` 對兩字詞安靜回傳 0 筆的盲區），以及 WAL 跨進程隔離原則。
- **`hermes-local-state-safety`** — 使用中的 agent 狀態庫（`state.db`／WAL）安全操作：只能「先複製再開」或 `mode=ro`（裸 connect 會觸發 WAL recovery，可能讓 gateway 永久失去寫入能力）、把「進程活著／平台連上／turn 跑得完」分三層驗，以及從 `state.db` 撈出「某工具或某顆模型這幾天真的被叫幾次」而不是靠印象答。

### 🖥️ 本地 LLM 與雲端 GPU 基礎設施（2 支）
- **`mac-mlx-ollama-deployment`** — 在 Apple Silicon 上使用 Ollama 原生 MLX 引擎部署 LLM（解碼速度為 GGUF/llama.cpp 的 2 倍）、`--experimental` 匯入自訂 safetensors 權重，以及修復 Cloudflare Tunnel 403 Host 標頭阻擋。
- **`cloud-gpu-lane-ops`** — 將無頭雲端 GPU（Colab CLI）作為自動化運算產線：配額與工作階段生命週期管理、工作負載分流，以及將 POSIX 專屬 Python CLI 移植至 Windows 的三件套解法（`termios` stub、`PYTHONPATH` 隔離、程序樹終止）。

### 🪟 Windows Agent 維運（2 支）
- **`windows-python-tool-compat`** — 外部 Python 工具在 Windows 上跑不起來的逐項解法：POSIX 專屬 import（`termios`／`tty`／`fcntl`）要 stub 進該工具自己的 venv `site-packages`、MSYS 與原生路徑不互轉的混淆，以及 `PYTHONPATH` 與程序樹收尾。
- **`windows-app-install-verification`** — 在 Windows 裝第三方 app／驅動之後怎麼驗收才算完成：開跑前先講清楚會跳 UAC 與可能要重開機、廠商 launcher 的解壓與登錄檔殘留檢查、以及動共用 GPU／服務前先確認所有權。

### 🎬 ComfyUI 與多模態影音生成工程（5 支）
- **`comfyui-server-ops`** — 用 HTTP API 操作一台**共用** ComfyUI 產線機的維運知識：佇列紀律（不要連續霸佔 GPU）、`/history/{pid}` 回 `{}` 的假死陷阱、為什麼 timeout 不等於任務失敗（先讀 `/queue`）、為什麼 `/prompt` **不能**無腦重試（非冪等，會多排一張）、成果 partial 落盤讓被砍掉的 wrapper 不至於整批歸零、cron 排程與時區坑、沒有 shell 時怎麼把模型弄進機器，以及 ComfyUI 升級後的節點集合 diff 驗證。API 腳本撰寫基礎（`/prompt` 契約、`/object_info` 反查、`SaveVideo` 輸出鍵、批次 A/B seed）收在它的 `references/api-scripting.md`。
- **`ltx25-video-generation`** — Lightricks LTX-2.5 22B 影音同步生成於 16GB VRAM 的完整配置（NVFP4 Transformer + INT8 Gemma-4、duration-head 自動片長與 NAG + DualCFG 工作流）。
- **`minimax-h3-comfyui`** — MiniMax H3 24fps 影音生成完整指南（16GB/12GB 顯卡配置）：Pruned GGUF 與 safetensors 量化選型、FastH3 8-Step V2 蒸餾加速、`BlockSparseAttention` 點號展開參數防 720p FP16 溢位綠點、真實底片膚質去油光 Prompt，以及驗證下載腳本。
- **`autoip-video-api`** — AutoIP MSR 鎖臉影片生成 API 整合：多主體參考鎖臉、單人分鏡防臉崩原則，以及使用 ffmpeg `atempo` 修正配音語速過快問題。
- **`ai-video-qa`** — 驗收 AI 生成影片的完整方法論：抽幀密度要跟「你想下的結論」匹配、稀疏取樣如何偽造出假陰性、SSIM／接縫比值門檻必須按素材來源分 lane 校準、首尾幀過渡的物件憑空生成與牆面漸變、運鏡詞被幾何條件壓過、ping-pong 重組成閉環、vision 不能信的邊界（縮圖拼圖會自信地講錯），以及症狀→根因快查表。附 4 支可重用 ffmpeg 量測腳本。

### 📚 長篇中文小說工程（2 支）
- **`longform-novel-zh`** — 固定長度記憶卡（小說聖經 ＋ 300 字以內滾動進度摘要 ＋ 單章大綱）的長篇連載防爆 token 工作流（附 4 份標準模板）。跨章一致性審查（稱呼弧線、空間配置、時間軸、角色知識鏈）以 `references/cross-chapter-consistency.md` 收在同一個 skill 內。
- **`fiction-chapter-qc`** — 交稿前自動化品管閘門（附 `scripts/verify_chapter_qc.py`）：口頭禪頻率門檻、簡體字誤用字典掃描、與前文比對「最長連續共同片段」（預設 ≥8 字，長度可調；編碼讀不進來時以 exit 2 中止而不是假裝通過）。

## 如何使用

將任一技能資料夾放入你的 Hermes Agent 技能目錄（預設為 `~/.hermes/skills/`），或直接讓你的 AI Coding Agent 讀取 `SKILL.md` 檔案——所有檔案皆為帶有 YAML frontmatter 的標準 Markdown，亦可直接作為技術文件閱讀。

## 目錄結構

```text
<skill-name>/
├── SKILL.md          # 技能主檔 — 觸發條件、使用時機、完整步驟與踩坑紀錄
├── references/       # 進階參考資料（API 規格表、實測紀錄，選配）
├── scripts/          # 可直接執行的自動化或驗證腳本（選配）
└── templates/        # 工作流 JSON 或文件模板（選配）
```

## 備註

- 所有技能依原始撰寫習慣採用繁體中文或英文。中英夾雜是刻意的：作者的工作語言為中文，而程式碼與 API 規格保留英文原貌。
- 不含任何憑證。主機名稱、路徑與帳號相關細節皆已通用化（`example.com`、`~/projects/`、`<user>`）；內部拓樸、事故紀錄與私人資產名是**直接移除**，不是改寫成別的代稱。
- 每支 skill 各自標明範圍：哪些真的跑過、哪些要你自己補或自己驗（部分 skill 引用的 client／runner **沒有**隨附）。
- 部分技能提及特定硬體（如 RTX 5080、Apple Silicon、RTX 4070），這些是實測效能基準而非硬性需求，相關技術皆可跨平台移植。

## 授權條款

MIT License — Copyright (c) 2026 **Drizzt Studio**。歡迎自由使用、修改與發布。

---

Maintained by **Drizzt Studio**.
