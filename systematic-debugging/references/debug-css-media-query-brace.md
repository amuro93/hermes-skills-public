# CSS Pitfall: Missing `}` in Media Query Silently Swallows Subsequent Rules

## Symptom

- CSS rule confirmed byte-level in stylesheet (fetched from server, `grep` verified)
- `getComputedStyle(el)` shows property as `none` / `0px` / unset
- Inline style workaround works — proving the element CAN display the property
- Cache busters bumped multiple times with no effect

## Root Cause

A missing closing `}` in a `@media` block causes ALL subsequent CSS rules to be silently parsed into that media query, regardless of their position in the file. The browser's CSS parser is forgiving and does not error — it just treats unclosed blocks as extending indefinitely.

### Real Case (2026-05-19, Character Studio)

```css
/* Line 964 */
@media (max-width: 600px) {
  .admin-modal { ... }
  .admin-content { ... }
  /* ... ~800 lines of admin styles ... */
  .sf-batch-btn { ... }
}  /* Line 1794: closes @media (max-width: 480px) nested inside */
/* MISSING: } to close @media (max-width: 600px) */

/* Line 1805 — STILL INSIDE max-width:600px! */
.welcome-hero {
  background-image: url('../background/bg-welcome-desktop.png'); /* NEVER applies at desktop */
  min-height: 100vh; /* NEVER applies at desktop */
}
```

The page rendered fine at viewport 1280px, but `.welcome-hero` had `background-image: none` because the rule was trapped inside `@media (max-width: 600px)`.

### Why It's Hard to Spot

1. The CSS file passes visual inspection — the missing `}` is invisible
2. Syntax highlighters don't flag it because inside the media query, all rules are individually well-formed
3. `brace-diff = 0` at the welcome section because the issue started far above
4. The browser's CSSOM correctly reports the rule is inside `@media (max-width: 600px)`, but you have to explicitly CHECK that

## Diagnostic Method

```javascript
// Find where .my-class actually landed in the CSSOM
for (let sheet of document.styleSheets) {
  if (!sheet.href?.includes('style.css')) continue;
  for (let rule of sheet.cssRules) {
    if (rule instanceof CSSMediaRule) {
      for (let inner of rule.cssRules) {
        if (inner.selectorText === '.my-suspicious-class') {
          console.log('TRAPPED inside @media:', rule.conditionText);
          console.log('Media matches?', window.matchMedia(rule.conditionText).matches);
          console.log('Viewport:', window.innerWidth, 'x', window.innerHeight);
        }
      }
    }
    if (rule.selectorText === '.my-suspicious-class') {
      console.log('TOP-LEVEL rule (no media) — should apply');
    }
  }
}
```

### Quick Brace Check

```bash
# Find position of the suspicious rule
awk '/\.welcome-hero/{print NR; exit}' style.css  # e.g. 1805
# Count open/close braces before that line
head -n 1805 style.css | grep -o '{' | wc -l  # open
head -n 1805 style.css | grep -o '}' | wc -l  # close
# If open > close, a media query is unclosed
```

## Fix

Add the missing `}` immediately after the last rule that should be inside the media query:

```css
  .sf-batch-btn { font-size: 10px; }
}  /* closes @media (max-width: 480px) */
}  /* ← ADD THIS: closes @media (max-width: 600px) */

/* Welcome section now correctly TOP-LEVEL */
.welcome-hero { background-image: ...; }
```

## Prevention

- When adding a `@media` block, immediately write BOTH `{` and `}` before filling in rules
- Run a brace-checker on CSS files before deploy
- If `getComputedStyle(el).someProp` contradicts the stylesheet source, jump to CSSOM traversal first, not cache-busting
