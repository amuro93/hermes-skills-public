#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_frame_pops.py — 抓「單格突變（跳幀）」

AI 影片常有「中間某一格畫面突然整格換掉」的瑕疵（播放時閃一下）。
用 `check_jumps` 只看「最大相鄰差」會漏判（單格爆掉但峰值不如快動作片）、
也會冤枉快動作片（正常動作的峰值本來就高）。

本工具判「孤立性」而不是大小：
  逐格算相鄰幀平均差 → 取中位數當基準
  → 標出「> ratio×基準 且 > neighbor×鄰近平均 且 ≥ abs_floor」的孤立尖峰

⚠️ 為什麼需要 `abs_floor`（2026-10 修正的漏報）：
  靜止畫面（idle、停格、慢速轉場）的**中位數是 0**，舊版把 `median > 0` 寫成前置條件，
  於是「整片靜止中插一格壞幀」永遠判成「無孤立尖峰」——最該抓的情況剛好抓不到。
  現在中位數為 0 時改以「鄰近平均」當基準，並用 `abs_floor`（絕對灰階差下限）
  擋掉壓縮雜訊。

用法：
  python3 check_frame_pops.py <file_or_dir> [--size 64x88] [--ratio 4] [--neighbor 3] [--abs-floor 1.0]

判定：
  ✅ 無孤立尖峰：正常（動作快的片是「連續高」不是「單格爆」）
  ⚠️ 有孤立尖峰：抽出確切那兩格（索引不能記錯）算 4x4 區塊差；
     「每一塊都在跳」＝整格被重繪／硬切 → 隔離該支＋換 seed 重跑。

注意：端點貼合（首/尾幀 SSIM）合格**不代表**中間沒壞 → 兩組 gate 都要跑。

自驗（改門檻或改演算法後必跑）：
  python3 -c "import check_frame_pops as m; print(m.detect_pops([0,0,0,12,0,0,0]))"
  → 必須抓到位於 index 3 的尖峰；`[8,8,9,8,8]`（正常快動作）必須是空的。
"""
import argparse, os, subprocess, tempfile


def dump(video, w, h):
    fd, path = tempfile.mkstemp(suffix=".gray")
    os.close(fd)
    try:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video,
                        "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", path], check=True)
        with open(path, "rb") as f:
            d = f.read()
    finally:
        os.remove(path)
    return d, len(d) // (w * h)


def frame_diffs(d, w, h):
    """回傳相鄰幀平均絕對差序列；第 k 筆＝幀 k → k+1。"""
    px = w * h
    n = len(d) // px
    diffs = []
    for i in range(1, n):
        a = d[(i - 1) * px:i * px]
        b = d[i * px:(i + 1) * px]
        diffs.append(sum(abs(b[j] - a[j]) for j in range(px)) / px)
    return diffs


def _median(xs):
    s = sorted(xs)
    return s[len(s) // 2] if s else 0.0


def detect_pops(diffs, ratio=4.0, neighbor=3.0, abs_floor=1.0, window=2):
    """找出孤立尖峰，回傳 [(frame_index_after, diff, neighbor_avg), ...]。

    三個條件都要成立：
      1) 相對基準：v > ratio × baseline
         baseline＝全片中位數；**中位數為 0 時改用鄰近平均**（靜止片的情況）
      2) 相對鄰居：v > neighbor × 鄰近平均（排除「整段都在動」的快動作片）
      3) 絕對下限：v ≥ abs_floor（排除壓縮雜訊）
    """
    if not diffs:
        return []
    med = _median(diffs)
    pops = []
    for k, v in enumerate(diffs):
        lo = max(0, k - window)
        hi = min(len(diffs), k + window + 1)
        nb = [diffs[j] for j in range(lo, hi) if j != k]
        nbavg = sum(nb) / len(nb) if nb else 0.0
        baseline = med if med > 0 else nbavg
        if v < abs_floor:
            continue
        if not (v > ratio * baseline):
            continue
        if nbavg > 0 and not (v > neighbor * nbavg):
            continue
        pops.append((k + 1, v, nbavg))
    return pops


def scan(video, w=64, h=88, ratio=4.0, neighbor=3.0, abs_floor=1.0):
    d, n = dump(video, w, h)
    diffs = frame_diffs(d, w, h)
    if not diffs:
        return None
    pops = detect_pops(diffs, ratio, neighbor, abs_floor)
    return {"frames": n, "median": _median(diffs), "max": max(diffs),
            "max_at": diffs.index(max(diffs)) + 1, "pops": pops}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--size", default="64x88")
    ap.add_argument("--ratio", type=float, default=4.0)
    ap.add_argument("--neighbor", type=float, default=3.0)
    ap.add_argument("--abs-floor", type=float, default=1.0,
                    help="絕對灰階差下限；中位數為 0（靜止片）時唯一有效的門檻")
    a = ap.parse_args()
    w, h = (int(x) for x in a.size.lower().split("x"))

    if os.path.isdir(a.target):
        files = sorted(os.path.join(a.target, f) for f in os.listdir(a.target) if f.endswith(".mp4"))
    else:
        files = [a.target]

    bad = 0
    for f in files:
        r = scan(f, w, h, a.ratio, a.neighbor, a.abs_floor)
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
