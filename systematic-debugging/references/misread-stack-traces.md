# 誤讀 stack trace 的代價與正確量法（本 repo 案例筆記）

> 本檔是 `systematic-debugging` 的案例筆記（原創），主文的方法論見 SKILL.md。

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

See `desc-slice-direction-bug.md` for diagnosis checklist and fix.
