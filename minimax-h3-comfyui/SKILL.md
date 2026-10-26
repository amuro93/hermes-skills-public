---
name: minimax-h3-comfyui
description: Use when 跑 MiniMax H3 影片生成：量化選型、ComfyUI 工作流。
version: 1.0.0
author: Drizzt Studio
license: MIT
---

# MiniMax H3 本地影片生成 (ComfyUI)

MiniMax H3 全模態生成: 影片 + 原生 32kHz 立體聲, 24FPS, 768p 基礎(可 2K), 4-15 秒, 11 種語言(含中文)。開源授權 `minimax-h3-community-license-agreement` — 商用要翻條款。

## 架構三件套 (VRAM 瓶頸分析)
1. **Transformer**: FL2VA(文生/首尾幀插值) + Ref2VA(全參考模式, 最多 9 圖/3 影片/3 音訊)
2. **文字編碼器: Qwen3-VL-32B** — 超肥, 低 VRAM 的生死關鍵
3. **Video VAE 5.21G fp16** + **Audio VAE 0.61G fp32**

## VRAM 對照 (Abiray pruned GGUF 官方建議, 2026-08 實測可用)
| 量化 | 大小 | 目標卡 |
|---|---|---|
| Q3_K_M | 8.9G | ~12GB (4070) |
| Q4_K_M | 11.6G | **16GB (5080) ← 最佳平衡** |
| Q5_K_M | 14.1G | 24GB |
| Q6_K / Q8_0 | 16.7G / 21.6G | 24GB+ |
完整(非 pruned)版 Q4_K_M 19.9G — 16GB 卡不用想。

## 5080 (16GB) 配置
- `models/unet/`: `MiniMax-H3-FL2VA-Pruned-Q4_K_M.gguf` (+ `Ref2VA` 同款, 圖生影片選配)
- `models/text_encoders/`: `qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf` (14.58G, realrebelai) — ComfyUI 編碼完會 offload, 峰值扛得住
- `models/vae/`: `minimax_h3_video_vae_fp16` + `minimax_h3_audio_vae_fp32` (Comfy-Org repo)
- `models/loras/`: `minimax_h3_turbo_v4_step600_ema.safetensors` (加速選配)

## 4070 (12GB) 配置
- Transformer 換 `Q3_K_M` (8.9G), **TE 必須換 Q2_K (8.49G)** — Q4 TE 14.58G 一定爆
- 兩個 8-9G 檔輪流 offload, 出片慢但跑得動

## 前置需求
- **ComfyUI v0.30.0+** (原生支援 H3 架構)
- **ComfyUI-GGUF 節點** (city96) — GGUF 用 `UnetLoaderGGUF` 載, 放 unet/ 目錄
- **ComfyUI-MiniMax-H3-Turbo** (Larryvrh) — 用 Turbo LoRA 才需要
- int8_convrot 系列要 **PyTorch cu130**; nvfp4 TE 不要求 Blackwell

## 工作流
- 官方模板: `github.com/Comfy-Org/workflow_templates` → `video_minimax_h3_t2v.json` / `i2v.json` / `r2v.json`
- ⚠️ **官方模板預設載 int8_convrot/nvfp4 大檔** → 拿到後把載入節點改成 `UnetLoaderGGUF` 吃 .gguf, 其他不動
- realrebelai repo 內附 `FL2V_(WORKFLOW).json` / `REF2V_(WORKFLOW).json`
- larryvrh 內附 `minimax_h3_t2v_turbo.json`

## Turbo LoRA (20 步 → 4-8 步, 快 ~5 倍)
- 最佳 checkpoint: `minimax_h3_turbo_v4_step600_ema.safetensors` (0.78G)
- 4 步是下限, **6-8 步最佳**; strength 保持 1.0; scheduler: `simple`
- 4 步 + 快速大動作會 motion-smear → 用 6-8 步; 過銳化 → strength 降到 0.8-0.95
- ⚠️ Turbo LoRA 用**完整模型**訓練, pruned 架構相容性未驗證, 上之前要測
- lightx2v 蒸餾版: 4 步, strength 0.75, er_sde/sa_solver (Kijai 有轉 comfy safetensors)

## 伺服器端實作（safetensors 量化版）

實測採用 **safetensors 量化版**（非 GGUF），RTX 5080 (16GB) 出片穩定。

