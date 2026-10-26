---
name: systematic-debugging
description: "Use when a bug or test fails — root cause before any fix."
version: 1.2.0
author: Jesse Vincent (obra/superpowers) — original method; Drizzt Studio — case notes
license: MIT
metadata:
  hermes:
    tags: [debugging, troubleshooting, problem-solving, root-cause, investigation]
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

📎 **先分流**：如果是「頁面一片空白」「改了程式碼卻沒生效」這類前端／Web 問題，先過一遍 `references/frontend-web-quick-wins.md`（console、快取、`display:none`、PWA、CSSOM）——那幾項佔了這類回報的大部分。

## The Four Phases

You MUST complete each phase before proceeding to the next.

---

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

📎 **雲端只回 500、沒有 traceback**：`references/python-backend-500.md`（TestClient 在本機把完整例外逼出來，比在 production 加 print 快）。

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

📎 **A 寫的資料 B 讀不到**（面板改的東西 bot 看不到）：`references/divergent-data-sources.md` —— 先確認兩邊是不是讀同一個檔／表。

📎 **錯誤訊息裡的 byte 位置怎麼算**（`latin-1` 那種）：`references/misread-stack-traces.md`。

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
- 先用一個會失敗的測試把 bug 固定住（見〈With a failing test first〉）

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

📎 三個「明明修好了卻還是壞」的已知陷阱：`references/restart-and-handler-routing.md`（按鈕走錯 handler）、
`references/function-tag-loop.md`（AI 把自己輸出的 tag 抄回歷史）、`references/context-compaction-claims.md`（摘要聲稱的完成未必存在）。

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

📎 **修完之後**：同一種錯通常還有別處 —— `references/post-fix-sweeps-and-masked-bugs.md`（含被 `except: return []` 吃掉的整條資料流）。

### ★ Quick Reference

| Phase | Key Activities | Success Criteria |
|-------|---------------|------------------|
| **1. Root Cause** | Read errors, reproduce, check changes, gather evidence, trace data flow | Understand WHAT and WHY |
| **2. Pattern** | Find working examples, compare, identify differences | Know what's different |
| **3. Hypothesis** | Form theory, test minimally, one variable at a time | Confirmed or new hypothesis |
| **4. Implementation** | Create regression test, fix root cause, verify | Bug resolved, all tests pass |

### References（全部案例筆記一覽）

> 上面四個 Phase 的方法論來自上游 `obra/superpowers`（MIT, Jesse Vincent）；**下面這些是本 skill 的原創踩坑筆記**，
> 需要時再讀，不佔主文篇幅。

| File | Description |
|------|-------------|
| [frontend-web-quick-wins.md](references/frontend-web-quick-wins.md) | 前端／Web bug 快篩：console、快取、`display:none`、PWA、CSSOM |
| [python-backend-500.md](references/python-backend-500.md) | 雲端只有 500：TestClient 取證、儀器化順序 |
| [restart-and-handler-routing.md](references/restart-and-handler-routing.md) | 「使用者說重啟了」與按鈕走錯 handler |
| [function-tag-loop.md](references/function-tag-loop.md) | AI 把自己輸出的 function tag 抄回歷史的自我強化迴圈 |
| [context-compaction-claims.md](references/context-compaction-claims.md) | 壓縮摘要裡的「已完成／已部署」怎麼驗 |
| [divergent-data-sources.md](references/divergent-data-sources.md) | A 寫的資料 B 讀不到（讀不同檔／表） |
| [misread-stack-traces.md](references/misread-stack-traces.md) | 誤讀 stack trace：`latin-1` 位置、header 編碼、部署驗證 |
| [post-fix-sweeps-and-masked-bugs.md](references/post-fix-sweeps-and-masked-bugs.md) | 修完後的清查：inline import、錯模組 import、LLM JSON 修補、被 `except: return []` 吃掉的鏈 |
| [design-doc-placeholders.md](references/design-doc-placeholders.md) | 設計文件的縮寫命名陷阱 |
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

### With a failing test first

When fixing bugs:
1. Write a test that reproduces the bug (RED)
2. Debug systematically to find root cause
3. Fix the root cause (GREEN)
4. The test proves the fix and prevents regression

（上游把它拆成獨立的 `test-driven-development` skill；本系列未收錄，上面四步自己照做即可。）

## Real-World Impact

Observations from debugging sessions (qualitative — not a controlled measurement):

- Systematic investigation tends to converge in minutes; guess-and-check thrashes for hours and often ends with several wrong fixes stacked on each other.
- The most expensive failures we hit were not "hard bugs" but **wrong hypotheses that looked plausible**: three successive fixes for a PNG-injection theory while the error was actually an HTTP-header encoding limit.
- Bugs "fixed" without a reproduction tend to come back, sometimes in a different component (see *Chain of Masked Bugs* above).

**No shortcuts. No guessing. Systematic always wins.**
