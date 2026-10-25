# Computed But Not Persisted Pattern

## Symptom

A scheduled job or background function runs, produces log output with correct values (e.g., "decay: -5"), but the actual persistent state doesn't change.

## Root Cause

The function calls a state-modifying utility (e.g., `_decay_state(bot_data)`, `apply_cooldown(bot_data)`) which modifies a Python dict in-memory, but the caller **never writes the modified dict back to the file/DB**.

The classic code pattern:

```python
def my_job():
    stats = _load_stats()                    # ← 1. Load
    for uid, user_data in stats.items():
        bot_data = user_data["gemini"]
        bot_data = _decay_state(bot_data)    # ← 2. Modify (correct)
        if some_condition:
            continue                         # ← 3. Skip save! ❌
        triggered.append(...)
    if triggered:
        _save_stats(stats)                   # ← 4. Only save on triggered path
```

## Why It's Easy to Miss

- The log inside `_decay_state` correctly shows the computed value
- The function appears to work (no errors)
- The bug only manifests as "state doesn't change over time"
- Scheduled jobs run silently — no user sees the intermediate state
- **Two variants exist:**
  - **Variant A (loop-level):** `continue` / `return` inside the loop skips save for specific users (covered below)
  - **Variant B (function-level):** Final `_save_stats` is guarded by `if triggered:` / `if changed:` — when no user triggers, ALL users' computed state is lost, even users whose `continue` paths DID write to the in-memory dict

## Diagnosis Checklist

When you suspect a computed-but-not-persisted bug:

- [ ] Trace ALL callers of the state-modifying function
- [ ] For each caller, verify the modified dict is written back
- [ ] Check: is `_save_stats()` / `db.commit()` / `file.write()` called?
- [ ] Check: is the save guarded by a condition that might be false?
- [ ] Check: does `continue` / `return` / `break` skip the save?
- [ ] Check: does the save happen in a different function than the modification?
- [ ] Put a log statement AFTER the save to verify persistence

## Worked Example

A background job ran on a fixed tick (every 5 minutes) and called `_decay_state()` for every record.
The loop correctly updated in-memory state for ALL records. But the final save was:

```python
# ❌ Before: only save on trigger
if triggered:
    _save_stats(stats)

return triggered
```

When no record crossed the alert threshold, `triggered` was empty → `_save_stats` never ran → **every record's decay result (including derived counters and `last_state_update`) was discarded**.

This was especially insidious because:

- Records that hit the `continue` branch had still assigned `user_data[bot_type] = state` — the in-memory dict WAS correctly updated
- The log showed correct decay values
- But the final `if triggered:` gate threw it all away
- In practice the value only ever decayed when a user sent a message (that path called `update_state()`, which saved at its end)

**Fix:**

```python
# ✅ After: unconditional save
_save_stats(stats)
return triggered
```

The 5-minute write frequency is acceptable for this data size (< 1MB, < 1000 records).

Variant A (loop-level skip) looks like this — the fix is to save after EVERY modification path,
not just the "happy path":

```python
if not active:
    user_data["counter"] = state   # ← Save first
    stats[uid] = user_data         # ← Save first
    continue

if value < THRESHOLD:
    user_data["counter"] = state   # ← Save first
    stats[uid] = user_data         # ← Save first
    continue
```

## Prevention

When writing a function that:
1. Loads state from file/DB
2. Calls a state-modifying utility function
3. Has conditional branches (if/else, continue, return, break)

**Verify every code path SAVES the modified state before exiting the function.**
