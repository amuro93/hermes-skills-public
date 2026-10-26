---
name: mac-mlx-ollama-deployment
description: Use when 在 Apple Silicon Mac 部署 LLM。Ollama MLX 引擎、自訂 safetensors 模型匯入。
version: 1.0.0
author: Drizzt Studio
license: MIT
---

# Mac (Apple Silicon) LLM 伺服器部署 — Ollama + MLX

## 適用場景
- 地端 LLM 伺服器（Apple Silicon M3 Max 64GB 等）取代雲端 API 供本地 Agent 呼叫
- 需要匯入 HuggingFace 上的 MLX 格式模型（含 abliterated / fine-tuned safetensors 權重）

## 關鍵環境事實（M3 Max 64GB 實證）
- **Ollama 0.19+ 在 Apple Silicon 內建 MLX 引擎**（decode 比舊版 llama.cpp 快 ~2 倍，官方 benchmark：M5 Max 35B MoE 58→112 tok/s）
- **GGUF 模型在 Mac 上走 llama.cpp Metal 路徑，吃不到 MLX 加速**——27B GGUF 實測僅 6.2 tok/s
- **MLX 格式模型才有 MLX 加速**（實測 4K context: prefill 641.7 / gen 33.2 tok/s）
- 匯入 MLX safetensors 到 Ollama 必須加 **`--experimental` 旗標**，否則報 `Error: unknown data type: U32`
- 首次使用 python3 會觸發 xcode-select 安裝 CLT（~2GB，必裝）；huggingface_hub 用 `python3 -m pip install --user` 裝

## 工作流程

### 1. 安裝
```bash
# Ollama（curl 一鍵裝，或官網 .dmg）
curl -fsSL https://ollama.com/install.sh | sh
# 驗證版本（0.19+ 才有 MLX）
ollama --version
# Xcode CLT（首次 python3 會自動要求；也可手動）
xcode-select --install
# HF 下載工具
python3 -m pip install --user -U "huggingface_hub[cli]"
```

### 2. 格式比較（以 Qwen3.8-27B 為例）
| 來源 | 格式 | Mac 速度 | 備註 |
|---|---|---|---|
| **orcarouter/Qwen3.8-27B-Uncensored-MLX** | MLX 2/4/6/8-bit | 快（MLX） | **推薦**：保留 tool calling/thinking 控制；6-bit 22.8GB 品質/速度平衡 |
| PocketAiHub/Qwen3.8-27B-Abliterated-MLX | MLX 4bit 15GB | 33 tok/s | 速度穩定，但 tool calling 支援需視版本測試 |
| 傳統 GGUF 27B | GGUF | 6.2 tok/s 慢 | 只適合 NVIDIA CUDA，Mac 上不建議使用 |

### 3. 下載（注意資料夾名有連字號！）
```python
# orcarouter 結構：2-bit/ 4-bit/ 6-bit/ 8-bit/（連字號！不是 6bit）
python3 -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='orcarouter/Qwen3.8-27B-Uncensored-MLX', allow_patterns='6-bit/*', local_dir='~/models/qwen3.8-mlx-6bit')"
```
- 6-bit = 5 個 safetensors + config 等，共 ~22.8GB
- allow_patterns 打錯資料夾名會「Fetching 0 files」靜默失敗——用 HF API tree 先確認結構

### 4. 匯入 Ollama（關鍵：--experimental）
```bash
echo "FROM ~/models/qwen3.8-mlx-6bit/6-bit" > ~/Modelfile
ollama create --experimental qwen3.8-27b-mlx -f ~/Modelfile
# 成功訊息：successfully imported ... with 1192 layers
```

### 5. 測速（不靠體感，用 API 數據）
```bash
curl http://localhost:11434/api/chat -d '{"model":"qwen3.8-27b-mlx","messages":[{"role":"user","content":"用一句話介紹台灣"}],"stream":false}'
# 找 eval_count / eval_duration（奈秒）：tok/s = eval_count / (eval_duration/1e9)
```

## 🔴 踩坑
- `ollama run` 互動模式輸入 `/bye` 離開、`/?` 看指令
- thinking 模型（Qwen3 系）會先輸出 Thinking tokens——回應時間包含 thinking；接 Agent 時可評估關閉 thinking（`enable_thinking: false` 或 API 參數）加速
- 風扇在推理時高速運轉 = 正常，模型閒置後降速
- Mac 上 `ollama ps` 確認模型載入；KEEP_ALIVE 設 -1 常駐：`launchctl setenv OLLAMA_KEEP_ALIVE -1`（或 ~/.zshrc export）後重啟 Ollama
- 模型放 `~/models/`，HF 下載的 MLX 版可直接 `ollama create --experimental` 匯入，不需手動轉檔
- git-bash（Windows 端）curl 送中文會壞碼——測遠端 API 時用 `--data-binary @file`；Mac 終端機原生 UTF-8 無此問題

## 遠端存取與 Cloudflare Tunnel 配置
- 🔴 **Cloudflare Tunnel 403 的常見根因之一**：Ollama 防 DNS rebinding 的 **Host header 檢查**（Host 非 localhost → 403 空 body），**不是** Access/Bot/WAF。解法＝`config.yml` ingress 加 `originRequest: httpHostHeader: "localhost:11434"`（欄位名 **httpHostHeader**）→ `cloudflared tunnel ingress validate` → 重啟 tunnel
  - ⚠️ **但 403 不是只有這一種原因**，別看到 403 就改 Host header。先做三步檢查再動設定：① `curl -sS -o /dev/null -w '%{http_code}' https://ollama.example.com/api/tags`（不加任何 header）② 直接打區網 `http://<host>:11434/api/tags` 是否 200 ③ 換一個**不存在的** Host header 重打，比較三者的回應 body 長度（Access/WAF 的 403 會帶 HTML，Ollama 的 Host 檢查是**空 body**）
  - 🔴 **驗收要有「反向測試」**：暫時把 tunnel 關掉、或從外部打一個未經 tunnel 的位址，確認**連不到**（不然你只證明「打得通」，沒證明「沒被別人打通」）。若服務真的對外開放，請一併確認 auth 與 rate limit。
- ✅ **Agent 接法**：model 指向 OpenAI 相容端點 **`https://ollama.example.com/v1`**（Hermes 的 openai-compatible provider 設 `base_url` 即可）
