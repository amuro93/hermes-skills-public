#!/usr/bin/env python3
"""掃一組已 clone 的 git repo，找機密外洩面（repo／檔名:行號／類別／長度）。

這是 `git-secret-leak-scan` 第二趟（內容層）的標準工具，取代臨時手寫的 ad-hoc 掃描。
繼承本 skill 的輸出鐵則：**永不印出命中字串本身**，連前幾碼都不印。

用法：
    python scan_repos_secrets.py <repo 父目錄> [-o result.json]

輸出每行：
    [repo] tracked=560 env=0 db=1 sens=2 hits=8 remote_token=-
    之後可讀 result.json 拿每個命中的 file/line/len 做人工複核。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# 全部用「完整長度」pattern —— 裸前綴會把文件裡的遮蔽樣本當外洩
PATTERNS = [
    ("deepseek/openai-key", re.compile(rb"sk-[A-Za-z0-9]{32,}")),
    ("openrouter-key",      re.compile(rb"sk-or-v1-[A-Za-z0-9]{40,}")),
    ("google-api-key",      re.compile(rb"AIza[A-Za-z0-9_-]{35}")),
    ("xai-key",             re.compile(rb"xai-[A-Za-z0-9]{40,}")),
    ("anthropic-key",       re.compile(rb"sk-ant-[A-Za-z0-9_-]{40,}")),
    ("github-pat",          re.compile(rb"ghp_[A-Za-z0-9]{36}")),
    ("github-pat-fine",     re.compile(rb"github_pat_[A-Za-z0-9_]{60,}")),
    ("nvidia-nim",          re.compile(rb"nvapi-[A-Za-z0-9_-]{40,}")),
    ("telegram-bot-token",  re.compile(rb"\b[0-9]{8,10}:AA[A-Za-z0-9_-]{33}")),
    ("sendgrid-key",        re.compile(rb"SG\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")),
    ("slack-token",         re.compile(rb"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("private-key-block",   re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("aws-key",             re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("jwt-long",            re.compile(rb"eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")),
    # ⚠️ 這條誤報最多，命中一定要人工複核（SQL 語句、shell 快照 PWD= 都會中）
    ("hardcoded-password",  re.compile(rb"""(?:password|passwd|pwd)\s*[:=]\s*['"][^'"\s]{8,}['"]""", re.I)),
]

# 被 git 追蹤就該問「為什麼進 repo」的檔名
SENSITIVE_NAME = re.compile(
    r"(^|/)(\.env(\..+)?|.*credentials?.*\.json|id_rsa|id_ed25519|.*\.pem|.*\.p12|.*\.pfx|"
    r"secrets?\.(json|ya?ml|txt)|.*\.sqlite3?|.*\.db|api[ _-]?key.*\.txt|.*token.*\.txt)$",
    re.I)

SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".mp4", ".mov", ".mp3",
            ".wav", ".zip", ".tar", ".gz", ".7z", ".pdf", ".woff", ".woff2", ".ttf",
            ".eot", ".so", ".dll", ".exe", ".pyc"}
MAX_BYTES = 4 * 1024 * 1024


class GitError(RuntimeError):
    """git 指令失敗。以前這裡 `except Exception: return ""` 會讓「掃不到」看起來像「乾淨」。"""


def git(repo, *args):
    """跑 git，回傳 raw bytes；非 0 結束碼一律拋錯（不可靜默回空字串）。"""
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=120)
    if r.returncode != 0:
        first = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise GitError(f"git {' '.join(args[:2])} rc={r.returncode}: {first[0] if first else ''}")
    return r.stdout


def git_text(repo, *args):
    return git(repo, *args).decode("utf-8", "replace")


def scan_repo(repo: Path):
    out = {"repo": repo.name, "files_tracked": 0, "env_tracked": [], "db_tracked": [],
           "sensitive_tracked": [], "hits": {}, "remote_has_token": None,
           "skipped_large": 0, "error": None}
    try:
        # -z：不加的話 git 會把非 ASCII／含空白的檔名加上引號跳脫，
        # 路徑就對不上磁碟上的檔 → 整檔被靜默跳過（實測中文檔名會漏掃）。
        raw = git(repo, "ls-files", "-z")
    except GitError as e:
        out["error"] = str(e)
        return out
    files = [f for f in raw.decode("utf-8", "replace").split("\0") if f.strip()]
    out["files_tracked"] = len(files)

    env_files = [f for f in files if re.search(r"(^|/)\.env(\.|$)", f)]
    db_files = [f for f in files if re.search(r"\.(db|sqlite3?)$", f, re.I)]
    out["env_tracked"] = env_files[:20]
    out["db_tracked"] = db_files[:20]
    out["sensitive_tracked"] = [f for f in files
                               if SENSITIVE_NAME.search(f) and f not in env_files][:20]

    # remote 是否內嵌 token —— 只回報有無，永不印 URL
    try:
        cfg = git_text(repo, "config", "--get", "remote.origin.url")
    except GitError:
        cfg = ""   # 沒有 origin 不算錯誤
    out["remote_has_token"] = bool(re.search(r"(ghp_|github_pat_|://[^/]*:[^@]+@)", cfg))

    for f in files:
        p = repo / f
        if p.suffix.lower() in SKIP_EXT:
            continue
        try:
            if not p.is_file():
                continue
            size = p.stat().st_size
            if size > MAX_BYTES:
                out["skipped_large"] += 1   # 跳過要計數，別靜默
                continue
            data = p.read_bytes()
            if b"\x00" in data[:4096]:
                continue
        except Exception:
            continue
        for cat, rx in PATTERNS:
            for m in rx.finditer(data):
                line = data.count(b"\n", 0, m.start()) + 1
                out["hits"].setdefault(cat, []).append(
                    {"file": f, "line": line, "len": len(m.group(0))})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="repo 父目錄（底下每個含 .git 的子目錄各算一個 repo）")
    ap.add_argument("-o", "--out", default="secret_scan_result.json")
    a = ap.parse_args()

    root = Path(a.root)
    repos = sorted([p for p in root.iterdir() if (p / ".git").exists()])
    if not repos:
        print("找不到任何含 .git 的 repo —— 先確認 clone 是否完成", file=sys.stderr)
        return 1

    results = []
    failed = 0
    for r in repos:
        res = scan_repo(r)
        results.append(res)
        n = sum(len(v) for v in res["hits"].values())
        if res["error"]:
            failed += 1
        print(f"[{r.name}] tracked={res['files_tracked']} env={len(res['env_tracked'])} "
              f"db={len(res['db_tracked'])} sens={len(res['sensitive_tracked'])} hits={n} "
              f"remote_token={'YES' if res['remote_has_token'] else '-'}"
              + (f" skipped_large={res['skipped_large']}" if res["skipped_large"] else "")
              + (f" ERROR={res['error']!r}" if res["error"] else ""))

    out = Path(a.out)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n=== {len(results)} repos → {out} ===")
    if failed:
        # 有 repo 掃不動就不能回 0：那會被上游腳本／CI 當成「全部乾淨」。
        print(f"🔴 {failed} 個 repo 掃描失敗（見 JSON 的 error 欄），結果不可視為乾淨", file=sys.stderr)
        return 2
    print("下一步：讀 json 逐筆人工複核（尤其 hardcoded-password），再決定哪些要驗活")
    return 0


if __name__ == "__main__":
    sys.exit(main())
