#!/usr/bin/env python3
"""盘點素材包 → 寫一份「規格＋sha256」清單（交付前對帳、憑證到期/換機前搶救用）。

用法：
    python3 inventory_assets.py DIR [DIR ...] [--out MANIFEST.md] [--ext mp4,png,jpg]

為何要有這支：
  * 服務商沒有「列出歷史作品」的 API，作品清單只存在本機（見 SKILL.md §6）→
    手上有什麼只能自己盤；盤完的 sha256 清單就是之後「對帳缺哪些」的正本。
  * 驗收門檻要跟素材來源匹配（§3）→ 所以逐支把 width/height/fps/nb_frames 印出來，不要只抽一支相信。

零依賴：只用 stdlib；影片規格走 ffprobe（沒有 ffprobe 時降級成只算 sha256＋大小）。
只在輸出/錯誤用中文，欄位名保持英文方便 grep。
"""
import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys

DEFAULT_EXT = "mp4,mov,webm,png,jpg,jpeg,webp"

def ffprobe_video(path):
    """回 dict（拿不到就回 None）——欄位對齊 SKILL.md §3 的 ffprobe 配方。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate,nb_frames,codec_name",
             "-of", "json", path],
            capture_output=True, text=True, timeout=120).stdout
        st = (json.loads(out).get("streams") or [{}])[0]
        if not st:
            return None
        num, _, den = (st.get("r_frame_rate") or "0/1").partition("/")
        fps = round(float(num) / float(den), 3) if float(den or 0) else None
        return {"w": st.get("width"), "h": st.get("height"), "fps": fps,
                "frames": st.get("nb_frames"), "codec": st.get("codec_name")}
    except Exception:
        return None

def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--out", default=None, help="輸出 md（預設 <第一個 dir>/_inventory_<YYYYMMDD>.md）")
    ap.add_argument("--ext", default=DEFAULT_EXT, help="要盤的副檔名，逗號分隔")
    a = ap.parse_args()
    exts = tuple("." + e.strip().lower().lstrip(".") for e in a.ext.split(",") if e.strip())

    groups = {}
    for d in a.dirs:
        if not os.path.isdir(d):
            print(f"⚠️ 跳過（不是目錄）：{d}", file=sys.stderr)
            continue
        for root, _dirs, files in os.walk(d):
            for fn in sorted(files):
                if not fn.lower().endswith(exts):
                    continue
                fp = os.path.join(root, fn)
                key = os.path.relpath(root, d).replace("\\", "/")
                if key == ".":
                    key = "(root)"
                groups.setdefault((d, key), []).append(fp)

    lines = ["# 素材盤點（inventory_assets.py）", "",
             f"產生時間：{datetime.datetime.now():%Y-%m-%d %H:%M}　機器：{os.environ.get('COMPUTERNAME') or os.uname().nodename}",
             f"來源：{', '.join(a.dirs)}", "", "## 各群組數量與大小", ""]
    summary = []
    detail = []
    for (d, key), fps_ in sorted(groups.items()):
        total = sum(os.path.getsize(p) for p in fps_)
        summary.append(f"- `{os.path.basename(d.rstrip('/'))}/{key}` — {len(fps_)} 支 / {total / 1e6:.1f} MB")
        detail.append(f"### {os.path.basename(d.rstrip('/'))}/{key}（{len(fps_)} 檔）\n")
        for p in fps_:
            spec = ffprobe_video(p) if p.lower().endswith((".mp4", ".mov", ".webm")) else None
            if spec and spec.get("w"):
                s = f"{spec['w']}x{spec['h']} / {spec['fps']}fps / {spec['frames']} 幀 / {spec['codec']}"
            else:
                s = "(非影片或 ffprobe 不可用)"
            detail.append(f"- `{os.path.relpath(p, d).replace(chr(92), '/')}` — {s} / "
                          f"{os.path.getsize(p) / 1e6:.2f} MB — `{sha256_file(p)}`")
        detail.append("")

    lines += summary + ["", "## 逐檔規格與 sha256", ""] + detail
    out = a.out or os.path.join(a.dirs[0], f"_inventory_{datetime.datetime.now():%Y%m%d}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    n = sum(len(v) for v in groups.values())
    print(f"已寫出 {out}｜{n} 檔")
    for ln in summary:
        print("  " + ln)
    print("⚠️ 「已交付」不等於「磁碟上有」——用這份清單跟腳本宣告的清單對帳（宣告是正本）。")

if __name__ == "__main__":
    main()
