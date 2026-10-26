# Multi-Plugin Framework First-Run Triage

## Overview

When starting a multi-plugin framework for the **very first time** (e.g., a 13-plugin bot framework), the first startup attempt rarely succeeds. The crash sequence follows a **predictable pattern** — knowing it cuts diagnosis time from hours to minutes.

## The 6 Most Common First-Run Crashes (In Order)

### 1. Coroutine `on_load()` Not Awaited

**Symptom:** `RuntimeWarning: coroutine 'FooPlugin.on_load' was never awaited`

**Root cause:** Plugin manager calls `plugin.on_load()` synchronously, but the method is `async def`.

**Fix:**

```python
if asyncio.iscoroutinefunction(plugin.on_load):
    loop = asyncio.get_event_loop()
    if loop.is_running():
        asyncio.ensure_future(plugin.on_load())
    else:
        loop.run_until_complete(plugin.on_load())
else:
    plugin.on_load()
```

**Checklist:** Search ALL plugins for `async def on_load` — every one needs this fix.

### 2. APScheduler "no running event loop"

**Symptom:** `RuntimeError: no running event loop` during scheduler startup.

**Root cause:** `AsyncIOScheduler.start()` calls `asyncio.get_running_loop()` but the event loop was just created via `new_event_loop()` + `set_event_loop()`, not yet running.

**Fix:** Pass the event loop to APScheduler explicitly:

```python
# In the scheduler class:
def set_event_loop(self, loop):
    self._scheduler = AsyncIOScheduler(event_loop=loop)

# In bot.run():
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
self.scheduler.set_event_loop(loop)  # ← must be before .start()
```

### 3. Cron Job Functions with PTB `context` Parameter

**Symptom:** `ValueError: The following arguments have not been supplied: context`

**Root cause:** Job functions have `context: ContextTypes.DEFAULT_TYPE` parameter intended for PTB callbacks, but APScheduler doesn't pass it.

**Fix:** Remove the `context` parameter from all job functions. Use `self.context.bot` instead of `context.bot`:

```python
# Wrong (will crash):
async def night_diary_job(self, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(...)

# Correct:
async def night_diary_job(self):  # APScheduler 不傳 context
    await self.context.bot.send_message(...)
```

**Checklist:** Search ALL plugins for `.scheduler.cron(` and `.scheduler.interval(`, then check each callback function for `context` parameter.

### 4. ConfigManager Doesn't Read .env Variables

**Symptom:** `WARNING: 未設定任何 AI API Key` despite `.env` having valid keys.

**Root cause:** `load_dotenv()` loads into `os.environ`, but `ConfigManager` only reads `APP_CORE__`-prefixed env vars. Bare names like `DEEPSEEK_API_KEY` are invisible to config.

**Fix:** Add `os.getenv()` fallback at each API key read site:

```python
deepseek_key = (self._config.get("deepseek_api_key")
                or self._config.get("DEEPSEEK_API_KEY")
                or os.getenv("DEEPSEEK_API_KEY"))
```

**Broader pattern:** Any code that reads config from `.env` needs to check BOTH `config.get()` AND `os.getenv()`.

### 5. Database Interface Name/Signature Mismatch

**Two variants:**

- **Method name mismatch:** Plugin calls `db.fetchone()` but framework has `db.fetch_one()` (with underscore)
- **Parameter order mismatch:** Plugin calls `db.execute(sql, params)` but framework has `db.execute(pkg, sql, params)`

**Root cause:** Plugins were written against a different DB API than the framework provides. Common when porting from a monolith to a framework.

**Fix:**
- Fix the plugin call sites to the framework's real API (`fetch_one`, `execute_ns`, …) — this is the fix that survives the next refactor
- 若短期無法改所有 call site，可加**過渡期 adapter**：名稱一樣，但內部只呼叫正式 API，並 `warnings.warn(..., DeprecationWarning)`，同時排進清理清單
- 🔴 **不要**加「繞過 namespace 解析」的 alias 就當修好：那正是把兩套 API 並存下去的做法，下一個人會繼續用舊的那套（症狀會以「權限／多租戶查錯資料」的形式回來）

**Checklist:** Search ALL plugins for `db.fetchone`, `db.fetchall`, `db.execute` — verify signatures match framework.

### 6. F-String Multi-Line Syntax Error from Bad Patches

**Symptom:** `SyntaxError: unterminated string literal` after patching.

