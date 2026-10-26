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

⚠️ 2026-10 修正的實作缺陷（每一項都有對應探針，改完必跑）：
  - 舊版 `merge_overlaps()` 先 `sorted(ngrams)` 再只看「相鄰兩筆能不能接」，
    結果同一個片段會被字典序切碎、長度也可能被低估 → 改成直接從參考檔字串
    滑動延伸，取真正的最長連續共同片段。
  - 舊版讀檔用 `errors="ignore"`，**編碼壞掉的字會被靜默丟掉**，導致重複偵測
    少算卻沒有任何提示 → 改成明確解碼（UTF-8/UTF-8-BOM/CP950/UTF-16），
    全部失敗就以 exit 2 中止，不假裝掃過。
  - 🔴 舊版 `shared_segments()` 拿目標稿的 n-gram **集合**去延伸參考稿的字序列。
    集合沒有位置資訊 ⇒ 只要這些 n-gram 各自散落在目標稿不同地方，就能接力拼出
    一句「連續 11 字重複」的指控，而那 11 字在目標稿裡從未連續出現 → **誤判抄重**。
    （實測：目標稿是「甲乙丙丁戊己庚辛」、「乙丙丁戊己庚辛壬」、「丙丁戊己庚辛壬癸」…
      這種**逐字錯位**的多句寫法，每句各隔一段；參考稿把最前那句一路接到最後。
      舊版報「11 字連續重複」（在目標稿裡 find() = -1，根本不存在），
      目標稿真正連續的共同片段只有 8 字。）
    現在改成逐字位置比對，報告的每段都保證是兩邊都存在的連續子字串。
  - 🔴 舊版對空白稿（0 個中文字）三項檢查全過 → 印「✅ QC 全過」。
    現在 `--min-chars`（預設 1）擋空稿，要擋半成品可調高（例：1500）。

自驗（改任何一項檢查後必跑，別只跑真稿一次就宣布可用）：
  1) 錯位誤判：見下面 `shared_segments()` docstring 的範例組合，
     修好的版本必須回報 8 字、**不是** 13 字以上。
  2) 真空稿：`printf '' > e.md` → exit 1（不是「✅ QC 全過」）。
  3) 真完稿：寫 20 個中文字 → exit 0，且印「中文字數 20」。
  4) 真的抄重：參考稿與新稿放同一段 12 字 → exit 1 且印出該 12 字。
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


def shared_segments(ref_chars, target_chars, n=8):
    """取「在**兩邊都真的連續存在**」的最長共同片段（長度 ≥ n）。

    🔴 2026-10 修正（誤判：把分散片段拼成不存在的連續長句）：
       舊版拿目標稿的 n-gram **集合**去比對參考稿的字序列——集合沒有位置資訊，
       只要 n-gram 各自出現在目標稿的不同地方，就能一路接力延伸，
       最後印出一句「參考稿裡連續 N 字」的句子，但那 N 字在目標稿裡**從沒連續出現過**。
       現在的作法：先建 n-gram → 位置清單，命中後**從兩邊同一位置逐字往後比對**，
       報告的每個片段都是 `ref[i:i+k] == target[t:t+k]` 驗證過的連續子字串。
       ⇒ 寧可少報一個「巧合疊字」，也不報一個不存在的抄重指控。

    範例（n=8，兩邊都取中文字）：
      目標稿：甲乙丙丁戊己庚辛 / 乙丙丁戊己庚辛壬 / 丙丁戊己庚辛壬癸 …（逐字錯位，各句隔開）
      參考稿：甲乙丙丁戊己庚辛壬癸子丑寅   ← 這 13 字在參考稿裡是真的連續
      舊版：報 11 字「甲乙丙丁戊己庚辛壬癸子」（假的，目標稿 find() = -1）
      現在：報 8 字「甲乙丙丁戊己庚辛」（真的，目標稿第一句就是這 8 字）
    """
    if len(ref_chars) < n or len(target_chars) < n:
        return []
    ref = "".join(ref_chars)
    tgt = "".join(target_chars)
    positions = {}
    for t in range(len(tgt) - n + 1):
        positions.setdefault(tgt[t:t + n], []).append(t)

    segs, i, L = [], 0, len(ref)
    while i <= L - n:
        best = 0
        for t in positions.get(ref[i:i + n], ()):
            k = n
            while i + k < L and t + k < len(tgt) and ref[i + k] == tgt[t + k]:
                k += 1
            if k > best:
                best = k
        if best >= n:
            segs.append(ref[i:i + best])
            i += best          # 跳過已計入的區段，避免同一段被重複報告
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
    ap.add_argument("--min-chars", type=int, default=1,
                    help="最少中文字數（預設 1＝只擋空稿；要擋半成品可調高，例如 1500。0＝關閉）")
    args = ap.parse_args()

    try:
        text = read_text(args.file)
    except (OSError, ReadError) as e:
        print(f"❌ 讀不到稿子：{e}", file=sys.stderr)
        sys.exit(2)

    problems = []
    target_chars = cjk_chars(text)

    # 0. 空稿／佔位稿：0 個中文字時「三項檢查全過」會變成假 PASS
    if len(target_chars) < args.min_chars:
        problems.append(f"稿子只有 {len(target_chars)} 個中文字（門檻 {args.min_chars}）"
                        f"—— 空稿、只有標題或寫到一半，不可視為完稿")
        print(f"  🔴 中文字數 {len(target_chars)} < 門檻 {args.min_chars}：視為空稿／未完成")

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
    for ref_path in [p.strip() for p in args.refs.split(",") if p.strip()]:
        try:
            ref_chars = cjk_chars(read_text(ref_path))
        except (OSError, ReadError) as e:
            print(f"❌ 讀不到對照檔：{e}", file=sys.stderr)
            sys.exit(2)
        segs = sorted(set(shared_segments(ref_chars, target_chars, args.min_repeat)),
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
