# Class-Level Dict Cache Pollution in pytest-asyncio

## Pattern

A class-level `_cache = {}` dict on a service class causes **cross-test pollution** when each test gets a fresh fixture but shares the same class-level cache.

```
_class Cache = {}  # ← class-level, shared across ALL instances

Test A: PersonaService(db1) → _cache["default:user"] = "uuid-a"
Test B: PersonaService(db2) → _cache.get("default:user") → returns "uuid-a"  ← WRONG!
```

## How It Manifests

- Test A creates a record and sets a cache entry
- Test B (different DB file via fixture) reads the stale cache entry from Test A
- Test B's `get_default_persona()` returns a UUID from Test A's DB → `None` when queried on Test B's DB
- Error type: `AssertionError: assert None == '<uuid>'` or `TypeError: 'NoneType' object is not subscriptable`

## Why pytest-asyncio Makes It Worse

With `asyncio_mode = "auto"`, each test gets the **same thread** but may create a **new event loop**. The class-level cache persists across event loops, unlike instance state which gets garbage collected.

## Fix

**Move cache from class-level to instance-level:**

```python
# ❌ BAD — class-level, shared across all instances
class PersonaService:
    _cache = {}
    _cache_ttl = 300

# ✅ GOOD — instance-level, isolated per test
class PersonaService:
    def __init__(self, db_path):
        self._cache = {}
        self._cache_ttl = 300
```

## Additional: thread-local Connection + pytest-asyncio

**另一種相關但成因不同的情況**：用 `threading.local()` 存 SQLite 連線，在 async 測試裡會出兩種相反的問題，別把它們混為一談：

- **同一個 thread 內跑多個 coroutine（pytest-asyncio 預設就是這樣）** ⇒ `threading.local()` 的值**是共用的**（因為都同一個 thread），於是多個 coroutine 會**同時用同一條連線**：交易互相交錯、`commit()` 把別人的未完成寫入一起送出去。這不是「local 掉了」，而是「local 擋不住 coroutine 併發」——**async 要用 `contextvars`，不是 threading.local**。
- **真的換 thread 時（anyio worker thread、`asyncio.to_thread`）** ⇒ local 會是空的，程式若假設「一定已經初始化」就會拿到 `None` 而 `AttributeError`。

**做法：** 連線生命週期要跟著「有意義的單位」（每個 request／每個 session）走，而不是跟著 thread 走；async 場景用 `contextvars.ContextVar`，或明確實例變數 `self._conn` 並限制單一 coroutine 使用。

```python
# ❌ BAD — thread-local, can lose connection in pytest-asyncio
class PersonaService:
    def __init__(self):
        self._local = threading.local()
    def _get_conn(self):
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(...)
        return self._local.conn

# ✅ GOOD — instance variable
class PersonaService:
    def __init__(self):
        self._conn = None
    def _get_conn(self):
        if self._conn is None:
            self._conn = sqlite3.connect(...)
        return self._conn
```

## Diagnosis

When a test suite has inconsistent test results where:
- Isolated test passes (`pytest test.py::TestX::test_y`)
- Same test fails when run in batch (`pytest test.py`)
- Failure type: `None` returned where data should exist
- No DB schema errors, just missing data

Check for:
1. Class-level mutable state (`{}`, `[]`, `set()`) 
2. `threading.local()` connections
3. Singleton patterns that cache between tests

## Prevention

All cache/storage in service classes should be **instance-level**:

```python
@property
def cache(self):
    if not hasattr(self, '_cache'):
        self._cache = {}  # lazy init on first access
    return self._cache
```

Or explicitly in `__init__`:
```python
def __init__(self):
    self._cache = {}  # explicit, visible, testable
```