**Root cause:** When fixing f-strings, replacing `\\n` with real line breaks creates multi-line f-strings. In Python <3.12, f-strings without `\` line continuation or `"""` triple quotes will fail.

**Fix:** Keep `\n` escape sequences inside f-strings — never expand to real line breaks unless using `f"""..."""`.

## Diagnostic Procedure

When a first-run fails:

1. **Read the FIRST error** — stop at the first crash, don't scroll past it
2. **Identify which category** from the 9 below
3. **Apply the fix** (one at a time)
4. **Restart and repeat** — the next crash will likely be a different category
5. **Checklist sweep** after fixing each category — the same bug pattern often hits multiple plugins

### Expected Cascade Count

When porting a monolith (13+ plugins) to a framework for the first time, expect **8–12 sequential crashes** on startup. Each fix reveals the next bug in the chain. This is NOT a sign of broken architecture — it's the normal cost of API surface alignment between old-plugin code and new-framework interfaces.

**Key insight:** Each crash falls into one of ~9 predictable categories (below). Once you've seen all 9, you've cleared the entire first-run cascade.

## The 9 Most Common First-Run Crashes (In Order)

### 1–6: (see above — async on_load, APScheduler event loop, job context param, ConfigManager .env, DB signature, f-string syntax)

### 7. BotContext Alias Missing

**Symptom:** `AttributeError: 'BotContext' object has no attribute 'quota'`

**Root cause:** The framework's `BotContext` defines `quota_manager` but plugins reference `self.context.quota`. The alias `identity = identity_service` exists but `quota` doesn't.

**Fix:** Add the alias to both the dataclass and the builder:
```python
# In context.py dataclass:
quota: Optional[object] = None  # alias for quota_manager

# In bot.py BotBuilder.__init__:
self.context = BotContext(
    quota_manager=self.quota,
    quota=self.quota,  # same object, different name
)
```

**Checklist:** Search ALL plugins for `self.context.X` where X is a service — verify every access pattern has an alias or matching field in BotContext.

### 8. Service/Manager API Mismatch

**Symptom:** `TypeError: X.preflight_check() got an unexpected keyword argument 'cost'`

**Root cause:** Plugin uses old API (e.g., old QuotaManager with `preflight_check(chat_id, qtx_id, cost=1)` returning dict) but framework's version has different signature.

**Fix options:**
- **只限一次性 spike：** 整段註解掉並在 issue 裡記一筆；**不要**在主線分支留 「comment out + TODO」
  （下一個人會以為那是壞掉的程式碼而刪掉，或忘記它其實是功能缺口）
- **正式做法：** 依新服務的 API 改寫整合，並補一個呼叫它的測試

**Common mismatches when porting monolith to framework:**
| Old API | New API | Symptom |
|---------|---------|---------|
| `preflight_check(id, name, cost=1)` → dict | `preflight_check(uid, resource, amount=1)` → Reservation | `unexpected keyword 'cost'` |
| `db.fetchone(sql, params)` | `db.fetch_one(pkg, sql, params)` | `fetchone not found` |
| `db.execute(sql, params)` | `db.execute(pkg, sql, params)` | SQL str passed as package |
| `emit_event(name, data)` (sync) | `await emit_event(name, data)` (async) | coroutine never awaited |

### 9. Coroutine Not Awaited Cascade

**Symptom:** `RuntimeWarning: coroutine '...emit_event' was never awaited`

**Root cause:** Method changed from sync to async during framework migration; not all call sites were updated.

**Fix:** Search ALL plugins for all `self.emit_event(` calls and add `await`.

**Common locations:** ChatPlugin (message events, tag handlers), DiaryPlugin (diary.written), Media plugins (draw/video requested).

### 10. Variable Lost During Code Cleanup

**Symptom:** `NameError: name 'prefs' is not defined`

**Root cause:** Removing an old code block also removed a variable assignment that code below still uses.

**Fix after removing/rewriting a code block:**
- Scan ALL lines below the patch site for variable references
- For each referenced variable, verify it's assigned before use
- Add missing assignments as needed

## Prevention

When designing a multi-plugin framework:

- Make `on_load()` synchronous, or add a separate `async def on_load_async()` hook
- Require APScheduler event loop at construction time, not as a lazy init
- Ban `context` parameter in job function signatures — always use `self.context`
- Provide direct SQL methods (`fetchone`, `fetchall`, `execute`) alongside namespace methods
- Use a single env var loader that checks both ConfigManager and `os.getenv`
