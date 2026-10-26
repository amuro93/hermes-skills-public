# 前端／Web 類 bug 的快篩清單（本 repo 案例筆記）

> 本檔是 `systematic-debugging` 的案例筆記（原創），主文的方法論見 SKILL.md。

## ⚡ Quick Win Checklist (Start Here for Frontend/Web Bugs)

Before diving into full 4-phase investigation, check these common culprits FIRST:

### 1. JS Console
- Open DevTools Console (F12)
- **No errors ≠ JS ran correctly** — errors can be silently swallowed by try-catch or async rejection
- If console is **completely empty** (no log, no error), check if JS file loaded at all

### 2. Browser Cache
```javascript
// Check if the loaded JS/cache is stale
fetch('/static/js/app.js?nocache='+Date.now())
  .then(r=>r.text())
  .then(t=>console.log('has fix:', t.includes('expected-string')))
```
- Use **Ctrl+Shift+R** (hard reload) OR DevTools → Disable cache
- Or add `?v=N` cache-bust to `<script src>` in HTML — and **actually push/deploy** the HTML change to CDN
- Even after deploying the fix, browsers and CDNs may serve old files for minutes
- **To verify:** fetch the JS file with a cache-busting query param and check if it contains the fix string

### 3. DOM Exists But Page Is Blank
Golden rule: `display: none` on an **ancestor** hides everything inside, even if children have `display: block`.
- Check **computed style** of parent containers: `getComputedStyle(el).display`
- Inline style may be empty but CSS class could still force `display: none`
```javascript
// Three-way check
el.style.display               // inline style (what JS set)
el.getAttribute('style')       // raw style attribute (null if never touched by JS)
getComputedStyle(el).display   // actual final style (CSS + inline)
```

**Critical insight:** `el.style.display` returning empty string (`""`) does NOT mean the element is visible. It means JS never set it. The CSS class may still force `display: none`. Always check `getComputedStyle(el).display` for truth.

**Don't forget parent containers!** A child can have `display: block` but if any ancestor has `display: none`, the child is invisible. Check the entire parent chain when debugging blank pages.

### 4. PWA / Service Worker
- Manifest + SW can serve stale cached content even after deploy
- Clear site data: DevTools → Application → Storage → Clear site data
- Or unregister SW: `navigator.serviceWorker.getRegistrations().then(regs => regs.forEach(r => r.unregister()))`

### 5. JS SyntaxError Points to Import Line but Parent Module Loads Fine

**The "Import Chain" trap:** When `main.js` (parent) reports `SyntaxError: Invalid or unexpected token at main.js:60:44`, but main.js itself successfully loads and emits startup logs — the error is actually in a **child module** that main.js imports, not in main.js itself.

**Why:** Browser attributes syntax errors in dynamically imported modules to the parent's `import()` statement line, not to the actual child file where the error occurs.

**Diagnosis:**
```bash
# Validate ALL JS files as ES modules with Node.js (.mjs forces module mode)
for f in static/js/views/*.js static/js/components/*.js static/js/core/*.js; do
  cp "$f" /tmp/test.mjs
  node --check /tmp/test.mjs 2>&1 && echo "✅ $f" || echo "❌ $f"
done
```

**Common pitfall found this way:** `\\'` (double backslash + single quote) inside a single-quoted JS string — `\\` is parsed as an escaped literal backslash, then `'` terminates the string, making everything after it invalid syntax. Fix: use `\'` (single backslash) for proper single-quote escaping.

See `js-module-syntax-error-debug.md` for full detailed procedure with hex dump technique.

### 6. CSS Rules Exist in Source But Don't Apply

When `getComputedStyle(el).property` shows `none` / `0px` but the CSS file on disk/server has the correct value:

1. **The rule may be trapped inside a `@media` query** due to a missing `}` earlier in the file. Traverse the CSSOM to find where the rule actually landed — see `debug-css-media-query-brace.md`.
2. Do NOT chase cache busters — the CSSOM is ground truth. If the rule is inside a non-matching `@media`, no amount of cache-busting will help.

## Test-harness state: localStorage persists across runs

- localStorage persists across browser_navigate calls
- Previous test sessions leave stale tokens/auth state
- Always `localStorage.clear()` before starting a fresh test sequence
