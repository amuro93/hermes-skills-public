#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_frame_pops.py — 抓「單格突變（跳幀）」

AI 影片常有「中間某一格畫面突然整格換掉」的瑕疵（播放時閃一下）。
用 check_jumps 只看「最大相鄰差」會漏判（單格爆掉但峰值不如快動作片）、
也會冤枉快動作片（正常動作的峰值本來就高）。

本工具的做法（判「孤立性」而不是大小）：
  逐格算相鄰幀平均差 → 取中位數當基準
  → 標出「> ratio×中位數 且 > neighbor×鄰近平均」的孤立尖峰

用法：
  python3 check_frame_pops.py <file_or_dir> [--size 64x88] [--ratio 4] [--neighbor 3]

判定：
  ✅ 無孤立尖峰：正常（動作快的片是「連續高」不是「單格爆」）
  ⚠️ 有孤立尖峰：抽出確切那兩格（索引不能記錯）算 4x4 區塊差；
     「每一塊都在跳」＝整格被重繪／硬切 → 隔離該支＋換 seed 重跑。

注意：端點貼合（首/尾幀 SSIM）合格**不代表**中間沒壞 → 兩組 gate 都要跑。
"""
import argparse, os, subprocess, tempfile


def dump(video, w, h):
    fd, path = tempfile.mkstemp(suffix=".gray")
    os.close(fd)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video,
                    "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", path], check=True)
    d = open(path, "rb").read()
    os.remove(path)
    return d, len(d) // (w * h)


def scan(video, w=64, h=88, ratio=4.0, neighbor=3.0):
    d, n = dump(video, w, h)
    px = w * h
    diffs = []
    for i in range(1, n):
        a = d[(i - 1) * px:i * px]
        b = d[i * px:(i + 1) * px]
        diffs.append(sum(abs(b[j] - a[j]) for j in range(px)) / px)
    if not diffs:
        return None
    s = sorted(diffs)
    med = s[len(s) // 2]
    pops = []
    for k, v in enumerate(diffs):
        lo = max(0, k - 2)
        hi = min(len(diffs), k + 3)
        nb = [diffs[j] for j in range(lo, hi) if j != k]
        nbavg = sum(nb) / len(nb) if nb else 0
        if med > 0 and v > ratio * med and (nbavg == 0 or v > neighbor * nbavg):
            pops.append((k + 1, v, nbavg))     # 幀 k → k+1
    return {"frames": n, "median": med, "max": max(diffs), "max_at": diffs.index(max(diffs)) + 1, "pops": pops}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--size", default="64x88")
    ap.add_argument("--ratio", type=float, default=4.0)
    ap.add_argument("--neighbor", type=float, default=3.0)
    a = ap.parse_args()
    w, h = (int(x) for x in a.size.lower().split("x"))

    if os.path.isdir(a.target):
        files = sorted(os.path.join(a.target, f) for f in os.listdir(a.target) if f.endswith(".mp4"))
    else:
        files = [a.target]

    bad = 0
    for f in files:
        r = scan(f, w, h, a.ratio, a.neighbor)
        name = os.path.basename(f)
        if r is None:
            print(f"{name:<45} 讀不到幀")
            continue
        if r["pops"]:
            bad += 1
            det = "｜".join(f"幀{p-1}→{p} 差{v:.2f}（鄰均{nb:.2f}）" for p, v, nb in r["pops"])
            print(f"{name:<45} ⚠️ 單格突變：{det}  ｜中位數 {r['median']:.2f}")
        else:
            print(f"{name:<45} ✅ 無孤立尖峰（中位數 {r['median']:.2f}、最大 {r['max']:.2f}@幀{r['max_at']}）")
    print(f"\n{len(files)} 支｜有問題 {bad} 支")


if __name__ == "__main__":
    main()
