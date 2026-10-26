# FastAPI／後端 500 的取證法（本 repo 案例筆記）

> 本檔是 `systematic-debugging` 的案例筆記（原創），主文的方法論見 SKILL.md。

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
