#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_chapter_qc.py — 小說章節/番外稿件 QC 驗證腳本（fiction-chapter-qc skill 第二節）

用法:
  python verify_chapter_qc.py --file <新稿.md> [--refs 對照1.md,對照2.md] \
      [--tics 低聲說,可是,啞著聲音] [--min-repeat 8]

檢查:
  1. 風格詞計數（預設門檻：低聲說 ≤12、可是 ≤4；其餘只報數不設限）
  2. 簡體字掃描（curated simplified-only 字表，啟發式，命中需人工確認）
  3. 與參考檔的「最長連續共同片段」掃描（中文字序列，預設 ≥8 字才算抄重）
  4. 中文字數統計

Exit code: 0 = 全過; 1 = 有問題（可當 gate 用）; 2 = 檔案讀不進來（不可當「通過」）

⚠️ 2026-10 修正的兩個實作缺陷：
  - 舊版 `merge_overlaps()` 先 `sorted(ngrams)` 再只看「相鄰兩筆能不能接」，
    結果同一個片段會被字典序切碎、長度也可能被低估 → 改成直接從參考檔字串
    滑動延伸，取真正的最長連續共同片段。
  - 舊版讀檔用 `errors="ignore"`，**編碼壞掉的字會被靜默丟掉**，導致重複偵測
    少算卻沒有任何提示 → 改成明確解碼（UTF-8/UTF-8-BOM/CP950/UTF-16），
    全部失敗就以 exit 2 中止，不假裝掃過。
"""
import argparse
import re
import sys
from pathlib import Path

# 高可信簡體專用字：只存在於簡體寫法（已用台灣教育部常用字表4808字交叉比對）。
# 規格書 §4 陷阱：繁簡同形字（台灣也用，非簡體專用）不可收——
# 包含但不限於：都/后/坏/夸/干/并/狗/云/余/准/几/台/上/你/到/前/加/口/中/大/小/多/好/有/沒/嗎/呢/吧/啦/哦/啊/的/了/過/著/們/啊。
# 「准」在「不准/准許/批准」是正確用詞（禁止義），亦非簡體。
SIMPLIFIED_ONLY = set(
    "东严个为丽举书买们价众优会传伤体儿党关内写军农决况减凭刚别办务动区华协单卖卫历双发变叙叶号叹听员响图圆场块坚声处备复够头夹夺奋奖妈娇孙宁宝实审宪宫宽对寻导寿将尘尝届属岂师带帮广庄庆应开异弃张归当录无时机权来树样桥楼欢气汉汤泽灯点炼烂烟烦烧热猪猫现电经胜虽见观认让讲识话该说请读谁谢贝财责货质贵车边过还这进长门闪闭问闲间闷闹闻阀阅难题风飞马驴鱼鸟鸡鸭鹅龙龟"
)
VERIFIED_NOT_IN_SIMPLIFIED = set("都后坏夸干并狗云余准几")

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
ENCODINGS = ("utf-8", "utf-8-sig", "cp950", "utf-16")


class ReadError(Exception):
    pass


def read_text(path):
    """明確解碼；全部失敗就拋 ReadError（不要用 errors='ignore' 靜默丟字）。"""
    raw = Path(path).read_bytes()
    for enc in ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ReadError(f"{path}：{', '.join(ENCODINGS)} 都解不開（{len(raw)} bytes），先確認編碼再跑 QC")


def cjk_chars(text):
    return CJK_RE.findall(text)


def cjk_ngrams(chars, n=8):
    if len(chars) < n:
        return set()
    return {"".join(chars[i:i + n]) for i in range(len(chars) - n + 1)}


def shared_segments(ref_chars, target_ngrams, n=8):
    """從參考檔的字序列滑動，取「真正的最長連續共同片段」（長度 ≥ n）。"""
    segs, i, L = [], 0, len(ref_chars)
    while i <= L - n:
        if "".join(ref_chars[i:i + n]) in target_ngrams:
            j = i + n
            while j < L and "".join(ref_chars[j - n + 1:j + 1]) in target_ngrams:
                j += 1
            segs.append("".join(ref_chars[i:j]))
            i = j
        else:
            i += 1
    return segs


def main():
    ap = argparse.ArgumentParser(description="小說章節/番外稿件 QC")
    ap.add_argument("--file", required=True, help="新稿路徑")
    ap.add_argument("--refs", default="", help="對照檔路徑，逗號分隔")
    ap.add_argument("--tics", default="低聲說,可是,啞著聲音", help="風格詞，逗號分隔")
    ap.add_argument("--min-repeat", type=int, default=8,
                    help="視為抄重的最短連續字數（預設 8；短句借用屬正常，別調太低）")
    args = ap.parse_args()

    try:
        text = read_text(args.file)
    except (OSError, ReadError) as e:
        print(f"❌ 讀不到稿子：{e}", file=sys.stderr)
        sys.exit(2)

    problems = []

    # 1. 風格詞計數
    for tic in [t for t in args.tics.split(",") if t.strip()]:
        cnt = text.count(tic)
        flag = ""
        if tic == "低聲說" and cnt > 12:
            flag = "  ⚠️ 預設門檻 ≤12"
            problems.append(f"低聲說 {cnt} 次超標")
        if tic == "可是" and cnt > 4:
            flag = "  ⚠️ 預設門檻 ≤4"
            problems.append(f"可是 {cnt} 次超標")
        print(f"  風格詞 [{tic}]: {cnt}{flag}")

    # 2. 簡體字
    found = sorted({c for c in text if c in SIMPLIFIED_ONLY})
    if found:
        problems.append(f"簡體字候選: {''.join(found)}")
        print(f"  ⚠️ 簡體字候選: {''.join(found)}（啟發式，請人工確認）")
    else:
        print("  簡體字: 無")

    # 3. 逐字重複掃描（最長連續共同片段）
    target_chars = cjk_chars(text)
    target_ngrams = cjk_ngrams(target_chars, args.min_repeat)
    for ref_path in [p.strip() for p in args.refs.split(",") if p.strip()]:
        try:
            ref_chars = cjk_chars(read_text(ref_path))
        except (OSError, ReadError) as e:
            print(f"❌ 讀不到對照檔：{e}", file=sys.stderr)
            sys.exit(2)
        segs = sorted(set(shared_segments(ref_chars, target_ngrams, args.min_repeat)),
                      key=len, reverse=True)
        if segs:
            shown = "／".join(f"{s}({len(s)}字)" for s in segs[:5])
            problems.append(f"與 {Path(ref_path).name} 逐字重複: {shown}")
            print(f"  ⚠️ 與 {Path(ref_path).name} 重複片段: {shown}")
        else:
            print(f"  與 {Path(ref_path).name}: 無 {args.min_repeat}+ 字連續重複")

    # 4. 字數
    print(f"  中文字數: {len(target_chars)}")

    if problems:
        print("\n❌ QC 未過:")
        for p in problems:
            print("   -", p)
        sys.exit(1)
    print("\n✅ QC 全過")


if __name__ == "__main__":
    main()
