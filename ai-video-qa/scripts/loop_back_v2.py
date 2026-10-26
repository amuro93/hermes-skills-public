#!/usr/bin/env python3
"""loop_back v2 — 倒轉閉環「進階版」（解 使用者 2026-09-15 指出的兩個病灶）

使用者 指出的問題：
  ① 倒轉接片後「頭尾停很久、接起來停更久」← 來源片頭尾各有一段靜止，倒轉後變成兩份
  ② 接合處閃爍

解法（全部純 ffmpeg，0 點）：
  1. **自動偵測動作區間**（32×32 灰階逐幀差）→ 剪掉頭尾靜止段
  2. 只留「動作段 ＋ 倒轉動作段」，接縫那格重複幀**去掉一格**
  3. 可指定總幀數（預設不裁）→ 舞台規格 121 幀可直接對齊
  4. 全程**同一組編碼參數重編**（CRF 18、yuv420p、CFR 24fps）
     ← 閃爍最常見來源＝「不同參數片段硬 concat」或 VFR 時間戳
  5. `--keep-holds` 可保留停頓做對照

用法：
  python3 loop_back_v2.py IN.mp4 --out OUT.mp4 [--conform 1188x1740] [--frames 121]
"""
import argparse, math, os, subprocess, sys, tempfile
import numpy as np


def run(cmd):
    """回傳 stdout（bytes）；失敗就直接中止"""
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        print("FAILED:", " ".join(str(c) for c in cmd)[:240])
        print((r.stderr or b"")[-500:].decode("utf-8", "replace"))
        sys.exit(1)
    return r.stdout


def probe(video, entries):
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
               "-show_entries", f"stream={entries}", "-of", "default=noprint_wrappers=1", video]).decode()
    d = {}
    for line in out.strip().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k] = v
    return d


def encode(infile, src_filters, dst):
    run(["ffmpeg", "-y", "-v", "error", "-i", infile, "-vf", src_filters, "-an",
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "24", "-fps_mode", "cfr", dst])
    return dst


def motion_window(video, thresh=1.5, pad=2):
    """(start, end) 動作區間"""
    info = probe(video, "nb_frames")
    n = int(info.get("nb_frames", "0") or 0)
    raw = run(["ffmpeg", "-v", "error", "-i", video, "-vf", "scale=32:32,format=gray",
               "-f", "rawvideo", "-"])
    frames = np.frombuffer(raw, dtype=np.uint8)
    if n <= 0:
        n = len(frames) // (32 * 32)
    frames = frames[: n * 32 * 32].reshape(n, 32 * 32).astype(np.float32)
    if n < 4:
        return 0, max(n - 1, 0)
    d = np.abs(np.diff(frames, axis=0)).mean(axis=1)
    active = np.where(d > thresh)[0]
    if len(active) == 0:
        return 0, n - 1
    return max(0, int(active[0]) - pad), min(n - 1, int(active[-1]) + 1 + pad)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", required=True)
    ap.add_argument("--conform", default=None, help="例 1188x1740")
    ap.add_argument("--frames", type=int, default=0, help="目標總幀數（0=不裁）")
    ap.add_argument("--thresh", type=float, default=1.5)
    ap.add_argument("--keep-holds", action="store_true")
    ap.add_argument("--fit", action="store_true",
                    help="把動作段伸縮（慢放/快轉）到剛好填滿目標幀數；係數限制 0.5~4x")
    ap.add_argument("--max-fit", type=float, default=4.0)
    a = ap.parse_args()

    info = probe(a.src, "nb_frames")
    n = int(info.get("nb_frames", "0") or 0)
    s, e = (0, n - 1) if a.keep_holds else motion_window(a.src, a.thresh)
    print(f"來源 {os.path.basename(a.src)}: {n} 幀 → 動作區間 [{s}, {e}] = {e - s + 1} 幀"
          f"{'（保留停頓）' if a.keep_holds else ''}")

    d = tempfile.mkdtemp(prefix="loopv2_")
    L = e - s + 1
    target_half = math.ceil(a.frames / 2) if a.frames else L
    speed_note = ""
    if a.fit and a.frames:
        factor = target_half / L
        if 0.5 <= factor <= a.max_fit:
            speed_note = f"｜伸縮 ×{factor:.2f}（慢放）" if factor > 1 else f"｜伸縮 ×{factor:.2f}（快轉）"
            seg_f = (f"select='between(n\\,{s}\\,{e})',setpts=N/FRAME_RATE/TB,"
                     f"setpts=PTS*{factor:.4f}")
        else:
            speed_note = f"｜動作 {L} 幀、係數 {factor:.2f} 超出範圍 → 不伸縮"
            seg_f = f"select='between(n\\,{s}\\,{e})',setpts=N/FRAME_RATE/TB"
    else:
        seg_f = f"select='between(n\\,{s}\\,{e})',setpts=N/FRAME_RATE/TB"
    seg = encode(a.src, seg_f, os.path.join(d, "seg.mp4"))
    info2 = probe(seg, "nb_frames")
    L = int(info2.get("nb_frames", "0") or L)

    half = math.ceil(a.frames / 2) if a.frames else L
    print(f"  動作段 {L} 幀{speed_note}")
    half = min(half, L)
    part = encode(seg, f"select='lt(n\\,{half})',setpts=N/FRAME_RATE/TB", os.path.join(d, "part.mp4"))
    rev = encode(part, "reverse", os.path.join(d, "rev.mp4"))
    # 接縫去重：反轉段去掉第 0 幀（＝正向段最後一幀）
    rev2 = encode(rev, "select='gt(n\\,0)',setpts=N/FRAME_RATE/TB", os.path.join(d, "rev2.mp4"))

    lst = os.path.join(d, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.write(f"file '{os.path.abspath(part)}'\nfile '{os.path.abspath(rev2)}'\n")
    cat = os.path.join(d, "cat.mp4")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-an",
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "24", "-fps_mode", "cfr", cat])

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    _w, _h = (a.conform.split("x") if a.conform else (None, None))
    vf = (f"scale={_w}:{_h}:force_original_aspect_ratio=decrease,pad={_w}:{_h}:(ow-iw)/2:(oh-ih)/2:white"
          if a.conform else "null")
    encode(cat, vf, a.out)
    oi = probe(a.out, "width,height,nb_frames,r_frame_rate,duration")
    print(f"OK:{a.out}  {oi.get('width')}x{oi.get('height')}  {oi.get('nb_frames')} 幀  "
          f"{oi.get('r_frame_rate')}  {oi.get('duration')}s")


if __name__ == "__main__":
    main()
