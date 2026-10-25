# Bypassing Shared Save Function — Debugging Pattern

## Scenario

A shared JSON/database file gets silently corrupted. Other users' data disappears. Fixed values keep resetting to defaults.

## Root Cause Pattern

Some code path writes directly to the file using `json.dump(data, f)` instead of calling the project's shared `_save_stats()` or equivalent wrapper function.

The direct dump often writes the **wrong level of data**:
- The shared file expects `{"user_id": {data}}` (wrapped by user key)
- The buggy code writes `{data}` (without the user key wrapper)
- Next read: lookup key not found → initialize default → **data loss**

## Diagnosis Checklist

```bash
# 1. Find ALL writers to the file
grep -rn "user_stats\.json\|stats\.json" --include="*.py" .

# 2. Find ALL json.dump calls near that file path  
grep -rn "json\.dump.*stats\|json\.dump.*_ud" --include="*.py" .

# 3. Compare each writer: does it use the shared save function?
grep -n "_save_stats\|save_full" --include="*.py" .
```

## Specific Pattern to Look For

```python
# ❌ WRONG — writes single user's inner dict, no user_id wrapper
_ud = get_user_stats(user_id)  # returns {"nickname": "...", "gemini": {...}}
# ... modify _ud ...
json.dump(_ud, f)  # File becomes {"nickname": "..."} instead of {"<chat_id>": {...}}

# ✅ CORRECT — uses shared save with full structure
stats = _load_stats()
stats[user_id] = _ud
_save_stats(stats)
```

## Fix Principle

**Every write to a shared data file must use the project's dedicated save function, never raw `json.dump()`.**

The dedicated function knows:
- The correct file wrapper structure (user_id keys, version fields)
- Atomic write patterns (write to temp, rename)
- Backup/rollback mechanisms
- Locking (if applicable)

## Prevention

When reviewing any PR that writes to JSON/SQLite:
1. Search for `json.dump` near the project's data directory path
2. Verify all writes go through `_save_stats` / `save_full` / equivalent
3. The wrapper function is the single source of truth for the file format
