#!/usr/bin/env python3
"""審計：某個工具（例 vision_analyze）最近被叫用幾次、哪幾天、帶什麼參數。

為什麼要有這支：使用者會冷不防直接問「**妳這幾天有用 vision 嗎? 用的是哪個模型?**」
── 要當場拿得出**逐筆清單**（日期／圖／問句），不是靠印象回答。

安全（見 SKILL.md 鐵律）：
  1. 對 live DB 只開 `mode=ro` 連線，**不直開可寫連線**；
  2. 用 SQLite **Online Backup API**（`Connection.backup()`）把快照寫到暫存檔
     ——「依序 copy2 state.db / -wal / -shm」不是原子操作，複製期間的寫入
     會讓副本前後不一致（SQLite 官方文件就說這種複製只在有鎖保護時才安全）；
     真的要複製檔案時必須先取得 shared lock，或改用 backup API／`VACUUM INTO`。
  3. 查完刪暫存（`finally` 保證），動輒 400MB+ 不要留在 C 槽。

用法：
  python3 audit_tool_usage.py vision_analyze
  python3 audit_tool_usage.py vision_analyze --days 30 --dump-args
  python3 audit_tool_usage.py vision_analyze --profile "C:/Users/<user>/AppData/Local/hermes/profiles/<name>"
  python3 audit_tool_usage.py terminal --days 3          # 任何工具名都行
"""
import argparse
import datetime
import json
import os
import shutil
import sqlite3
import sys
import tempfile


def snapshot_state_db(profile: str, keep: bool) -> str:
    """把 live state.db 做成一致快照，回傳暫存目錄。"""
    live = os.path.join(profile, "state.db")
    if not os.path.exists(live):
        sys.exit(f"找不到 state.db：{live}\n用 --profile 指到 profile 目錄（或設 HERMES_HOME）")
    tmp = tempfile.mkdtemp(prefix="audit_db_")
    dest = os.path.join(tmp, "state.db")
    completed = False
    try:
        # 唯讀連線 + online backup：快照在一致性上等同「複製時的那一刻」，
        # 不需要停 gateway，也不會觸發 WAL recovery（那是裸可寫連線才會做的事）。
        src = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(dest)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        completed = True
    finally:
        # 失敗或中斷時絕不回傳半成品；keep 只適用於成功的快照。
        # 連線已由上面的 finally 關閉，Windows 才能移除副本。
        if not completed:
            try:
                shutil.rmtree(tmp)
            except OSError as e:
                # 清理失敗也不能掩蓋原始錯誤或繼續查詢。
                print(f"⚠️ 無法清除未完成快照 {tmp}：{e}", file=sys.stderr)
    return tmp


def iter_calls(con, tool: str, since_ts: float):
    """只看 assistant 訊息裡的 tool_calls。

    `role='tool'` 那幾列是「工具結果」，內容同樣含工具名 → 一起數會重複計數，
    所以查詢就帶 `role='assistant'`（不是靠呼叫端自己過濾）。
    """
    cur = con.execute(
        "SELECT timestamp, session_id, tool_calls FROM messages "
        "WHERE role = 'assistant' AND tool_calls LIKE ? AND timestamp >= ? "
        "ORDER BY timestamp",
        (f"%{tool}%", since_ts),
    )
    for row in cur:
        try:
            calls = json.loads(row["tool_calls"] or "[]")
        except Exception:
            continue
        if isinstance(calls, dict):
            calls = [calls]
        for c in calls:
            fn = (c or {}).get("function", {}) or {}
            if fn.get("name") != tool:
                continue
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {"_raw": (fn.get("arguments") or "")[:120]}
            yield row["timestamp"], row["session_id"], args


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tool", help="工具名，例如 vision_analyze")
    ap.add_argument("--profile", default=os.environ.get("HERMES_HOME") or os.getcwd())
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--dump-args", action="store_true", help="逐筆印出參數（問句/圖檔名）")
    ap.add_argument("--keep-copy", action="store_true", help="保留 DB 副本（預設查完刪掉，動輒 400MB+）")
    a = ap.parse_args()
    if not (1 <= a.days <= 36500):
        sys.exit(f"--days 必須介於 1 和 36500 之間（收到 {a.days}；更大的值會讓 timedelta 溢位）")

    try:
        tmp = snapshot_state_db(a.profile, a.keep_copy)
    except (sqlite3.Error, OSError) as e:
        print(f"❌ 建立一致快照失敗，已停止審計：{e}", file=sys.stderr)
        sys.exit(2)
    con = None
    try:
        db = os.path.join(tmp, "state.db")
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row

        since = (datetime.datetime.now() - datetime.timedelta(days=a.days)).timestamp()
        per_day, total, sessions = {}, 0, set()
        detail = []
        for ts, sid, args in iter_calls(con, a.tool, since):
            dt = datetime.datetime.fromtimestamp(ts)
            per_day.setdefault(dt.strftime("%Y-%m-%d"), []).append(dt.strftime("%H:%M"))
            sessions.add(sid)
            total += 1
            if a.dump_args:
                img = str(args.get("image_url") or args.get("path") or args.get("command") or "")
                q = str(args.get("question") or "").replace("\n", " ")[:70]
                detail.append((dt.strftime("%m-%d %H:%M"), os.path.basename(img)[:48], q))

        print(f"工具：{a.tool}｜範圍：最近 {a.days} 天｜總計：{total} 次（{len(sessions)} 個 session）")
        if not per_day:
            print("（0 次：這段期間沒有這支工具的呼叫紀錄）")
        for day in sorted(per_day, reverse=True):
            times = sorted(set(per_day[day]))
            shown = "、".join(times[:8]) + ("…" if len(times) > 8 else "")
            print(f"  {day}：{len(per_day[day])} 次  {shown}")
        if a.dump_args:
            print("\n逐筆參數：")
            for t, f, q in detail:
                print(f"  {t}  {f}\n      Q: {q}")
    finally:
        if con is not None:
            con.close()
        if not a.keep_copy:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
