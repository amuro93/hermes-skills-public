---
name: systematic-debugging
description: Use when encountering any bug, test failure, or unexpected behavior. 4-phase root cause investigation — NO fixes without understanding the problem first.
version: 1.1.0
author: Hermes Agent (adapted from obra/superpowers)
license: MIT
metadata:
  hermes:
    tags: [debugging, troubleshooting, problem-solving, root-cause, investigation]
    related_skills: [test-driven-development]
---

# Systematic Debugging

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure.

**Violating the letter of this process is violating the spirit of debugging.**

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed Phase 1, you cannot propose fixes.

## When to Use

Use for ANY technical issue:
- Test failures
- Bugs in production
- Unexpected behavior
- Performance problems
- Build failures
- Integration issues

**Use this ESPECIALLY when:**
- Under time pressure (emergencies make guessing tempting)
- "Just one quick fix" seems obvious
- You've already tried multiple fixes
- Previous fix didn't work
- You don't fully understand the issue

**Don't skip when:**
- Issue seems simple (simple bugs have root causes too)
- You're in a hurry (rushing guarantees rework)
- Someone wants it fixed NOW (systematic is faster than thrashing)

## The Four Phases

You MUST complete each phase before proceeding to the next.

---

## ⚡ Quick Win Checklist (Start Here for Frontend/Web Bugs)

Before diving into full 4-phase investigation, check these common culprits FIRST:

### 1. JS Console
- Open DevTools Console (F12)
- **No errors ≠ JS ran correctly** — errors can be silently swallowed by try-catch or async rejection
- If console is **completely empty** (no log, no error), check if JS file loaded at all

### 2. Browser Cache
```javascript
// Check if the loaded JS/cache is stale
fetch('/static/js/app.js?nocache='+Date.now())
  .then(r=>r.text())
  .then(t=>console.log('has fix:', t.includes('expected-string')))
```
- Use **Ctrl+Shift+R** (hard reload) OR DevTools → Disable cache
- Or add `?v=N` cache-bust to `<script src>` in HTML — and **actually push/deploy** the HTML change to CDN
- Even after deploying the fix, browsers and CDNs may serve old files for minutes
- **To verify:** fetch the JS file with a cache-busting query param and check if it contains the fix string

### 3. DOM Exists But Page Is Blank
Golden rule: `display: none` on an **ancestor** hides everything inside, even if children have `display: block`.
- Check **computed style** of parent containers: `getComputedStyle(el).display`
- Inline style may be empty but CSS class could still force `display: none`
```javascript
// Three-way check
el.style.display               // inline style (what JS set)
el.getAttribute('style')       // raw style attribute (null if never touched by JS)
getComputedStyle(el).display   // actual final style (CSS + inline)
```

**Critical insight:** `el.style.display` returning empty string (`""`) does NOT mean the element is visible. It means JS never set it. The CSS class may still force `display: none`. Always check `getComputedStyle(el).display` for truth.

**Don't forget parent containers!** A child can have `display: block` but if any ancestor has `display: none`, the child is invisible. Check the entire parent chain when debugging blank pages.

### 4. PWA / Service Worker
- Manifest + SW can serve stale cached content even after deploy
- Clear site data: DevTools → Application → Storage → Clear site data
- Or unregister SW: `navigator.serviceWorker.getRegistrations().then(regs => regs.forEach(r => r.unregister()))`

### 5. JS SyntaxError Points to Import Line but Parent Module Loads Fine

**The "Import Chain" trap:** When `main.js` (parent) reports `SyntaxError: Invalid or unexpected token at main.js:60:44`, but main.js itself successfully loads and emits startup logs — the error is actually in a **child module** that main.js imports, not in main.js itself.

**Why:** Browser attributes syntax errors in dynamically imported modules to the parent's `import()` statement line, not to the actual child file where the error occurs.

**Diagnosis:**
```bash
# Validate ALL JS files as ES modules with Node.js (.mjs forces module mode)
for f in static/js/views/*.js static/js/components/*.js static/js/core/*.js; do
  cp "$f" /tmp/test.mjs
  node --check /tmp/test.mjs 2>&1 && echo "✅ $f" || echo "❌ $f"
done
```

**Common pitfall found this way:** `\\'` (double backslash + single quote) inside a single-quoted JS string — `\\` is parsed as an escaped literal backslash, then `'` terminates the string, making everything after it invalid syntax. Fix: use `\'` (single backslash) for proper single-quote escaping.

See `references/js-module-syntax-error-debug.md` for full detailed procedure with hex dump technique.

### 6. CSS Rules Exist in Source But Don't Apply

When `getComputedStyle(el).property` shows `none` / `0px` but the CSS file on disk/server has the correct value:

1. **The rule may be trapped inside a `@media` query** due to a missing `}` earlier in the file. Traverse the CSSOM to find where the rule actually landed — see `references/debug-css-media-query-brace.md`.
2. Do NOT chase cache busters — the CSSOM is ground truth. If the rule is inside a non-matching `@media`, no amount of cache-busting will help.

