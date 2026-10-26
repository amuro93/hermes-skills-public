---
name: ltx25-video-generation
description: Use when 在 ComfyUI 跑 LTX-2.5 出片（5080 原生／Sulphur workflow、duration head 自動片長）。
version: 1.0.0
author: Drizzt Studio
license: MIT
tags:
  - ltx
  - ltx-2.5
  - video-generation
  - comfyui
  - duration-head
  - 5080
metadata:
  hermes:
    tags: [ltx, ltx-2.5, video-generation, comfyui, duration-head, 5080]
    related_skills: [minimax-h3-comfyui, comfyui-server-ops]
---

# LTX-2.5 影片生成（5080 ComfyUI）

## When to Use
- 需要在 5080 ComfyUI 生成 LTX-2.5 影片，或使用 duration head 自動決定片長
- 比較 H3 與 LTX-2.5 的生成特性
- 盤點／下載 LTX-2.5 模型檔案（對照 HF `Lightricks/LTX-2.5`）

## Overview
Lightricks LTX-2.5：22B open-weights audio-video world model，影片+音訊同步生成。實測**速度明顯比 H3 快**（同機同場景），畫質優秀。定位 = 與 H3 互補（H3 動作跟隨較準、LTX 強在速度/細節/對白同步）。

## 模型檔案（16GB 顯卡實測盤點）
| HF 路徑 | ComfyUI 位置 | 必裝 |
|:--|:--|:--|
| `diffusion_models/ltx-2.5-22b-distilled-transformer-nvfp4.safetensors` | `diffusion_models/LTX-2.5\` | ✅ **主力**（16GB 卡吃這顆） |
| `text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | `text_encoders/` | ✅ INT8 版（16GB 別抓 bf16） |
| `vae/ltx-2.5-video-vae-bf16.safetensors` | `vae/LTX-2.5\` | ✅ |
| `vae/ltx-2.5-audio-vae-bf16.safetensors` | `vae/LTX-2.5\` | ✅ |
| `vae/ltx-2.5-video-vae-conv-bf16.safetensors` | `vae/LTX-2.5\` | ✅ |
| `latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors` | `latent_upscale_models/` | ✅ two-stage 用 |
| `latent_upscale_models/ltx-2.5-latent-temporal-upscaler-x2-bf16-1.0.safetensors` | `latent_upscale_models/` | 選用 |
| `loras/ltx-2.5-22b-distilled-lora-450-bf16.safetensors` | `loras/LTX-2.5\` | 選用（官方微調） |
| `model_patches/ltx-2.5-duration-head-bf16.safetensors` | **`models/model_patches/`** | duration head 用 |

不用下載的：dev-bf16/int8、distilled-bf16/int8、gemma bf16（給 48GB+ 或訓練用，16GB 裝了佔空間）。

## 兩條 workflow 路線（皆實測成功）
1. **Sulphur AllInOne（簡單）**：一顆 `LTXVSulphurAllInOne` 包兩 pass 產線。注意 `clip_1`/`clip_2` 都要填 `gemma4-with-proj`（節點無 None 選項）。
2. **原生核心節點（完整控制 + duration head）**：支援 two-stage 高畫質版與單 stage 快版，可接 duration head 自動決定片長。

## duration head 接法（自動片長）
```
ModelPatchLoader(name=ltx-2.5-duration-head-bf16) → MODEL_PATCH
LTXVDurationPredictor(model, positive, duration_head, frame_rate, min_seconds, max_seconds)
  → 輸出 num_frames (INT) → 接 EmptyLTXVLatentVideo.length + LTXVEmptyLatentAudio.frames_number
