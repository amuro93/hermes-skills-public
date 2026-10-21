# MiniMax H3 — 完整 repo 地圖與已驗證下載網址

> 2026-08 實測: 所有 resolve URL 皆 `curl -sIL` 回 200。大小為 HF tree API 抓取。

## 已驗證下載網址

### 16GB VRAM 主力 (Q4_K_M)
- 文生 Transformer (11.56G): https://huggingface.co/Abiray/MiniMax-H3-Pruned-GGUF/resolve/main/MiniMax-H3-FL2VA-Pruned-Q4_K_M.gguf
- 圖生 Transformer (11.56G): https://huggingface.co/Abiray/MiniMax-H3-Pruned-GGUF/resolve/main/MiniMax-H3-Ref2VA-Pruned-Q4_K_M.gguf
- TE Q4_K_M (14.58G): https://huggingface.co/realrebelai/MiniMax-H3_GGUFs/resolve/main/qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf

### 4070 用 (Q3 極限)
- 文生 Transformer (8.9G): https://huggingface.co/Abiray/MiniMax-H3-Pruned-GGUF/resolve/main/MiniMax-H3-FL2VA-Pruned-Q3_K_M.gguf
- 圖生 Transformer (8.9G): https://huggingface.co/Abiray/MiniMax-H3-Pruned-GGUF/resolve/main/MiniMax-H3-Ref2VA-Pruned-Q3_K_M.gguf
- TE Q2_K (8.49G): https://huggingface.co/realrebelai/MiniMax-H3_GGUFs/resolve/main/qwen3vl-32B-MiniMax-H3-Q2_K.gguf

### VAE (兩台共用)
- 影片 VAE (5.21G): https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_fp16.safetensors
- 音訊 VAE (0.61G): https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors

### Turbo LoRA (選配)
- v4 step600 EMA (0.78G): https://huggingface.co/larryvrh/MiniMax-H3-Turbo-Lora/resolve/main/minimax_h3_turbo_v4_step600_ema.safetensors
- Turbo t2v workflow: https://huggingface.co/larryvrh/MiniMax-H3-Turbo-Lora/resolve/main/minimax_h3_t2v_turbo.json
- 其他 checkpoint: `minimax_h3_turbo_4step_ema.safetensors` (v1-850, 4步重動作較友好), `minimax_h3_turbo_v4_step600.safetensors` (非 EMA)
- ⚠️ 別抓 `experimental_*.bin` (10.9G each, 訓練殘渣)

### 工作流
- 官方模板: https://github.com/Comfy-Org/workflow_templates (video_minimax_h3_t2v.json / i2v.json / r2v.json)
- realrebelai 內附: https://huggingface.co/realrebelai/MiniMax-H3_GGUFs/tree/main → FL2V_(WORKFLOW).json / REF2V_(WORKFLOW).json

## Repo 地圖 (誰是幹嘛的)
| Repo | 內容 | 註記 |
|---|---|---|
| MiniMaxAI/MiniMax-H3 | 官方原始 (498G, bf16 13-split) | 不用抓 |
| Comfy-Org/MiniMax-H3 | ComfyUI 重打包 + **VAE** + 官方 workflow | VAE 從這抓; bf16 66G / pruned int8_convrot 20.97G / fp8_scaled 20.96G; TE nvfp4_awq 27.14G |
| Abiray/MiniMax-H3-Pruned-GGUF | **pruned GGUF 量化階梯** (Q3 8.9G → Q8 21.58G) | 5080/4070 主力來源 |
| realrebelai/MiniMax-H3_GGUFs | 完整版 GGUF (Q3 15.6G → Q8 36G) + **TE GGUF (Q2 8.49G / Q4 14.58G)** | TE 唯一 GGUF 來源 |
| Abiray/MiniMax-H3-nvfp4-INT4-INT8-Convrot | pruned_nvfp4 12.53G, pruned_mixed_int4_int8 15.9G, TE nvfp4_awq 15.69G, int4_convrot 14.95G, VAE | nvfp4 TE 不要求 Blackwell; int8_convrot 要 cu130 |
| larryvrh/MiniMax-H3-Turbo-Lora | Turbo LoRA (v4_step600_ema 最佳) + turbo workflow | 需 ComfyUI-MiniMax-H3-Turbo 節點 |
| lightx2v/Minimax-h3-Turbo | 蒸餾版 diffusers (4步) | 源碼 ModelTC/Minimax-H3-Turbo |
| Kijai/MiniMax-H3_comfy | lightx2v LoRA 轉 comfy (1.96G full / 0.31G resized) + experimental | Kijai wrapper |
| unsloth/MiniMax-H3-GGUF | pruned GGUF 另版 (Q4_K 11.4G, Q8 21.4G), TE Q4_K_M 18.2G | 備援 |
| sakamakismile/Qwen3-VL-32B-Heretic-MiniMax-H3-NVFP4 | Heretic CLIP 相關 NVFP4 TE | 與我們 Heretic CLIP 環境相關, 待查 |

## HF API 研究模式 (web_search 掛掉時的完整流程)
```bash
# 1. 搜尋模型
curl -s "https://huggingface.co/api/models?search=minimax+h3&limit=30"

# 2. 撈檔案樹+大小 (用 python 解析, 濾 >100MB)
curl -s "https://huggingface.co/api/models/{repo}/tree/main?recursive=true"

# 3. README (官方 VRAM 建議都在這)
curl -s "https://huggingface.co/{repo}/raw/main/README.md"

# 4. Workflow JSON 引用哪些檔名
curl -s <raw workflow url> | grep -oE '[A-Za-z0-9_\-\./]+\.(gguf|safetensors)' | sort -u

# 5. 交付前驗證每個下載 URL
curl -sIL -o /dev/null -w "%{http_code}\n" <resolve url>   # 200 = 存在
```
注意: 執行環境的 web_search 走 Firecrawl (`hermes config set web.provider firecrawl + api_key`); 沒設定時直接改用 HF API, 不要卡在 web_search。

## 踩過的坑
- 官方 workflow 模板引用 int8_convrot/nvfp4 大檔 (要 cu130 / 27G TE), 換 GGUF 方案後要改 UnetLoaderGGUF 節點
- pruned 是 channel pruning — Turbo LoRA / 一般 LoRA 相容性未保證, 品質要實測
- realrebelai workflow 裡寫的檔名有 `-fixed` 後綴 (過時), 實際檔案無後綴
- 16GB 卡 TE 峰值瞬間 14.58G + transformer 11.56G 需要 ComfyUI smart offload; 4070 兩個 8-9G 檔輪流 offload 會喘