## Test-harness state: localStorage persists across runs

- localStorage persists across browser_navigate calls
- Previous test sessions leave stale tokens/auth state
- Always `localStorage.clear()` before starting a fresh test sequence

## Phase 1: Root Cause Investigation

**BEFORE attempting ANY fix:**

### 1. Read Error Messages Carefully

- Don't skip past errors or warnings
- They often contain the exact solution
- Read stack traces completely
- Note line numbers, file paths, error codes

**Action:** Use `read_file` on the relevant source files. Use `search_files` to find the error string in the codebase.

### 2. Reproduce Consistently

- Can you trigger it reliably?
- What are the exact steps?
- Does it happen every time?
- If not reproducible → gather more data, don't guess

**Action:** Use the `terminal` tool to run the failing test or trigger the bug:

```bash
# Run specific failing test
pytest tests/test_module.py::test_name -v

# Run with verbose output
pytest tests/test_module.py -v --tb=long
```

#### ⚡ FastAPI 500: Reproduce Locally with TestClient

When Zeabur/cloud logs only show `500 Internal Server Error` with no Python traceback:

```python
from fastapi.testclient import TestClient
from main import app  # or wherever your FastAPI app is

client = TestClient(app)

# Use the live token/credentials
headers = {"Authorization": "Bearer <token>"}
r = client.post("/api/items/create", json={"name": "example"}, headers=headers)

# TestClient propagates the FULL Python exception, not just the HTTP 500
# This reveals NameError, ImportError, TypeError, etc. that clouds obscure
print(r.status_code)
if r.status_code != 200:
    print(r.text)  # ← Full traceback here
```

**Why it works:** `TestClient` runs the ASGI app in-process and propagates unhandled exceptions directly. The raw Python traceback appears in the response/console, bypassing Uvicorn's generic "Exception in ASGI application" message.

