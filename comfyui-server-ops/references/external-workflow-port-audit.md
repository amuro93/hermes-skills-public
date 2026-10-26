# 外來 workflow 落地盤點 — 實戰案例集

用法：拿到別人（RunningHub／discord／群里／使用者 轉發）的 workflow JSON 時，照 `SKILL.md` 的
「外來的 workflow 能不能跑？」一節跑一遍，然後把結果照本檔的格式記錄下來。

---

## 案例 1（2026-09-22）：兩支 MiniMax H3「唱歌數字人 MV」workflow

來源：使用者 直轉 .json（API 格式，可直接 `POST /prompt`）。
本機實況：5080 ComfyUI **0.34.6**／torch **2.10.0+cu130**／RTX 5080 17.1GB／`/object_info` 共 **3249** 個節點。

### WF1「H3导演台唱歌数字人版」

- 形狀：`MiniMaxH3Director` 一次拉 6 段、每段 362 幀（15s、24fps）＝**總 2172 幀 ≈ 90.5s**；
  每段一個 `MiniMaxH3DirectorGroupReferenceToVideo`，各自 `TrimAudioDuration` 從同一首歌切不同區間
  （21.22 / 46 / 61 / 75.59 / 84.69 / 106 秒）→ 用 `MiniMaxH3DirectorGroupsCombine` 併 → `CreateVideo` → `SaveVideo`。
- 13 種 class_type，**缺 3 種**（同一個包）：
  - `MiniMaxH3Director` / `MiniMaxH3DirectorGroupReferenceToVideo` / `MiniMaxH3DirectorGroupsCombine`
  - 來源：**`AIMixer/ComfyUI_MiniMaxH3_Director`**（該包另有 Director Conditioning／Group(Image to Video)／Director Plan）
- 模型：CLIP `qwen3vl_32b_minimax_h3_nvfp4_awq` ✅、兩顆 VAE ✅、LoRA `MysticXXX_MMH3-V1` ⚠️（本機在 `MMH3\` 子目錄，要補前綴）、
  UNET `minimax_h3_hybrid_fl2va_ref2va_b25-49-int8` ❌（本機是**分開的兩顆**）、turbo LoRA ❌

### WF2「sigma强化 + SelfLift 双采去油小脸不崩口型同步 MV 無限分段加速」

- 形狀：單段 6 步加速（`BasicScheduler` steps=6）＋ `SelfLiftAvatarH3Sampler`（低解析度跑前面步數再 lift 到全解析度）
  ＋ `H3SigmaRefiner`（低噪區補 2 步去油）＋ 4 張 `ref_images` ＋ `AudioCrop` 逐段抓 15s → 無限分段。
- 36 種 class_type，**缺 5 種**：
  - `H3SigmaRefiner` → **`yichengup/ComfyUI-YCNodes-MiniMax-H3`**
  - `SelfLiftAvatarH3Sampler` → **`facok/comfyui-SelfLift`**（很新的 repo）
  - `JjkText` → **`jjkramhoeft/ComfyUI-Jjk-Nodes`**
  - `SoundFlow_GetLength` → ComfyUI-SoundFlow（**可繞**：只是取音長）
  - `AudioCrop` → audio-separation-nodes-comfyui（**可換**：本機已有 `TrimAudioDuration`、`FL_Audio_Crop`）
- 好消息：`MiniMaxChunkFeedForward`／`MiniMaxLowVRAMAttention`／`ModelPreviewOverrideKJ`／`LTXV*` AV latent 全都有
  → 這支本來就是為低 VRAM 設計的，16GB 卡吃得住。
- 模型缺：UNET `minimax_h3_fl2va_bf16`（bf16 原檔 66GB 級）、CLIP `qwen3vl_32b_minimax_h3_int8_convrot`、
  LoRA `minimax_h3_fl2v_lightx2v_turbo_4step`（約 2GB）、**`h3-realism-people-t2v-i2v-r2v`（去油那顆，觸發詞 `r34l1sm`）**、
  `taeh3.safetensors`（tiny preview）、`minimax_h3_latent_upscaler_3d_fp16`（SelfLift 那步要用）。

### 兩支共同的注意事項

- workflow 裡的參考圖／音檔都是**對方機器上的 hash 檔名**（例 `309f2007…png`）→ 跑之前一律換成自己的素材。
- 交付報告結尾一定要標「**這兩個包能不能吃 0.34.6 要裝了才知道**」——不要替外來包保證相容性。
- 建議路線（使用者 2026-09-22 未拍板）：**先只補 WF2 那兩包**（YCNodes ＋ SelfLift）＋用本機現有模型替代，
  跑 5 秒小樣本驗「加速倍率／顆粒感／臉有沒有崩」，值得再補剩下的。不要一次全裝。

---

## 本機 H3 相關節點家族（2026-09-22 快照，用來快速判斷「是同一包嗎」）

- `T8/MiniMax H3/*`（56 顆以上）：LongVideo Orchestrator／Speech／MotionContext／Audio 系列
- `model/conditioning/minimax`：官方 `MiniMaxH3ReferenceToVideo`
- `KJNodes/experimental`：`MiniMaxChunkFeedForward`、`MiniMaxLowVRAMAttention`
- `model/patch/minimax`：`MiniMaxH3SigmaShift`
- 其他：`MiniMaxH3ImageToVideo`、`EmptyMiniMaxH3LatentAV`、`MiniMaxH3TokenCounter`、`SpectrumApplyMiniMaxH3`
- ⚠️ 本機 **沒有** `UnetLoaderGGUF` 的 H3 GGUF（GGUF 池僅 7 檔、H3 0 檔）→ 走的是 safetensors 量化版，
  而量化檔放在 `MiniMax H3\` 子目錄（`minimaxH3INT8INT4_fl2vaINT4BQPruned`、`minimax_h3_ref2va_pruned_fp8_scaled` 等）。