### 伺服器實際檔案配置
| 用途 | 檔名（含目錄） |
|:---|:---|
| Transformer (FL2VA) | `MiniMax H3\minimaxH3INT8INT4_fl2vaINT4BQPruned.safetensors`（15.16GB，INT8/INT4 混合 pruned） |
| 文字編碼器 | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`（CLIPLoader type=`minimax`） |
| 影片 VAE | `minimax_h3_video_vae_fp16.safetensors` |
| 音訊 VAE | `minimax_h3_audio_vae_fp32.safetensors` |

若僅部署 **fl2va**，多圖參考模式（ref2va）需另抓 `minimax_h3_ref2va_pruned_int8_convrot.safetensors`。

### API Workflow 節點鏈（POST /prompt 直接出片）
```
UNETLoader → BasicGuider(model)
CLIPLoader(type=minimax) → MiniMaxH3ReferenceToVideo(clip)
VAELoader(video) → MiniMaxH3ReferenceToVideo(vae) + VAEDecode
VAELoader(audio) → MiniMaxH3ReferenceToVideo(audio_vae) + VAEDecodeAudio
LoadImage → MiniMaxH3ReferenceToVideo(ref_images.ref_image_0)
MiniMaxH3ReferenceToVideo → BasicGuider(conditioning) + SamplerCustomAdvanced(latent_image)
RandomNoise / KSamplerSelect(res_multistep) / BasicScheduler(simple,20步) → SamplerCustomAdvanced
SamplerCustomAdvanced → VAEDecode + VAEDecodeAudio → CreateVideo(fps=24) → SaveVideo
```

### 實作踩坑（全部實測）
- **SaveVideo 必給 `format:"mp4"` + `codec:"auto"`**——缺 codec：採樣跑完 200 秒後卡 `SaveVideo.execute() missing codec`；缺 format：validation 400（新版 ComfyUI 0.31.1 也接受 `format:"auto"`）
- **⚠️ GUI 工作流 LoadImage 被 mute（mode=4）= 參考圖沒連！** API prompt 的 `ref_images` 變 null → 文生影片假裝圖生。正解：API 扁平格式只留要用的 LoadImage
- **ref_images 是 optional dict**：`{"ref_image_0": ["<node>", 0]}`，最多 ref_image_0~8；多圖必須同一人（混不同人的臉 = 混血飄掉）
- **length**：17 幀/塊網格，5 秒=124，10 秒~243
- **解析度**：32 倍數；9:16 0.4MP=480×864；短邊上限 768
- **中文 prompt 實測可用**（Qwen3-VL 中文最強）；對白寫中文生成中文語音；多圖參考用 `<Picture N>` 標記（連接順序），描述可中文；不用的 LoadImage 要 mute 不然作者原圖混入
- **參考圖上傳**：`curl -F "image=@圖" -F "overwrite=true" https://comfyui.example.com/upload/image`
- **SageAttention 缺失**：mute `PathchSageAttentionKJ`（Ctrl+M）即可跑，H3 原生不需它
- **Spectrum 節點**：`xmarre/ComfyUI-Spectrum-MiniMax-H3`（git clone 到 custom_nodes，無第三方依賴）；bootstrap_first_forecast 需 degree=1 + warmup_steps≤1 才啟用

### 實測數據（RTX 5080，INT8INT4 15.16GB 動態載入）
- 0.4MP 5 秒：約 3 分鐘（20 步）；0.2MP 更快
- 0.4MP 9:16 10 秒（~243 幀，Spectrum 加速）：約 5 分鐘
- CPU 95% 觸發 memory management 是正常的（搬模型）
- **雙人場景實測容易崩壞 → 建議拆為單人分鏡**

## FastH3 8-Step V2 蒸餾加速與高解析度修正（2026-09 實測）
- **FastH3 V2（DMD2 蒸餾版）**：8 步（`sigmas: 1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.9, 0.725, 0.421875, 0.0`）、**單一路徑 CFG=1**（`BasicGuider`，速度與畫質兼顧）。
- **BlockSparseAttention API 語法陷阱**：`MiniMaxH3BlockSparseAttention` 節點的 `attention_mode` 選擇 `block_sparse_attn` 時，**必須使用點號展開子參數**（`attention_mode.attention_mode`、`attention_mode.block_size: 64`、`attention_mode.topk: 32`），否則 ComfyUI 預設載入 `flash_attn` 會在 720p（1280×720）發生 FP16 attention 溢位，畫面出現大量螢光綠點／紅藍光斑。
- **人臉與膚質自然感 Prompt 守則**：
  - 避免寫 `glowing skin`、`dewy skin`、`8k masterpiece`（會將高光推向純白造成塑膠蠟像油臉）。
  - 改用底片消光與真實毛孔詞彙：`matte natural skin texture, visible fine pores, subtle subsurface scattering, soft diffused lighting, Kodak Portra 400 film grain`。

## 兩套裝法：16GB 先跟哪一套（先讀這段再往下）

本文同時寫了**兩套可用的權重配置**，別混著裝：

1. **GGUF 系列（`UnetLoaderGGUF` 載入）** —— 對應 `templates/download_minimax_h3.sh`，一條命令把該有的檔抓齊。
   👉 **16GB 卡第一次裝、只想快點跑起來：跟這套。**
2. **safetensors 量化系列（`UNETLoader` 載入）** —— 伺服器實測用的另一種裝法，檔名、載入節點、需要的 patch 都不同。
   👉 只有在你已經有一台跑著 safetensors 的機器、或要沿用別人的 workflow JSON 時才走這套。

⚠️ 兩套的**載入節點不同**（GGUF 走 `UnetLoaderGGUF`、safetensors 走 `UNETLoader`），拿 A 的 workflow 配 B 的權重一定載不到。

## 下載與驗證習慣
- **直接提供 HuggingFace resolve URL**，完整網址清單見 `references/minimax-h3-repos.md`
- 下載腳本備用: `templates/download_minimax_h3.sh` (預設 Q4 / `--q3` 4070 / `--turbo` 三模式, 斷點續傳 + 大小檢查)
- 所有 URL 交付前用 `curl -sIL -o /dev/null -w "%{http_code}"` 驗證 200

## 研究/驗證方法 (web_search 掛掉時)
HF API 直接撈, 不用 Firecrawl:
- 搜尋: `https://huggingface.co/api/models?search=minimax+h3`
- 檔案+大小: `https://huggingface.co/api/models/{repo}/tree/main?recursive=true`
- README: `https://huggingface.co/{repo}/raw/main/README.md`
- 直下: `https://huggingface.co/{repo}/resolve/main/{path}`
- Workflow JSON 引用檔名: 抓 raw JSON 後 regex `\.gguf|\.safetensors`
