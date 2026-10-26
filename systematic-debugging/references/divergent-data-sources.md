# 兩個元件讀不同資料源（本 repo 案例筆記）

> 本檔是 `systematic-debugging` 的案例筆記（原創），主文的方法論見 SKILL.md。

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
