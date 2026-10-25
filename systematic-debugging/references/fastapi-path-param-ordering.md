# FastAPI Path Parameter Route Ordering Pitfall

## The Bug

A **static route with a path parameter** defined **before a more specific static route** will silently swallow requests to the specific route.

```python
@app.get("/api/backup/download/{filename}")  # ← registered FIRST
async def download(filename: str):
    ...

@app.get("/api/backup/auto-download")         # ← registered SECOND
async def auto_download(key: str = ""):
    ...
```

`/api/backup/auto-download` → matches `/api/backup/download/{filename}` with `filename="auto-download"` → **auto_download() is never called** → HTTP 404.

## Root Cause

FastAPI (and Starlette) matches routes **in registration order**. A path parameter (`{filename}`) matches any string, including the literal `auto-download`. The first matching route wins — so the more general route catches the request before the specific one gets a chance.

## The Fix

Register **all static/specific routes before parameterized routes**:

```python
# ✅ Static routes first (most specific → most general)
@app.get("/api/backup/list")                    # 1. fully static
@app.post("/api/backup/now")                    # 2. fully static
@app.get("/api/backup/auto-download")            # 3. fully static
@app.get("/api/backup/download/{filename}")     # 4. path param — last!
```

## Detection

- **HTTP 404** on a route that clearly exists in the source code
- The "swallowed" route works in local dev but not in production (unlikely — it's order-dependent, not environment-dependent)
- Check route registration order by reading `@app.get/post/...` decorators top to bottom in `main.py`

## Prevention Checklist

When adding a new route alongside an existing parameterized route:

- [ ] Is there an existing dynamic route like `/api/resource/{param}` nearby?
- [ ] Is the new route a subset of that pattern? (e.g., `auto-download` vs `{filename}`)
- [ ] If yes, place the new `@app.get(...)` BEFORE the parameterized one
- [ ] Run a quick curl test on the new route after deployment

## Applies To

- FastAPI (`@app.get/post/put/delete`)
- Flask (`@app.route`)
- Any web framework that registers routes in source-code order and supports path parameters
