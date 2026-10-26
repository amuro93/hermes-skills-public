#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_region_step.py — 抓「場景／取景階躍」型瑕疵（家具被推走、畫面整體滑走）

用途：AI 影片「播到一半家具/背景整體位移」的瑕疵（例：角色靠上沙發，扶手被「推」著滑走）。
      這類瑕疵是**連續型**：
        - check_frame_pops.py（單格突變）抓不到——沒有突變
        - 端點貼合（首幀 vs 來源圖、尾幀 vs 目標圖）也常合格——首尾都對得上
      → 只能專門量「過程中場景有沒有動」。

原理：挑一塊**角色永遠碰不到**的區域，逐格算它與第 0 幀的平均絕對差 dev[i]，
      再算逐格步階 step[i] = |dev[i] - dev[i-1]|。
        - 場景靜止  → dev 平穩、step 極小（只有壓縮噪聲）
        - 家具滑走／整格取景位移 → dev 後段爆走，且 step 有明顯尖峰

🔴 選區塊是這支工具唯一的手工藝（選錯＝全部誤判）：
      ✅ **純白牆角落**最好（角色、家具都碰不到；高對比、高穩定）
      ❌ **地板／沙發下緣／椅腳帶**：躺姿、伸腿、翹腳時她的腿腳就是會伸進去
         （實測那些區塊的 55.0／25.8 **全部是她自己的身體**，不是家具）
      ❌ 也**不要**用「追最暗欄／追最強垂直邊」的自動追蹤——追蹤器會改追她的大腿邊緣

門檻（1188×1740 Kling 片、160×220 灰階、量右上白牆角落的實測值）：
      好檔 step ≤0.5、後段漂移 1.3~2.8
      壞檔 step 2.9~10.8、後段漂移 11.6~14.5
    → 預設門檻 step ≤1.5（--step-tol）；但**同批互比**永遠比絕對值可靠。

用法：
    python3 check_region_step.py X.mp4
    python3 check_region_step.py <目錄> --region 0.86:0.98,0.06:0.20 --size 160x220
    python3 check_region_step.py A.mp4 B.mp4 --step-tol 1.0
    # --region = x0:x1,y0:y1（比例 0~1，左上為原點）

退出碼：0 = 全部通過；1 = 有檔案被標記（可直接當交件 gate 用）。
"""

import argparse
import glob
import os
import subprocess
import sys
import tempfile


def dump_gray(video: str, width: int, height: int):
    """把影片 dump 成 width×height 灰階 raw，回傳 (bytes, frames)。"""
    out = os.path.join(tempfile.gettempdir(), "region_step.gray")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", video,
           "-vf", f"scale={width}:{height},format=gray", "-f", "rawvideo", out]
    subprocess.run(cmd, check=True)
    with open(out, "rb") as fh:
        data = fh.read()
    frame_bytes = width * height
    return data, len(data) // frame_bytes if frame_bytes else 0


def parse_region(spec: str):
    try:
        xr, yr = spec.split(",")
        x0, x1 = (float(v) for v in xr.split(":"))
        y0, y1 = (float(v) for v in yr.split(":"))
    except Exception:
        sys.exit(f"--region 格式錯誤：{spec}（要像 0.86:0.98,0.06:0.20）")
    return x0, x1, y0, y1


def measure(video, width, height, region, step_tol):
    x0, x1, y0, y1 = region
    X0, X1 = int(width * x0), int(width * x1)
    Y0, Y1 = int(height * y0), int(height * y1)
    if X1 <= X0 or Y1 <= Y0:
        sys.exit("選的區塊是空的——檢查 --region 與 --size")

    data, n = dump_gray(video, width, height)
    if n < 3:
        return None

    fb = width * height
    idx = [(y * width + x) for y in range(Y0, Y1) for x in range(X0, X1)]
    frames = [[data[i * fb + k] for k in idx] for i in range(n)]
    base = frames[0]
    area = len(base)

    dev = [sum(abs(a - b) for a, b in zip(fr, base)) / area for fr in frames]
    step = [abs(dev[i] - dev[i - 1]) for i in range(1, n)]
    max_step = max(step)
    at = step.index(max_step) + 1
    third = max(1, n // 3)
    head = sum(dev[:third]) / third
    tail = sum(dev[-third:]) / third
    return {"frames": n, "dev": dev, "head": head, "tail": tail,
            "max_step": max_step, "at": at, "flag": max_step > step_tol,
            "max_dev": max(dev)}


def trace(dev, slots=10):
    n = len(dev)
    every = max(1, n // slots)
    return "".join(f"{v:5.1f}" for v in dev[::every])


def main():
    ap = argparse.ArgumentParser(description="抓場景／取景階躍（家具被推走、畫面整體滑走）")
    ap.add_argument("paths", nargs="+", help="影片檔或裝影片的目錄")
    ap.add_argument("--region", default="0.86:0.98,0.06:0.20",
                    help="量測區塊 x0:x1,y0:y1（比例；預設右上白牆角落）")
    ap.add_argument("--size", default="160x220", help="抽取尺寸 WxH（預設 160x220）")
    ap.add_argument("--step-tol", type=float, default=1.5, help="步階門檻（預設 1.5）")
    ap.add_argument("--trace", action="store_true", help="逐支印出 dev 軌跡")
    args = ap.parse_args()

    width, height = (int(v) for v in args.size.lower().split("x"))
    region = parse_region(args.region)

    files = []
    for p in args.paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, "*.mp4")))
        else:
            files.append(p)
    if not files:
        sys.exit("找不到影片檔")

    print(f"量測區塊 x{region[0]:.2f}~{region[1]:.2f}, y{region[2]:.2f}~{region[3]:.2f}"
          f"｜尺寸 {width}x{height}｜步階門檻 {args.step_tol}")
    print(f"{'檔名':<42}{'幀':>5}{'最大步階':>10}{'@幀':>6}{'前1/3':>8}{'後1/3':>8}  判定")

    flagged = 0
    for f in files:
        r = measure(f, width, height, region, args.step_tol)
        name = os.path.basename(f)
        if r is None:
            print(f"  {name:<40}{'—':>5}  讀不到幀")
            continue
        if r["flag"]:
            flagged += 1
        mark = "⚠️ 場景位移" if r["flag"] else "✅"
        print(f"  {name:<40}{r['frames']:>5}{r['max_step']:>10.1f}{r['at']:>6}"
              f"{r['head']:>8.1f}{r['tail']:>8.1f}  {mark}")
        if args.trace:
            print(f"      dev: {trace(r['dev'])}")

    print(f"\n{len(files)} 支｜有問題 {flagged} 支")
    if flagged:
        print("處置：⚠️ 這是『目標圖場景幾何與來源圖不一致』造成的（不是 prompt 問題）→"
              "把目標圖重做（鎖死家具/牆/地板/光線）後重跑同一支影片，不要花時間改 prompt。")
        print("⚠️ 若連純白牆都一起跳 → 是整格取景在動（不是家具自己滑）。")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