**Do this BEFORE instrumenting production code with `print()` — faster diagnosis. Only instrument production if the bug is environment-specific (cloud-only, DB state you can't replicate locally).**

### 3. Check Recent Changes

- What changed that could cause this?
- Git diff, recent commits
- New dependencies, config changes

**Action:**

```bash
# Recent commits
git log --oneline -10

# Uncommitted changes
git diff

# Changes in specific file
git log -p --follow src/problematic_file.py | head -100
```

### 4. Gather Evidence in Multi-Component Systems

**WHEN system has multiple components (API → service → database, CI → build → deploy):**

**BEFORE proposing fixes, add diagnostic instrumentation:**

For EACH component boundary:
- Log what data enters the component
- Log what data exits the component
- Verify environment/config propagation
- Check state at each layer

Run once to gather evidence showing WHERE it breaks.
THEN analyze evidence to identify the failing component.
THEN investigate that specific component.

### 4a. Backend 500 Without Detail — Instrument Before Guessing

When a FastAPI/backend endpoint returns HTTP 500 with no useful error detail:

**Don't:** Guess the cause by reading the code. Backend 500s in production often come from runtime conditions (DB state, concurrent locks, schema drift) that code review alone can't reveal.

**Do:** Add diagnostic logging around the suspected function:

```python
try:
    result = possibly_failing_function(...)
    log.info("[debug] function result: %r", result)      # ← server log only
except Exception:
    log.exception("[debug] function raised")             # ← full traceback in the log
    raise HTTPException(status_code=500, detail="internal error")  # ← generic to the client
```

This converts a silent 500 into a diagnosable one. The `log` lines go to the server's stdout/stderr (Zeabur Dashboard → Logs, Heroku logs, journald, etc.).

🔴 **不要把 traceback 放進 HTTP 回應的 `detail`**：那會把檔案路徑、SQL、內部主機名、甚至連線字串送給任何打得到這個端點的人（含未登入者）。
需要對外追蹤時，改回一個 request id，log 裡帶同一個 id，讓使用者回報 id 給你查。

**Critical:** After reading the error, **remove the diagnostic logging** or replace it with proper error handling. Don't leave `print()` debugging in production.

**Common backend 500 causes that diagnostics reveal:**
- `c.fetchone()[0]` — fetchone returned `None`, not a tuple (user has no record in a JOIN table)
- `dict[key]` where key doesn't exist (response format changed between endpoint versions)
- `sqlite3.OperationalError: database is locked` (concurrent write contention on SQLite)
- `TypeError: ... is not JSON serializable` (response contains a type FastAPI can't encode)
- `AttributeError: 'NoneType' object has no attribute 'something'` (a preceding call returned None)

### 5. Trace Data Flow

**WHEN error is deep in the call stack:**

- Where does the bad value originate?
- What called this function with the bad value?
- Keep tracing upstream until you find the source
- Fix at the source, not at the symptom

**Action:** Use `search_files` to trace references:

```python
# Find where the function is called
search_files("function_name(", path="src/", file_glob="*.py")

# Find where the variable is set
search_files("variable_name\\s*=", path="src/", file_glob="*.py")
```

### Phase 1 Completion Checklist

- [ ] Error messages fully read and understood
- [ ] Issue reproduced consistently
- [ ] Recent changes identified and reviewed
- [ ] Evidence gathered (logs, state, data flow)
- [ ] Problem isolated to specific component/code
- [ ] Root cause hypothesis formed

**STOP:** Do not proceed to Phase 2 until you understand WHY it's happening.

---

## Phase 2: Pattern Analysis

**Find the pattern before fixing:**

### 1. Find Working Examples

- Locate similar working code in the same codebase
- What works that's similar to what's broken?

**Action:** Use `search_files` to find comparable patterns:

```python
search_files("similar_pattern", path="src/", file_glob="*.py")
```

### 2. Compare Against References

- If implementing a pattern, read the reference implementation COMPLETELY
- Don't skim — read every line
- Understand the pattern fully before applying

### 3. Identify Differences

- What's different between working and broken?
- List every difference, however small
- Don't assume "that can't matter"

### 4. Understand Dependencies

- What other components does this need?
- What settings, config, environment?
- What assumptions does it make?

---

## Phase 3: Hypothesis and Testing

**Scientific method:**

### 1. Form a Single Hypothesis

- State clearly: "I think X is the root cause because Y"
- Write it down
- Be specific, not vague

### 2. Test Minimally

- Make the SMALLEST possible change to test the hypothesis
- One variable at a time
- Don't fix multiple things at once

### 3. Verify Before Continuing

- Did it work? → Phase 4
- Didn't work? → Form NEW hypothesis
- DON'T add more fixes on top

### 4. When You Don't Know

- Say "I don't understand X"
- Don't pretend to know
- Ask the user for help
- Research more

---

## Phase 4: Implementation

**Fix the root cause, not the symptom:**

### 1. Create Failing Test Case

- Simplest possible reproduction
- Automated test if possible
- MUST have before fixing
- Use the `test-driven-development` skill（上游 obra/superpowers 系列，本系列未收錄）

### 2. Implement Single Fix

- Address the root cause identified
- ONE change at a time
- No "while I'm here" improvements
- No bundled refactoring

### 3. Verify Fix

```bash
# Run the specific regression test
pytest tests/test_module.py::test_regression -v

# Run full suite — no regressions
pytest tests/ -q
```

### 4. If Fix Doesn't Work — The Rule of Three

- **STOP.**
- Count: How many fixes have you tried?
- If < 3: Return to Phase 1, re-analyze with new information
- **If ≥ 3: STOP and question the architecture (step 5 below)**
- DON'T attempt Fix #4 without architectural discussion

### 5. If 3+ Fixes Failed: Question Architecture

**Pattern indicating an architectural problem:**
- Each fix reveals new shared state/coupling in a different place
- Fixes require "massive refactoring" to implement
- Each fix creates new symptoms elsewhere

**STOP and question fundamentals:**
- Is this pattern fundamentally sound?
- Are we "sticking with it through sheer inertia"?
- Should we refactor the architecture vs. continue fixing symptoms?

**Discuss with the user before attempting more fixes.**

This is NOT a failed hypothesis — this is a wrong architecture.

### ⚠️ Exception: First-Run Cascade of a Ported Framework

**This rule has a CRITICAL exception:** When porting a monolith (8+ plugins) to a new framework for the VERY FIRST TIME, a cascade of 8–12 sequential crashes is NORMAL and EXPECTED. Each crash reveals a different API surface mismatch between old plugin code and new framework interfaces.

**How to tell the difference:**
- **Architectural failure (real red flag):** Each fix reveals deeper coupling in the SAME component. You keep editing the SAME file over and over.
- **First-run cascade (normal):** Each error is in a DIFFERENT file or a DIFFERENT category (async method, DB signature, ConfigManager, alias, etc.). You're working through a predictable checklist, not fighting architecture.

**When in first-run cascade mode:** Keep going. Once all 9 crash categories (see `references/multi-plugin-first-run-triage.md`) have been cleared, the cascade is done. Only THEN start to worry if bugs persist.

---

## Red Flags — STOP and Follow Process

If you catch yourself thinking:
- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "Add multiple changes, run tests"
- "Skip the test, I'll manually verify"
- "It's probably X, let me fix that"
- "I don't fully understand but this might work"
- "Pattern says X but I'll adapt it differently"
- "Here are the main problems: [lists fixes without investigation]"
- Proposing solutions before tracing data flow
- **"One more fix attempt" (when already tried 2+)**
- **Each fix reveals a new problem in a different place**

**ALL of these mean: STOP. Return to Phase 1.**

**If 3+ fixes failed:** Question the architecture (Phase 4 step 5).

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Issue is simple, don't need process" | Simple issues have root causes too. Process is fast for simple bugs. |
| "Emergency, no time for process" | Systematic debugging is FASTER than guess-and-check thrashing. |
| "Just try this first, then investigate" | First fix sets the pattern. Do it right from the start. |
| "I'll write test after confirming fix works" | Untested fixes don't stick. Test first proves it. |
| "Multiple fixes at once saves time" | Can't isolate what worked. Causes new bugs. |
| "Reference too long, I'll adapt the pattern" | Partial understanding guarantees bugs. Read it completely. |
| "I see the problem, let me fix it" | Seeing symptoms ≠ understanding root cause. |
| "One more fix attempt" (after 2+ failures) | 3+ failures = architectural problem. Question the pattern, don't fix again. |

## ⚠️ Don't Assume "User Didn't Restart" (When They Say They Did)

**Pitfall:** When a user reports your code fix isn't working after you made changes, the easiest (and wrong) hypothesis is "you need to restart the bot/server."

**What NOT to do:** Keep insisting the user restart when they've already confirmed they did. This wastes turns, frustrates the user, and delays finding the real bug.

**What TO do:**
- Accept their confirmation at face value: "你每次改完程式碼我就馬上重啟了" means the fix truly isn't working
- Look for the actual root cause: import timing, circular imports, handler registration order, different code path being hit, stale data in DB, etc.
- Add diagnostic logging if needed to trace the actual execution path
- Common sneaky causes:
  - **Import timing bug:** Module reads from `os.environ` at import time, but dotenv/`load_dotenv()` hasn't run yet → wrong value
  - **Handler priority:** Another handler (CommandHandler, CallbackQueryHandler, previous MessageHandler) catches the message before your interceptor
  - **Different code path:** The user's action triggers a completely different function than what you modified. Common example: a `ReplyKeyboardMarkup` button (appears above the keyboard) sends the button text as a regular TEXT message, which goes through the general `MessageHandler` → AI chat, NOT through the dedicated `CommandHandler` or `CallbackQueryHandler`. See `references/quick-intercept-handler-routing.md`.
  - **Stale data in DB:** Old conversation history with function tags contaminates future AI responses
  - **Incorrect route:** Keyboard button sends text through AI chat instead of the dedicated handler. Fix: add a `quick_intercept` check for the exact button text (`if "一鍵拍照" in user_text`) and call the dedicated handler directly. The intercept runs before AI processing, so the dedicated handler takes over cleanly.

## ⚠️ AI Self-Reinforcing Loop: Function Tags in Conversation History

**Symptom:** The AI keeps outputting the same function tag (`[SEARCH: ...]`, `[RENDER: ...]`, etc.) in every response, even when the user didn't ask for it. The behavior persists across restarts.

**Root Cause:** The AI's raw response (including function tags like `[SEARCH: <query>]`) is saved directly to the conversation history database. On the next turn, the AI sees its own tagged response in the history and thinks it should output the same tag again → **self-reinforcing loop**.

```
Turn 1: AI outputs "[RENDER:...] [SEARCH:<query>] 好的～"
         ↓  saved to history with tags
Turn 2: AI sees history → copies the pattern → outputs tags again
         ↓  saved again with tags
Turn N: Infinite loop 🔄
```

**Fix:** Strip function tags from the AI response BEFORE saving to conversation history:

```python
clean_for_history = re.sub(
    r'\[(?:RENDER|DARKRENDER|SEARCH_\w+|EXPENSE|INCOME|WEATHER|VIDEO...):.*?\]',
    '', ai_reply, flags=re.IGNORECASE | re.DOTALL
).strip()
await save_message(user_id, chat_id, "assistant", clean_for_history, ...)
```

**Diagnostic steps:**
1. Check if `ai_reply` (raw response) is saved to history vs `clean_text` (processed, tag-free)
2. Look for `save_message(user_id, chat_id, "assistant", ai_reply, ...)` in the chat handler
3. Check if the history includes function tags by reading the DB directly

**⚠️ This also affects other features:**
- "一鍵拍照" buttons that route through AI chat instead of a dedicated handler
- Any tag the AI can output (WEATHER, DRAW, VIDEO, NOTE, REMIND, etc.)

## ⚠️ Context Compaction Claims Are NOT Verified Facts

**Problem:** Context compaction summaries (written by previous agent instances across context windows) can contain claims that sound definitive but were never actually verified.

**Example:** A compaction summary asserted "video generation succeeded" — but investigation showed NO video files were saved to disk. The "success" was an optimistic reading of an intermediate API result, not an end-to-end confirmed save.

**Rule:** Treat any claim in a context compaction that describes a concrete result ("成功", "完成", "已修復", "運作正常", "部署成功") as **unverified until proven otherwise**. Specifically:

- **"File/result saved"** → `stat` or `ls` the claimed path
- **"DB record inserted/updated/deleted"** → `sqlite3 ... "SELECT * FROM table WHERE ..."` to confirm the row exists. **Compaction frequently fabricates SQL INSERTs that were never executed** — always SELECT to verify.
- **"API works"** → run a live test or check logs
- **"Deployed"** → `curl` the deployed file and grep for your fix
- **"Running"** → `ps` / Get-Process to confirm PID exists
- **"Bug fixed"** → read the actual source and check the fix is present

**🔴 Critical DB pattern:** Compaction summaries frequently claim successful SQL INSERT/UPDATE/DELETE operations that were never actually executed. The compaction agent writes the INSERT into the summary as a "completed action" during context window closure, but the SQL was either never sent to the DB or targeted the wrong database file. The only way to catch this is to **actually SELECT the data** in the current session — don't trust what a previous context window claimed it did to the database.

**This is NOT optional** — context compaction is lossy and written by an agent that may not have verified its own conclusions.

---

## ⚠️ Common Pitfall: Two Components Reading Different Data Sources

**Scenario:** User reports that data set via Tool A (admin panel, tendency panel, etc.) doesn't show up when using Tool B (bot, API, etc.). User sees stale/wrong values.

**Root Cause:** Tool A and Tool B read/write different files or database tables. Common in evolving codebases where:
- The bot writes to `user_stats.json` but the admin panel writes to `user_stats_{INSTANCE}.json`
- One module uses SQLite `chat_history.db` while another uses a different DB file
- Hardcoded paths diverge after refactoring

**Diagnosis — always check data source first:**

```bash
# 1. Find ALL file paths used by each component
grep -rn "open(" --include="*.py" component_a/ | grep -E "\.json|\.db"
grep -rn "open(" --include="*.py" component_b/ | grep -E "\.json|\.db"

# 2. Trace the actual file path at runtime
grep -rn "_get_stats_file\|STATS_FILE\|_STATS_FILE\|DB_PATH" --include="*.py" .

# 3. Compare — are they the same absolute path?
ls -la /path/to/possible/files*
```

**Fix:** Unify the data source. If the instances were deprecated (e.g., dual-bot unified to single), change the diverged component to use the same path as the main component.

**Prevention:** When refactoring multi-instance to single-instance, search for ALL file path references:
```bash
grep -rn "user_stats\|_stats_file\|STATS_FILE" --include="*.py" .
```
Every `_<instance>` suffix (e.g. `_box_a` / `_box_b`) must be removed from file paths AND from data lookup keys (e.g., `"openai"` not `"box_a"`).

## ⚠️ Common Pitfall: Misreading Stack Traces

A recurring mistake: **reading the error message but not the stack trace accurately.**

### The "Position 22-24" Lesson

**Scenario:** `POST /api/files/attach` returns 500 with:

```
'latin-1' codec can't encode characters in position 22-24: ordinal not in range(256)
```

❌ **Wrong approach (what happened):**
- Assumed it was a Pillow/PngInfo encoding bug
- Tried switching to manual binary chunk injection
- Then suspected FastAPI `Response()` encoding
- Then suspected GitHub deploy failure
- Three different fixes, all wrong, wasted hours

✅ **Correct approach:**
1. **Count the positions in the error message.** Position 22-24 = 3 characters.
2. In `Content-Disposition: attachment; filename="附件一_bot.png"`, `attachment; filename="` is exactly 22 characters → positions 22-24 are `附件一`
3. **HTTP Headers only support ISO-8859-1 (Latin-1).** Chinese characters in header values will always fail.
4. Fix: Use RFC 6266 `filename*=utf-8''` encoding.

### The Lesson

**Always calculate the exact byte positions in the error message before hypothesizing the cause.** One minute of counting can save hours of misguided debugging.

**Don't let the surface context (PNG, Pillow, tEXt chunks) distract you from the actual location in the stack trace.** The error pointed at `latin-1` encoding — if it was a Pillow internal error, the traceback would reference Pillow's code, not the Uvicorn/Starlette HTTP layer.

### Debug Checklist for "latin-1" or Encoding Errors
1. [ ] Is this in a **file write** operation? → File system encoding issue.
2. [ ] Is this in an **HTTP header**? → Header values must be ASCII or RFC 5987 encoded.
3. [ ] Is this in a **database connection**? → Connection charset/encoding config.
4. [ ] Where exactly in the code does the stack trace point? (Calculate positions match.)

### Additional Learning: Verify Your Deploy

When the same error persists after a "fix":
1. **Check if the code was actually deployed.** Use curl to fetch the raw file from the deployment environment and grep for your fix string.
2. **Check if GitHub raw content is stale** (CDN cache can lag).
3. **Force re-deploy** with an empty commit if needed: `git commit --allow-empty -m "chore: force redeploy"`
4. **Don't assume the deploy is working.** Verify at the byte level.

### 🔄 The "DESC + reversed + [:N]" Slice Bug

A recurring class of bug: `ORDER BY timestamp DESC LIMIT N` → `reversed()` → `[:M]` gets the **oldest** M records, not the newest.

See `references/desc-slice-direction-bug.md` for diagnosis checklist and fix.

### ★ Quick Reference

| Phase | Key Activities | Success Criteria |
|-------|---------------|------------------|
| **1. Root Cause** | Read errors, reproduce, check changes, gather evidence, trace data flow | Understand WHAT and WHY |
| **2. Pattern** | Find working examples, compare, identify differences | Know what's different |
| **3. Hypothesis** | Form theory, test minimally, one variable at a time | Confirmed or new hypothesis |
| **4. Implementation** | Create regression test, fix root cause, verify | Bug resolved, all tests pass |

### References

| File | Description |
|------|-------------|
| [bypass-shared-save-function-pattern.md](references/bypass-shared-save-function-pattern.md) | Raw json.dump bypassing shared save functions |
| [class-level-cache-pollution.md](references/class-level-cache-pollution.md) | Class-level dict cache polluting pytest-asyncio fixtures |
| [computed-but-not-persisted.md](references/computed-but-not-persisted.md) | State modified in-memory but never saved to file/DB (common scheduled-job bug) |
| [debug-css-media-query-brace.md](references/debug-css-media-query-brace.md) | CSS @media brace trap debug |
| [desc-slice-direction-bug.md](references/desc-slice-direction-bug.md) | DESC + reversed + [:N] slice direction bug |
| [fastapi-path-param-ordering.md](references/fastapi-path-param-ordering.md) | FastAPI route ordering: path-param route shadowing a specific static route |
| [js-module-syntax-error-debug.md](references/js-module-syntax-error-debug.md) | JS module SyntaxError import chain trap |
| [lazy-init-env-path-pattern.md](references/lazy-init-env-path-pattern.md) | Lazy init / env path pattern |
| [multi-plugin-first-run-triage.md](references/multi-plugin-first-run-triage.md) | Multi-plugin framework first-run crash triage (6 predictable patterns: async on_load, APScheduler event loop, job context param, ConfigManager .env, DB signature, f-string multiline) |
| [quick-intercept-handler-routing.md](references/quick-intercept-handler-routing.md) | Quick intercept handler routing |
| [keyword-detection-false-positive-chinese.md](references/keyword-detection-false-positive-chinese.md) | Chinese keyword false positive debugging |
| [telegram-bot-command-handler-debug.md](references/telegram-bot-command-handler-debug.md) | Telegram Bot command not firing |
| [porting-model-name-check.md](references/porting-model-name-check.md) | Porting: read model names from old codebase, don't guess |
| [qdrant-client-api-migration.md](references/qdrant-client-api-migration.md) | qdrant-client 1.12+ API changes |

## 📋 Design Documentation: Placeholder Naming

**Pitfall:** Using industry-specific abbreviations as generic placeholders in design documents. Example: "EC 網站" in Taiwan means 綠界科技 (ECPay), not "E-Commerce".

**Rule:** Use unambiguous names for future projects:
- ❌ "EC 網站"
- ✅ "會員中心（未來專案）" / "官網（尚未存在）"

**If you must use a shorthand, define it on first use with a footnote.**

## Hermes Agent Integration

### Investigation Tools

Use these Hermes tools during Phase 1:

- **`search_files`** — Find error strings, trace function calls, locate patterns
- **`read_file`** — Read source code with line numbers for precise analysis
- **`terminal`** — Run tests, check git history, reproduce bugs
- **`web_search`/`web_extract`** — Research error messages, library docs

### With delegate_task

For complex multi-component debugging, dispatch investigation subagents:

```python
delegate_task(
    goal="Investigate why [specific test/behavior] fails",
    context="""
    Follow systematic-debugging skill:
    1. Read the error message carefully
    2. Reproduce the issue
    3. Trace the data flow to find root cause
    4. Report findings — do NOT fix yet

    Error: [paste full error]
    File: [path to failing code]
    Test command: [exact command]
    """,
    toolsets=['terminal', 'file']
)
```

### With test-driven-development

When fixing bugs:
1. Write a test that reproduces the bug (RED)
2. Debug systematically to find root cause
3. Fix the root cause (GREEN)
4. The test proves the fix and prevents regression

### ⚠️ Inline Import Trap: Replacing Code That Contains `import`

**Scenario:** You replace a block of code that contains an inline `import` statement (e.g., `import time` inside a function body). Your replacement code calls `time.strftime()`. The inline `import` was in the OLD block that got removed → `NameError: name 'time' is not defined`.

**Root cause:** Many Python functions use inline imports (inside the function body, not at module level) to avoid circular imports or for lazy loading. When you `patch()` out a block containing `import X`, and the replacement also uses `X`, the import is lost.

**Prevention:**
```python
# ❌ WRONG — patch removes the old block containing `import time`
# New block uses time.strftime() but time is no longer imported

# ✅ RIGHT — before patching, check what imports exist in the function
# 1. Search for inline imports in the function:
grep -n "import " FILE.py | head -20
# 2. If the code being removed contains an import, add it to the replacement block
# 3. Or add it at the top of the function
```

**Checklist when replacing a code block:**
- [ ] Does the REMOVED block contain `import X` statements?
- [ ] Does the NEW block use any of those `X` modules?
- [ ] If yes, add `import X` at the top of the function or in the new block
- [ ] Run syntax check after: `python -c "import py_compile; py_compile.compile('file.py', doraise=True)"`
- [ ] Better yet, test the actual code path if possible

### ⚠️ Wrong-Module Import: silent `ImportError` inside a broad `try/except`

**Scenario:** A function call works when called from one module but fails with `ImportError` from another. Both code paths look identical.

**Pattern:** `from myapp.handlers.storage import _save_stats` — `storage.py` doesn't HAVE `_save_stats`. It's in `persona.py`.

**Why it happens:** Developer remembers "there's a save function" and guesses the module. The import is buried in a `try/except` block that catches all exceptions → the error is silently swallowed → feature silently fails forever.

**Diagnosis:**
```bash
grep -rn "def _save_stats" --include="*.py" .  # Find where it's ACTUALLY defined
grep -rn "_save_stats" --include="*.py" .      # Find ALL import sites
```

**Fix:** Always `grep` for the function definition before importing it. Import from the file that DEFINES it, not the file that sounds like it should have it.

### ⚠️ LLM-Generated JSON Repair Pattern

**Scenario:** LLM returns a JSON string that fails `json.loads()` with `Unterminated string` or `Expecting ',' delimiter`. Common causes:
1. String values contain raw newlines (control characters)
2. Last string value not closed with `"`
3. Missing closing `}` brace
4. Trailing comma before `}`

**Repair strategy (in order):**
```python
try:
    return json.loads(text)
except json.JSONDecodeError:
    # Phase 1: Replace control chars inside strings with spaces
    in_str = False
    chars = []
    for ch in text:
        if ch == '"' and (not chars or chars[-1] != '\\'):
            in_str = not in_str
        if in_str and ord(ch) < 32 and ch not in ('\t',):
            chars.append(' ')
        else:
            chars.append(ch)
    text = ''.join(chars)
    
    # Phase 2: Fix unclosed quotes and missing closing brace
    text = text.strip()
    if text.count('"') % 2 == 1:
        text += '"'
    if not text.endswith('}'):
        text += '}'
    text = re.sub(r',(\s*)}', r'\1}', text)  # Remove trailing commas
    
    return json.loads(text)
```

**When to use:** Any time an LLM generates JSON and the first parse fails. This covers ~90% of JSON formatting errors from models like DeepSeek V4 Flash.

**Most common fix-completion mistake:** Finding a bug, fixing the ONE code path that produced the error, and declaring done. If the bug involves a hardcoded value (user_id, localStorage key, API path, function name), **it almost certainly exists in other files too.**

**Example:** `admin_user_001` hardcoded user ID — recurred 3+ times because each fix only patched the one endpoint that errored out, not all 6+ appearances across the project.

**Always do before closing:**
```bash
grep -rn "THE_HARDCODED_VALUE" --include="*.py" --include="*.js" .
# Verify EVERY match — not just the one you found
```

Apply this to any: function names after rename, localStorage keys, user_ids, API paths, DB column names, hardcoded UUIDs.

### 🔴 Extended: When the Fix Changes a Shared Data Structure

If the fix involves changing a **shared function, data structure, or file format** (e.g., modifying a PreferenceManager's internal schema, renaming a config key, changing a save function's contract):

**Do NOT stop after fixing the one code path that errored.**

The modified structure likely has call sites spread across multiple modules. Each wild import (`from config import *`) or global reference (`PREF.data`, `_prefs.data.get("old_key")`) is a potential silent failure — it won't crash, it'll just return empty/default data forever.

**Mandatory post-fix sweep:**
```bash
# 1. Find ALL references to the changed function/variable
grep -rn "THE_CHANGED_FUNCTION\|THE_CHANGED_VARIABLE\|\.data\.get\|\.data\[" --include="*.py" .

# 2. For EACH match, verify it's compatible with the new structure
#    - Does it access a key that still exists?
#    - Does it call a method with the right signature?
#    - Does it import from the correct module?

# 3. Update project documentation with the schema change
```

**Common silent-failure patterns:**
- `_prefs.data.get("tags", [])` — after v2.1 upgrade, `data` is now `{"core_tags": {...}}` not `{"tags": [...]}`
- `PREF.data["last_updated"]` — key renamed or moved to nested structure
- `from old_module import save_func` — function moved to a different module

**Golden rule:** If the old code accessed `data.key` or `data["key"]`, the new code must too — just through the correct method (`get_structured()`, `get_formatted()`, etc.) rather than directly accessing internal state.

### 🔴 The Chain of Masked Bugs — When the Surface Bug Is Not the Root

**Scenario:** A feature has been silently broken for months. Users don't notice because nothing crashes. The only visible symptom is a minor oddity (e.g., "週記憶摘要 never works") that's easy to dismiss.

**Root cause pattern:** Exception handlers in the DATA FLOW CHAIN silently swallow errors at each layer, masking the real problem deep below the surface. Each layer thinks "it's not my fault, I handled it" — but "handling" means silently returning empty/default.

```python
# Layer 1 (deepest): External API returns 404
#   → except: return []     ← says "no data" instead of "API failed"
#
# Layer 2: Got empty data from Layer 1
#   → if not data: return False    ← says "nothing to save" instead of "can't embed"
#
# Layer 3: Got False from Layer 2, does nothing
#   → no log, no alert, just skips   ← says "everything fine"
#
# Layer 4: Reads from DB, finds nothing
#   → scroll() fails because it never expected 0 records
#   → THIS is the only visible error — 3 layers deep from the real cause
```

**Real example (vector memory system):**

```
text-embedding-004 被 Google 下架（回傳 404）
  → get_embedding() except: return []（靜默吃掉錯誤）
    → save_memory() if not vector: return False（靜默丟棄記憶）
      → Qdrant 2 個月 points_count=0，無任何資料
        → weekly_memory_summary scroll() 因 timestamp 無 index 噴 UnexpectedResponse()
          ↑ 這是最後一層的唯一可見症狀
```

同時 qdrant.search() 在 qdrant-client 1.17.1 已不存在（改名 query_points），但因為 embedding 先掛了，這行從未被執行到——**被遮蔽的 bug 藏了 2 個月**。

**Diagnostic technique — trace the FULL data flow chain:**

When debugging a long-broken silent failure:
1. **Start at the symptom** and work BACKWARDS through every layer
2. For EACH layer, check what happens when the previous layer Fails vs Returns Empty vs Returns Error
3. **Search for `except: return` patterns** — these are the silent error swallowers
4. **Add diagnostic logging** at each layer boundary before fixing anything:

```python
# Temporary diagnostic — log what's really happening at each boundary
vector = await get_embedding(text)
logger.info(f"[diag] get_embedding returned: vector={len(vector) if vector else 'EMPTY'}")
if not vector:
    logger.warning("[diag] SKIPPING save_memory because embedding failed!")
    return False
```

5. **Fix from the inside out** — fix the deepest layer first (API model dead → switch to working model), then verify each subsequent layer recovers naturally.

**Common silent-failure patterns to watch for:**

| Pattern | Example | Danger |
|:--|:--|:--|
| `except: return []` | API call fails → empty list | Downstream sees "no data" not "API broken" |
| `except: pass` | Any error → silently ignored | All trace lost |
| `if not result: return False` | Empty result treated as "nothing" | Can't distinguish "genuinely nothing" from "failed to check" |
| `asyncio.create_task(fn())` | Fire-and-forget with no error handler | Crashes go to event loop, not user |

**Golden rule:** When a feature that SHOULD work has been broken for months, the surface bug is NEVER the root cause. Trace the full data flow chain. The real bug is being silently eaten by a `except: return []` three layers deep.

### 🔴 Post-Refactor: The `if module_var:` Trap (Silent Skip)

**Scenario**: You refactor a module-level cached client (e.g., `xai_client`) so OAuth mode no longer sets the global variable — it now returns a fresh client from `async def get_client()`. All call sites that previously checked `if xai_client:` become silent no-ops.

```python
# OLD code: xai_client is always set (API Key mode cached forever)
# NEW code: xai_client stays None in OAuth mode (fresh client per call)

# ❌ Silent failure — module_var is None, branch never taken
if xai_client:
    resp = await xai_client.chat.completions.create(...)
    # This branch is NEVER reached after refactor

# ✅ Correct — call the factory function
client = await ensure_xai_client()
if client:
    resp = await client.chat.completions.create(...)
```

**Diagnosis**: The log shows no errors, but Grok-powered features (push notifications, search rewrite, proactive messages) silently use fallback or return empty. No 403 or timeout — just never using Grok.

**Post-fix sweep command**:
```bash
# After refactoring a module-level cached variable:
grep -rn "if xai_client\|if deepseek_client\|if gemini_client\b" --include="*.py" .
```
For each match, verify the call site uses the factory function's return value, not the module-level variable.

This applies to ANY module-level cached resource, not just API clients:
- `if db_connection:` → should use `get_connection()`
- `if config_loaded:` → should check `ensure_config()`
- `if cached_model:` → should call `load_model()`

See `references/bypass-shared-save-function-pattern.md` for the specific pattern of raw json.dump bypassing shared save functions.

## Real-World Impact

Observations from debugging sessions (qualitative — not a controlled measurement):

- Systematic investigation tends to converge in minutes; guess-and-check thrashes for hours and often ends with several wrong fixes stacked on each other.
- The most expensive failures we hit were not "hard bugs" but **wrong hypotheses that looked plausible**: three successive fixes for a PNG-injection theory while the error was actually an HTTP-header encoding limit.
- Bugs "fixed" without a reproduction tend to come back, sometimes in a different component (see *Chain of Masked Bugs* above).

**No shortcuts. No guessing. Systematic always wins.**
