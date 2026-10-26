# 修完之後的清查：inline import、錯模組 import、LLM JSON 修補（本 repo 案例筆記）

> 本檔是 `systematic-debugging` 的案例筆記（原創），主文的方法論見 SKILL.md。

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

See `bypass-shared-save-function-pattern.md` for the specific pattern of raw json.dump bypassing shared save functions.
