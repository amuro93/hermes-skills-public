# Hermes LINE Quiet-Listening & Shared-Group Session Patch
# Hermes LINE 群組靜默監聽與共享對話路由修補包

> **Bilingual Documentation / 雙語說明文件**：[繁體中文](#繁體中文說明-traditional-chinese) ｜ [English](#english-documentation)

---

## 繁體中文說明 (Traditional Chinese)

### 1. 專案來源與授權聲明 (Origin, Attribution & License)

- **上游專案來源 (Upstream Origin)**：[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
- **對應上游基準 Commit (Reviewed Base Commit)**：`4e58c721c8cf9b51c46636ea84ea6a5cb540880a`
- **授權條款 (License)**：保留上游 **MIT License** 原始版權聲明（`Copyright (c) 2025 Nous Research`，詳見隨附之 [`LICENSE`](./LICENSE) 檔案）。
- **修改整合聲明 (Modification Attribution)**：本群組靜默監聽（Quiet-Listening）、SQLite 訊息緩衝收件匣、超長歷史分頁（History Pages）與共享群組 Session 路由整合由個人創作者 **Drizzt Studio** 修改維護。
- **非官方聲明 (Non-Endorsement Disclaimer)**：本修補包並非 Nous Research 官方發布或背書之附加元件，亦不主張對整個 LINE Adapter 或上游 `hermes-agent` 框架擁有法律所有權。

### 2. 修補包性質與檔案對應表 (Source Patch Mapping)

本專案為**原始碼修補包（Standalone Source Patch Distribution）**，**並非**隨插即用（Plug-and-Play）的外掛或獨立套件。您必須先備妥已設定好 LINE Messaging API Webhook 的 `hermes-agent` 環境（建議對齊基準 commit `4e58c721c8cf9b51c46636ea84ea6a5cb540880a`），並手動備份與替換對應檔案。

資料夾內的 `adapter_minimal.py`、`session_candidate.py`、`ingress_context_candidate.py` 為測試框架（Test Harness）使用的候選別名（aliases），實際部署至 `hermes-agent` 時的**5 個原始碼檔案 + 1 個新增策略模組**對應路徑如下：

| 發佈包檔案名稱 (Release File) | 部署目標路徑 (`hermes-agent` Target Path) | 角色說明 (Role) |
| :--- | :--- | :--- |
| `line_group_policy.py` | `gateway/line_group_policy.py` | **新增共用輔助模組**：唯一負責解析 `LINE_LISTENER_GROUP_IDS` 與驗證共享群組資格 |
| `adapter_minimal.py` | `plugins/platforms/line/adapter.py` | **修改版 LINE Adapter**：整合指定群組靜默緩衝、真實 `@` 提及喚醒、分頁提示與 Delivery Ledger Ack |
| `group_inbox.py` | `plugins/platforms/line/group_inbox.py` | **群組收件匣模組**：SQLite WAL 訊息緩衝、`@` 提及純函數判定、單調遞增 Ack 與保留期清理 |
| `history_pages.py` | `plugins/platforms/line/history_pages.py` | **歷史分頁模組**：超過 24,000 字元時將未讀歷史轉為本機唯讀分頁檔與清單（Manifest） |
| `session_candidate.py` | `gateway/session.py` | **修改版 Session 路由**：針對已設定且具本地信任旗標之 LINE 群組啟用多人共享 Session Key |
| `ingress_context_candidate.py` | `gateway/session_ingress_context.py` | **修改版 Ingress Provenance**：於驗證 Provenance 通過後呼叫 Adapter 的 `restore_native_source_context` |

> **備註**：`envelope_reference.py` 為對應 `gateway/session_envelope.py` 的唯讀參考副本，僅供本機執行 `test_native_line_admission.py` 測試驗證使用，部署時無須修改上游的 `gateway/session_envelope.py`。

### 3. 環境變數設定與 Fail-Closed 安全機制 (`LINE_LISTENER_GROUP_IDS`)

本發佈版已移除所有硬編碼群組 ID，改由單一環境變數 `LINE_LISTENER_GROUP_IDS` 控制：

```ini
# 單一群組範例（必須為 C 開頭加上 32 位小寫十六進位字元）：
LINE_LISTENER_GROUP_IDS=Caaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

# 多群組範例（以逗號分隔，每個項目皆須符合 ^C[0-9a-f]{32}$）：
LINE_LISTENER_GROUP_IDS=Caaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,Cbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
```

- **預設關閉（Default Empty = Disabled）**：若未設定 `LINE_LISTENER_GROUP_IDS` 或值為空字串，靜默監聽與多人共享群組路由對**所有群組一律停用**。
- **格式嚴格驗證與 Fail-Closed**：每個以逗號分隔的群組 ID 必須嚴格符合正規表示式 `^C[0-9a-f]{32}$`（`C` 加上 32 位小寫十六進位字元）。只要其中**任何一個項目格式錯誤**（例如含大寫字母、長度不符、尾隨逗號或空項目），系統將採取 **Fail-Closed 拒絕整組設定值**，不啟用任何群組的監聽或共享路由。
- **與 `LINE_ALLOWED_GROUPS` 明確分離**：`LINE_ALLOWED_GROUPS` 是 LINE Adapter 原本的入站白名單（決定機器人是否接受該群組的 Webhook 事件），**不會**隱式啟用靜默監聽或共享 Session。目標群組必須同時獲准通過 Adapter 白名單（`LINE_ALLOWED_GROUPS` 或開發模式 `LINE_ALLOW_ALL_USERS`）**且**明確列於 `LINE_LISTENER_GROUP_IDS`。
- **Per-Profile 執行期作用域與重啟要求**：此環境變數屬於各 Gateway Profile 的執行期範圍（Runtime Scope）。修改 `.env` 或環境變數後，**必須重新啟動 Gateway 服務**方能完整生效。

### 4. 手動安裝步驟 (Manual Installation Steps)

1. **確認前置環境**：確認您的 `hermes-agent` 已完成基礎 LINE Messaging API Channel 設定（`LINE_CHANNEL_ACCESS_TOKEN`、`LINE_CHANNEL_SECRET` 與 HTTPS Webhook；本發佈包不含任何憑證）。
2. **備份原始檔案**：
   - 備份 `plugins/platforms/line/adapter.py`
   - 備份 `gateway/session.py`
   - 備份 `gateway/session_ingress_context.py`
3. **複製修補檔案**：依上方對應表將 6 個 `.py` 檔案複製至 `hermes-agent` 對應目錄。
4. **設定環境變數**：於對應 Profile 的 `.env` 中設定 `LINE_ALLOWED_GROUPS` 與 `LINE_LISTENER_GROUP_IDS`。
5. **重啟服務**：重新啟動 `hermes-agent` Gateway 服務。

### 5. 測試基準與驗證誠實揭露 (Testing & Validation Status)

- **私有版本驗證基準**：本功能之私有前身版本（採用單一固定群組 ID）已通過 **105 項本機自動化測試**，並於**單一擁有者實際 LINE 群組**完成端到端實測驗證。
- **公開泛化版本聲明**：本公開發佈版將群組判定泛化為 `LINE_LISTENER_GROUP_IDS` 環境變數設定，並透過純合成測試資料（Synthetic Fixtures，如 `C` + 32 個 `a`）驗證失敗關閉（Fail-Closed）與多群組隔離邏輯；惟**此泛化後之公開版本在部署者另行於實際環境測試前，尚未經過獨立的正式環境（Production）實群組壓測**。

### 6. 已知限制 (Known Limitations)

1. **靜默期間媒體僅記錄文字佔位符（No Quiet Media Download）**：當群組訊息未提及（`@`）機器人時，圖片、影片、音訊、檔案、貼圖與位置訊息僅會在 SQLite 收件匣記錄文字佔位符（例如 `[image]`、`[sticker]`），**不會**在靜默期間向 LINE 伺服器下載媒體二進位檔案。
2. **超長歷史分頁採保守不自動 Ack 且無完整讀取證明（Conservative No-Ack on Paged Turns）**：當未讀累積訊息超過單輪內嵌上限（24,000 字元）並轉為本機分頁檔（`history_pages.py`）時，為避免模型未讀完所有分頁即誤消歷史，系統於回覆完成後**不會自動 Ack 標記已讀**，亦無法在協定層強制證明模型已透過 `read_file` 讀完每一頁。
3. **發言者標記使用原始 LINE `userId`**：緩衝歷史記錄中的發言者標頭格式為 `[YYYY-MM-DD HH:MM:SS UTC] [U...]`，直接使用 LINE `userId`，不會在背景額外呼叫 LINE Profile API 解析暱稱。
4. **需既有 LINE Adapter 環境**：本修補包不包含任何 API 金鑰、Webhook 穿隧工具或部署腳本。

---

## English Documentation

### 1. Origin, Attribution & License

- **Upstream Repository**: [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
- **Reviewed Upstream Base Commit**: `4e58c721c8cf9b51c46636ea84ea6a5cb540880a`
- **License**: Released under the **MIT License**, preserving the original upstream copyright notice (`Copyright (c) 2025 Nous Research`; see [`LICENSE`](./LICENSE)).
- **Modified Integration Attribution**: LINE group quiet-listening inbox buffering, paged transcript materialization, and shared multi-user group session routing integration created and modified by **Drizzt Studio** (personal creator).
- **Non-Endorsement & Ownership Disclaimer**: This distribution is an independent community source patch, not an official Nous Research product or endorsement, and makes no legal ownership claim over the upstream `hermes-agent` framework or the full LINE adapter.

### 2. Source Patch Distribution & File Mapping

This repository is a **manual source patch distribution**, **not** a plug-and-play plugin or standalone package. It requires an existing `hermes-agent` checkout (aligned with upstream commit `4e58c721c8cf9b51c46636ea84ea6a5cb540880a`) where the LINE Messaging API adapter is already configured.

In this folder, `adapter_minimal.py`, `session_candidate.py`, and `ingress_context_candidate.py` are test-harness filenames. When applying the patch to `hermes-agent`, map the **five original patched/companion files plus the new policy helper** as follows:

| Release File | Target Path in `hermes-agent` | Description |
| :--- | :--- | :--- |
| `line_group_policy.py` | `gateway/line_group_policy.py` | **New canonical policy helper**: parses `LINE_LISTENER_GROUP_IDS` fail-closed and validates shared-group routing eligibility |
| `adapter_minimal.py` | `plugins/platforms/line/adapter.py` | **Patched LINE adapter**: quiet SQLite buffering on configured groups, `@` mention wake gate, paged transcript prompts, and delivery-ledger acks |
| `group_inbox.py` | `plugins/platforms/line/group_inbox.py` | **Group inbox module**: SQLite WAL storage, pure mention predicate (`is_bot_mentioned`), monotonic ack boundaries, and retention cleanup |
| `history_pages.py` | `plugins/platforms/line/history_pages.py` | **History pagination module**: materializes >24,000-char backlogs into bounded local read-only page files and a JSON manifest |
| `session_candidate.py` | `gateway/session.py` | **Patched session router**: routes participants in configured LINE listener groups (with process-local `shared_group=True`) to a shared session key |
| `ingress_context_candidate.py` | `gateway/session_ingress_context.py` | **Patched ingress provenance**: invokes the adapter's `restore_native_source_context` hook only after provenance validation succeeds |

> **Note**: `envelope_reference.py` is included as a read-only reference copy of `gateway/session_envelope.py` from commit `4e58c721c8cf9b51c46636ea84ea6a5cb540880a` so the standalone native admission test suite (`test_native_line_admission.py`) can run in isolation.

### 3. Configuration (`LINE_LISTENER_GROUP_IDS`) & Fail-Closed Semantics

All group IDs are configured exclusively via the `LINE_LISTENER_GROUP_IDS` environment variable:

```ini
# Single group (must be exact 'C' + 32 lowercase hex characters):
LINE_LISTENER_GROUP_IDS=Caaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

# Multiple groups (comma-separated, each matching ^C[0-9a-f]{32}$):
LINE_LISTENER_GROUP_IDS=Caaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,Cbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
```

- **Default Empty Disables All Groups**: When `LINE_LISTENER_GROUP_IDS` is unset, empty, or whitespace-only, quiet listening and shared-group session routing are **disabled for every group**.
- **Strict Validation & Fail-Closed Rejection**: Every comma-separated entry must match `^C[0-9a-f]{32}$` (`C` followed by 32 lowercase hexadecimal characters). If **any entry is malformed** (e.g., uppercase hex, wrong prefix, wrong length, trailing comma, or empty item), the parser **fails closed by rejecting the entire value**, enabling zero groups.
- **Distinct from `LINE_ALLOWED_GROUPS`**: `LINE_ALLOWED_GROUPS` controls standard LINE webhook source authorization and is **never** used as an implicit fallback for `LINE_LISTENER_GROUP_IDS`. A target group must be allowed by `LINE_ALLOWED_GROUPS` (or dev-only `LINE_ALLOW_ALL_USERS`) **and** explicitly listed in `LINE_LISTENER_GROUP_IDS`.
- **Per-Profile Runtime Scope**: Environment variables are scoped per gateway profile runtime. **Restart the gateway service** after modifying `.env` or environment variables.

### 4. Manual Installation Steps

1. **Prerequisites**: Ensure `hermes-agent` is installed and your LINE Messaging API channel (`LINE_CHANNEL_ACCESS_TOKEN`, `LINE_CHANNEL_SECRET`, public HTTPS webhook) is working. No credentials are bundled with this patch.
2. **Back Up Existing Files**:
   - Back up `plugins/platforms/line/adapter.py`
   - Back up `gateway/session.py`
   - Back up `gateway/session_ingress_context.py`
3. **Apply Patch Files**: Copy the 6 source files into their mapped `hermes-agent` paths listed in the table above.
4. **Configure Environment**: Set `LINE_ALLOWED_GROUPS` and `LINE_LISTENER_GROUP_IDS` in your gateway profile's `.env`.
5. **Restart Gateway**: Restart the `hermes-agent` gateway process.

### 5. Baseline Testing & Validation Status

- **Private Version Baseline**: The private pre-release implementation (using a single hardcoded group ID) passed **105 local automated tests** and was confirmed live in **one owner LINE group**.
- **Generalized Release Status**: This generalized public release replaces hardcoded group checks with `LINE_LISTENER_GROUP_IDS` and is verified against the local test suite using purely synthetic fixtures (`C` + 32 `'a'`s, synthetic user IDs). **The generalized configuration path has not been production-tested in live LINE traffic and should be validated in your own test group before production use.**

### 6. Known Limitations

1. **Media Placeholders Only (No Quiet Media Download)**: Non-mentioned media events (`image`, `video`, `audio`, `file`, `sticker`, `location`) are buffered as text placeholders (e.g., `[image]`, `[sticker]`) without downloading media bytes from LINE during quiet listening.
2. **Conservative No-Ack & No Full-Read Proof on Paged Backlogs**: When buffered history exceeds 24,000 characters and is materialized into paged files (`history_pages.py`), the adapter intentionally leaves the SQLite backlog **unacknowledged** after turn delivery and does not mechanically prove that the LLM read every page via `read_file`.
3. **Raw LINE `userId` Speaker Labels**: Buffered transcripts attribute messages using raw LINE `userId`s (`[U...]`) rather than display names.
4. **Requires Existing LINE Setup**: Requires an existing `hermes-agent` environment and LINE channel setup; no credentials or deployment scripts are included.

### 7. Running the Standalone Test Suite

From an activated `hermes-agent` Python environment with `requirements-test.txt` installed:

```bash
pytest test_group_inbox.py test_history_pages.py test_shared_session.py test_line_listener.py test_native_line_admission.py
```
