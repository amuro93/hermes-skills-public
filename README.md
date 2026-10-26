# Hermes Agent Skills — Public Collection

**English** | [**繁體中文說明 (Traditional Chinese)**](#hermes-agent-skills--公開精選集-繁體中文)

A curated set of production-tested [Hermes Agent](https://hermes-agent.nousresearch.com) skills, extracted from real projects built at **Drizzt Studio**.

These are not toy examples. Each skill was written after hitting an actual wall — a provider that silently timed out, a model that ignored its own prompt, a cron job that fired at the wrong hour — and encodes the fix plus the trap that caused it.

One of them is an exception and is labelled as such: **`systematic-debugging`** is adapted from an existing upstream MIT-licensed skill. Its frontmatter and its entry below say so, rather than presenting it as work written from scratch here.

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
- **`comfyui-api-scripting`** — Writing reliable headless ComfyUI API runners (`POST /prompt`, `/object_info` schema inspection, `SaveVideo` output key traps, and batch A/B seed testing).
- **`ltx25-video-generation`** — Lightricks LTX-2.5 22B audio-video generation on 16GB VRAM (NVFP4 transformer + INT8 Gemma-4, duration-head auto-length, and NAG + DualCFG workflows).
- **`minimax-h3-comfyui`** — MiniMax H3 24fps audio-video generation on 16GB/12GB GPUs: pruned GGUF vs safetensors quantisation, FastH3 8-step V2 distillation, `BlockSparseAttention` dotted-key API syntax, and verified HuggingFace download scripts.
- **`autoip-video-api`** — AutoIP MSR video API integration: multi-subject reference face locking, single-person shot splitting, and ffmpeg `atempo` voiceover pacing fixes.

### 📚 Long-Form Chinese Fiction Engineering
- **`longform-novel-zh`** — Chapter-by-chapter drafting workflow using a bounded context memory card (Story Bible + ≤300-char rolling summary + chapter outline).
- **`cross-chapter-consistency`** — Auditing and refactoring multi-chapter novels across forms of address, spatial layouts, timelines, and character knowledge chains.
- **`fiction-chapter-qc`** — Automated pre-submission quality gate (includes `scripts/verify_chapter_qc.py`): style-tic frequency thresholds, curated Simplified-Chinese leakage detection, and 8+ character cross-chapter verbatim repetition scanning.

## Layout

```
<skill-name>/
├── SKILL.md          # the skill itself — description, when to use, how
└── references/       # optional deeper notes (API tables, worked examples)
```

## Using these

Drop a directory into your Hermes Agent skills path (typically `~/.hermes/skills/`), or point your own agent at the `SKILL.md` files directly — they are plain markdown with YAML frontmatter and read fine as documentation.

## Notes

- All skills are in Traditional Chinese or English as originally written. Mixed-language is intentional: the author's working language is Chinese, and API documentation quotes stay in their original form.
- Hostnames, credentials and local paths have been generalised (`example.com`, `~/projects/`). Nothing here contains real keys or private infrastructure details.
- Some skills reference hardware (RTX 5080, Apple Silicon, 4070). Those are performance notes, not requirements — the techniques are portable.

## Licence

MIT — use them, fork them, ship them.

---

# Hermes Agent Skills — 公開精選集 (繁體中文)

這是一套經過實戰驗證的 [Hermes Agent](https://hermes-agent.nousresearch.com) 技能庫（Skills），提煉自 **Drizzt Studio** 實際開發與運行的 AI 系統。

這些不是玩具範例。除了下方特別標註出處的一支之外，每一支 Skill 都是在開發過程中真正撞牆後寫下的紀錄——例如被多層 `except: return []` 靜默吞掉的系統錯誤、在 720p 下發生 FP16 注意力溢位冒出綠點的影音模型、或是把真實金鑰印進 LLM 對話紀錄造成二次外洩的掃描腳本——裡面完整封裝了最終驗證通過的解法以及當時踩過的坑。

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

### 🎬 ComfyUI 與多模態影音生成工程（4 支）
- **`comfyui-api-scripting`** — 撰寫穩定無頭 ComfyUI API 腳本的規範（`POST /prompt`、`/object_info` 參數規格反查、`SaveVideo` 輸出鍵在 `images` 而非 `videos` 的陷阱，以及多組 Seed 批次測試）。
- **`ltx25-video-generation`** — Lightricks LTX-2.5 22B 影音同步生成於 16GB VRAM 的完整配置（NVFP4 Transformer + INT8 Gemma-4、duration-head 自動片長與 NAG + DualCFG 工作流）。
- **`minimax-h3-comfyui`** — MiniMax H3 24fps 影音生成完整指南（16GB/12GB 顯卡配置）：Pruned GGUF 與 safetensors 量化選型、FastH3 8-Step V2 蒸餾加速、`BlockSparseAttention` 點號展開參數防 720p FP16 溢位綠點、真實底片膚質去油光 Prompt，以及驗證下載腳本。
- **`autoip-video-api`** — AutoIP MSR 鎖臉影片生成 API 整合：多主體參考鎖臉、單人分鏡防臉崩原則，以及使用 ffmpeg `atempo` 修正配音語速過快問題。

### 📚 長篇中文小說工程（3 支）
- **`longform-novel-zh`** — 固定長度記憶卡（小說聖經 ＋ 300 字以內滾動進度摘要 ＋ 單章大綱）的長篇連載防爆 token 工作流（附 4 份標準模板）。
- **`cross-chapter-consistency`** — 多章節長篇小說的一致性審查與重構方法論（稱呼弧線、空間配置、時間軸與角色知識鏈檢查）。
- **`fiction-chapter-qc`** — 交稿前自動化品管閘門（附 `scripts/verify_chapter_qc.py`）：口頭禪頻率門檻、簡體字誤用字典掃描、跨章 8 字以上逐字重複檢測。

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
- 主機名稱、憑證與本地路徑皆已通用化（如 `example.com`、`~/projects/`），不包含任何真實金鑰或私人基礎設施細節。
- 部分技能提及特定硬體（如 RTX 5080、Apple Silicon、RTX 4070），這些是實測效能基準而非硬性需求，相關技術皆可跨平台移植。

## 授權條款

MIT License — Copyright (c) 2026 **Drizzt Studio**。歡迎自由使用、修改與發布。

---

Maintained by **Drizzt Studio**.
