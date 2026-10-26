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

⚠️ 為什麼基準要用「中位數」而不是「平均」（2026-10 第二次修正的漏報）：
  **一格壞幀會在差分序列上留下兩個尖峰**——進（前→壞幀）與出（壞幀→後）各一個，
  兩者相鄰。舊版拿鄰居的**平均**當基準，尖峰自己的隊友（另一個尖峰）把基準拉高，
  於是 `v > 3 × nbavg` 這兩條互相對消 → 單格閃爍 100% 漏報
  （實測：50 格全黑插一格全白，最大差 255，舊版仍回報「✅ 無孤立尖峰」）。
  改用**鄰居中位數**：一個隊友再大也只佔 4 個鄰居的 1 個，中位數仍是背景值。

用法：
  python3 check_frame_pops.py <file_or_dir> [--size 64x88] [--ratio 4] [--neighbor 3] [--abs-floor 1.0]

判定：
  ✅ 無孤立尖峰：正常（動作快的片是「連續高」不是「單格爆」）
  ⚠️ 有孤立尖峰：抽出確切那兩格（索引不能記錯）算 4x4 區塊差；
     「每一塊都在跳」＝整格被重繪／硬切 → 隔離該支＋換 seed 重跑。
     **相鄰成對的兩個尖峰（p, p+1 各一個）＝單格閃爍**：中間那一格被換掉，
     進出各留一個尖峰。只有一個尖峰則是「切了就沒回來」（轉場／接縫）。

注意：端點貼合（首/尾幀 SSIM）合格**不代表**中間沒壞 → 兩組 gate 都要跑。

自驗（改門檻或改演算法後必跑）：
  python3 -c "import check_frame_pops as m; print(m.detect_pops([0,0,0,12,0,0,0]))"
  → 必須抓到位於 index 3 的尖峰；`[8,8,9,8,8]`（正常快動作）必須是空的。
  python3 -c "import check_frame_pops as m; print(m.detect_pops([0,0,0,9,9,0,0,0]))"
  → 單格閃爍的**相鄰雙尖峰**必須抓到兩個（這是舊版必漏的案子）。
  端到端（最權威，勝過手動輸入數字）：
    ffmpeg -y -v error -f lavfi -i color=c=black:s=64x64:r=25:d=2 \
      -vf "drawbox=x=0:y=0:w=64:h=64:color=white:t=fill:enable='eq(n,25)'" -pix_fmt yuv420p flash1.mp4
    python3 check_frame_pops.py flash1.mp4   # 必須 ⚠️ 而不是 ✅
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
    """真中位數（偶數筆取中間兩筆平均）。基準值用它，才不會被單一尖峰帶走。"""
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def detect_pops(diffs, ratio=4.0, neighbor=3.0, abs_floor=1.0, window=2):
    """找出孤立尖峰，回傳 [(frame_index_after, diff, neighbor_avg), ...]。

    三個條件都要成立：
      1) 相對基準：v > ratio × baseline
         baseline＝全片中位數；**中位數為 0 時改用鄰近中位數**（靜止片的情況）
      2) 相對鄰居：v > neighbor × 鄰居中位數（排除「整段都在動」的快動作片）
      3) 絕對下限：v ≥ abs_floor（排除壓縮雜訊）

    🔴 鄰居一律用**中位數**：單格閃爍會產生相鄰的兩個尖峰（進／出），
       用平均的話最大值自己就是鄰居，`v > neighbor×avg` 這條會把兩個尖峰互相豁免掉
       → 整片靜止中插一格壞幀永遠抓不到（2026-10 實測的漏報）。
       中位數下一個隊友只佔 window×2 個鄰居裡的 1 個，基準仍是背景值。
    """
    if not diffs:
        return []
    n = len(diffs)
    med = _median(diffs)
    pops = []
    for k, v in enumerate(diffs):
        if v < abs_floor:
            continue
        lo = max(0, k - window)
        hi = min(n, k + window + 1)
        nb = [diffs[j] for j in range(lo, hi) if j != k]
        nbmed = _median(nb)
        baseline = med if med > 0 else nbmed
        if baseline > 0 and not (v > ratio * baseline):
            continue
        if nbmed > 0 and not (v > neighbor * nbmed):
            continue
        pops.append((k + 1, v, sum(nb) / len(nb) if nb else 0.0))
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
            idx = [p for p, _, _ in r["pops"]]
            flash = any(b - a == 1 for a, b in zip(idx, idx[1:]))
            hint = "  ⚠️ 相鄰雙尖峰＝單格閃爍（那一格被換掉，進出各一個尖峰）" if flash else ""
            print(f"{name:<45} ⚠️ 單格突變：{det}  ｜中位數 {r['median']:.2f}{hint}")
        else:
            print(f"{name:<45} ✅ 無孤立尖峰（中位數 {r['median']:.2f}、最大 {r['max']:.2f}@幀{r['max_at']}）")
    print(f"\n{len(files)} 支｜有問題 {bad} 支")


if __name__ == "__main__":
    main()