```
prompt 丟進去模型自己決定片長，不用手動設秒。

## 原生 T2V workflow 結構（核心節點版）
```
UNETLoader(nvfp4) + CLIPLoader(gemma4-int8, type=ltxv) + VAELoader×2(video+audio VAE)
→ CLIPTextEncode pos/neg → LTXVConditioning(frame_rate)
→ [LTXVDurationPredictor] → EmptyLTXVLatentVideo + LTXVEmptyLatentAudio
→ LTXVConcatAVLatent → Stage1 sampler: RandomNoise+CFGGuider(cfg=1.0)+KSamplerSelect(euler_ancestral)+ManualSigmas(9 值 8-step)+SamplerCustomAdvanced
→ LTXVSeparateAVLatent
→ (two-stage) LTXVLatentUpsampler(samples, upscale_model, vae) → LTXVConcatAVLatent(upscaled video + 原 audio latent) → Stage2 sampler(4 值 3-step)
→ LTXVSeparateAVLatent → VAEDecodeTiled(video) + LTXVAudioVAEDecode(audio)
→ CreateVideo(images, fps, audio) → SaveVideo
```

### 關鍵 sigma（官方 distilled）
- Stage1 8-step：`1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0`
- Stage2 refine 3-step：`0.85, 0.7250, 0.4219, 0.0`

## 踩坑（全實測 9/8）
1. **新版 ComfyUI `/prompt` 要包 `{"prompt": {...}}` 外層**，舊格式直接 400 `no_prompt`
2. `CreateVideo` color_space **不吃 auto** → 明確填 `sRGB`（bit_depth 可以 auto）
3. SaveVideo 輸出在 history 的 **`images` 欄位**不是 video/gifs——下載要掃三個 key
4. subgraph UI workflow（含 definitions）**不能直接餵 /prompt**（500）→ 要用核心節點手組扁平版，或展開 subgraph
5. 單獨跑 LTXVDurationPredictor 當 output node 會 `prompt_no_outputs` → 接完整鏈（有 SaveVideo 當輸出）
6. 背景跑完的收尾 KeyError：wait_download 回傳已是 hi[pid]，main 別再取一次

## 進階技法（社群 workflow video_ltx2_5_it2v_ollama_v3 移植 9/8）
1. **NAG（LTX2_NAG）**：negative attention guidance，讓 distilled（cfg=1）也能吃負面詞。掛法：model → LTX2_NAG(model, nag_cond_video=neg, nag_cond_audio=neg, nag_scale=11, nag_alpha=0.25, nag_tau=2.5, inplace=true)。社群 workflow 只掛 stage1，stage2 用 raw model
2. **LTXVDualCFGGuider**：video/audio cfg 分開（distilled 都 1.0），取代 CFGGuider。輸出 GUIDER 直接接 SamplerCustomAdvanced
3. **stage1 sigma 用 BasicScheduler(linear_quadratic, 8 steps, denoise=1)** 取代 ManualSigmas 9 值（效果相同但這是社群慣例）
4. **sampler 用 euler**（社群 workflow 不用 euler_ancestral）
5. **巨量負面詞**含 audio/video 品質項（blurry/mismatched lip sync/silent audio/off-sync 等）——NAG 吃的負面詞要完整
- ✅ **實測結論：NAG+DualCFG 版動態與畫質較自然，建議定為預設配方**（NAG + DualCFG + euler + 完整負面詞）

## Prompt 技巧
- **鎖年齡**：銀短髮+夜間燈光容易顯老 → prompt 寫死 "young woman in her early twenties, 24 years old, smooth youthful skin, no wrinkles" + 負面詞加 "old woman, wrinkles, gray hair, elderly"
- LTX 照字面畫，細節要寫死（跟 KREA2 一樣的圖文一致鐵律）

## 效能（9/8 實測）
- 單 stage + duration head：submit 到出片約 1-2 分鐘內（含 22B 載入）
- two-stage（+upscale + refine）：略久但還是明顯比 H3 快
- ⚠️ 精確秒數未計時，別瞎掰 timing

## 相關
- 官方 example workflows：`/tmp/ComfyUI-LTXVideo/example_workflows/2.5/`（subgraph 格式，當結構參考）
- HF repo：`Lightricks/LTX-2.5`（gated，要 Agree and Access）
