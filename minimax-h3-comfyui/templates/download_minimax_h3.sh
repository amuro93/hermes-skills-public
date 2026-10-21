#!/usr/bin/env bash
# ============================================================
# MiniMax H3 下載腳本 (pruned GGUF 方案) — 2026-08 實測 URL 全部 200
# 用法:
#   ./download_minimax_h3.sh            # 5080 16GB 方案 (Q4_K_M)
#   ./download_minimax_h3.sh --q3       # 4070 12GB 方案 (Q3_K_M + TE Q2_K)
#   ./download_minimax_h3.sh --turbo    # 5080 方案 + Turbo LoRA (v4)
#
# 放置目標 (依 ComfyUI 路徑修改):
#   COMFYUI/models/unet/           → transformer GGUF
#   COMFYUI/models/text_encoders/  → 文字編碼器 GGUF
#   COMFYUI/models/vae/            → VAE safetensors
#   COMFYUI/models/loras/          → Turbo LoRA
# 需要: ComfyUI v0.30.0+ + ComfyUI-GGUF 節點
# ============================================================
set -euo pipefail

COMFYUI="${COMFYUI:-$HOME/ComfyUI}"   # 改這裡指到你的 ComfyUI
PRUNED="Abiray/MiniMax-H3-Pruned-GGUF"
REBEL="realrebelai/MiniMax-H3_GGUFs"
COMFYORG="Comfy-Org/MiniMax-H3"
LARRY="larryvrh/MiniMax-H3-Turbo-Lora"

MODE="q4"
for arg in "$@"; do
  case "$arg" in
    --q3)    MODE="q3" ;;
    --turbo) MODE="turbo" ;;
  esac
done

dl() { # $1=repo $2=path $3=destdir $4=expect_bytes
  local url="https://huggingface.co/$1/resolve/main/$2"
  local out="$3/$(basename "$2")"
  mkdir -p "$3"
  echo ">>> $2"
  if [ -f "$out" ] && [ "$(stat -c%s "$out" 2>/dev/null || echo 0)" -ge "$4" ]; then
    echo "    已存在，跳過"
  else
    curl -L --fail --progress-bar -C - "$url" -o "$out"
  fi
  local got=$(stat -c%s "$out" 2>/dev/null || echo 0)
  if [ "$got" -lt "$4" ]; then
    echo "    ❌ 大小不符 (expect >= $4, got $got)" >&2
    exit 1
  fi
  echo "    ✅ OK ($got bytes)"
}

echo "== MiniMax H3 下載模式: $MODE =="

# --- Transformer (unet/) ---
case "$MODE" in
  q3)
    dl "$PRUNED" "MiniMax-H3-FL2VA-Pruned-Q3_K_M.gguf"  "$COMFYUI/models/unet/"          8900000000
    dl "$REBEL"  "qwen3vl-32B-MiniMax-H3-Q2_K.gguf"     "$COMFYUI/models/text_encoders/" 8490000000
    ;;
  turbo|q4)
    dl "$PRUNED" "MiniMax-H3-FL2VA-Pruned-Q4_K_M.gguf"  "$COMFYUI/models/unet/"          11560000000
    dl "$REBEL"  "qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf"   "$COMFYUI/models/text_encoders/" 14580000000
    ;;
esac

# --- Ref2VA (圖生影片, 選配但建議一起抓) ---
case "$MODE" in
  q3)
    dl "$PRUNED" "MiniMax-H3-Ref2VA-Pruned-Q3_K_M.gguf" "$COMFYUI/models/unet/"          8900000000
    ;;
  *)
    dl "$PRUNED" "MiniMax-H3-Ref2VA-Pruned-Q4_K_M.gguf" "$COMFYUI/models/unet/"          11560000000
    ;;
esac

# --- VAE (共用) ---
dl "$COMFYORG" "vae/minimax_h3_video_vae_fp16.safetensors" "$COMFYUI/models/vae/" 5210000000
dl "$COMFYORG" "vae/minimax_h3_audio_vae_fp32.safetensors" "$COMFYUI/models/vae/" 605000000

# --- Turbo LoRA (選配加速) ---
if [ "$MODE" = "turbo" ]; then
  dl "$LARRY" "minimax_h3_turbo_v4_step600_ema.safetensors" "$COMFYUI/models/loras/" 780000000
  echo ""
  echo "Turbo 工作流 (larryvrh 內附):"
  echo "  https://huggingface.co/larryvrh/MiniMax-H3-Turbo-Lora/resolve/main/minimax_h3_t2v_turbo.json"
fi

echo ""
echo "✅ 全部完成！"
echo "下一步:"
echo "  1. ComfyUI-Manager 裝 ComfyUI-GGUF (city96) + ComfyUI-MiniMax-H3-Turbo (Larryvrh)"
echo "  2. 官方工作流模板: https://github.com/Comfy-Org/workflow_templates (video_minimax_h3_*.json)"
echo "  3. 或 realrebelai 內附: FL2V_(WORKFLOW).json / REF2V_(WORKFLOW).json"
echo "  4. 注意官方模板預設載 int8_convrot/nvfp4, 要改成 UnetLoaderGGUF 載 .gguf"
