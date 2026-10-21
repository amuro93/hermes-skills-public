#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_chapter_qc.py — 小說章節/番外稿件 QC 驗證腳本（fiction-chapter-qc skill 第二節）

用法:
  python verify_chapter_qc.py --file <新稿.md> [--refs 對照1.md,對照2.md] [--tics 低聲說,可是,啞著聲音]

檢查:
  1. 風格詞計數（預設門檻：低聲說 ≤12、可是 ≤4；其餘只報數不設限）
  2. 簡體字掃描（curated simplified-only 字表，啟發式，命中需人工確認）
  3. 與參考檔的 8+ 字逐字重複掃描（滑動視窗，合併成最長連續片段）
  4. 中文字數統計

Exit code: 0 = 全過; 1 = 有問題（可當 gate 用）
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
# 已驗證不在字表內的繁簡同形字（勿再加回，除非有明確證據屬簡體專用）：
VERIFIED_NOT_IN_SIMPLIFIED = set("都后坏夸干并狗云余准几")

CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def read_text(path):
    return Path(path).read_text(encoding="utf-8", errors="ignore")


def cjk_ngrams(text, n=8):
    """抽出連續 n 個中文字的滑動視窗（忽略標點/空白/英文）"""
    chars = CJK_RE.findall(text)
    if len(chars) < n:
        return set()
    return {"".join(chars[i:i + n]) for i in range(len(chars) - n + 1)}


def merge_overlaps(ngrams, n=8):
    """把滑動視窗 n-grams 合併成最長連續片段（排序後檢查前後 n-1 字相接）"""
    items = sorted(ngrams)
    merged = []
    for g in items:
        if merged and merged[-1][-(n - 1):] == g[:n - 1]:
            merged[-1] += g[n - 1:]
        else:
            merged.append(g)
    return merged


def main():
    ap = argparse.ArgumentParser(description="小說章節/番外稿件 QC")
    ap.add_argument("--file", required=True, help="新稿路徑")
    ap.add_argument("--refs", default="", help="對照檔路徑，逗號分隔")
    ap.add_argument("--tics", default="低聲說,可是,啞著聲音", help="風格詞，逗號分隔")
    args = ap.parse_args()

    text = read_text(args.file)
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

    # 3. 逐字重複掃描
    if args.refs:
        target_ngrams = cjk_ngrams(text)
        for ref_path in [p.strip() for p in args.refs.split(",") if p.strip()]:
            ref_ngrams = cjk_ngrams(read_text(ref_path))
            overlap = sorted(target_ngrams & ref_ngrams)
            if overlap:
                segments = merge_overlaps(overlap)
                shown = "／".join(segments[:5])
                problems.append(f"與 {Path(ref_path).name} 逐字重複: {shown}")
                print(f"  ⚠️ 與 {Path(ref_path).name} 重複片段: {shown}")
            else:
                print(f"  與 {Path(ref_path).name}: 無 8+ 字重複")

    # 4. 字數
    cjk_count = len(CJK_RE.findall(text))
    print(f"  中文字數: {cjk_count}")

    if problems:
        print("\n❌ QC 未過:")
        for p in problems:
            print("   -", p)
        sys.exit(1)
    print("\n✅ QC 全過")


if __name__ == "__main__":
    main()
