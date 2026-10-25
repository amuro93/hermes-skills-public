# JS 模組語法錯誤偵錯：Import Chain SyntaxError

## 現象

瀏覽器主控台顯示：

```
app.js:17 ❌ Phase 6 main.js 載入失敗 SyntaxError: Invalid or unexpected token
    at main.js?v=20260527p74:60:44
```

但 `main.js` 自身成功載入並執行（有 startup log），只是匯入失敗。

## 根因 (Root Cause)

**SyntaxError 發生在子模組，但錯誤被歸因到父模組的 import 陳述式。**

當 `main.js` 使用 `await import('./sub-module.js')` 匯入子模組，如果子模組（或其更深層的 import）有語法錯誤，瀏覽器會將錯誤歸因到 `main.js` 的 import 行，而不是真正有問題的子模組檔案。

> ⚠️ **關鍵洞察**：錯誤訊息中的行號和欄位指向的是父模組的 `import()` 呼叫，不是實際錯誤發生的位置。

## 診斷步驟

### 1. 確認父模組是否正常載入

檢查父模組是否有 startup log：

```
main.js?v=20260527p74:7 🚀 Soul Forge Phase 6 main.js 最終入口啟動
main.js?v=20260527p74:34 ✅ Phase 1 Core 模組已載入
```

如果以上 log 出現，代表父模組本身語法正確，錯誤在子模組。

### 2. 用 Node.js 驗證所有 ES Module 語法

```bash
# 複製每個 .js 為 .mjs 後用 --check 驗證（ES Module 模式）
for f in static/js/views/*.js static/js/components/*.js; do
  cp "$f" /tmp/test.mjs
  node --check /tmp/test.mjs 2>&1 && echo "✅ $f" || echo "❌ $f"
done
```

Node.js 的 `--check` 搭配 `.mjs` 副檔名會以 ES Module 模式解析，正確支援：
- `export` / `import` 語法
- Top-level `await`
- Dynamic `import()`

### 3. 或使用 acorn 解析器（若可用）

```bash
# 直接依賴安裝的 acorn
node -e "
const acorn = require('acorn');
const fs = require('fs');
for (const f of files) {
  try {
    const code = fs.readFileSync(f, 'utf8');
    acorn.parse(code, {sourceType: 'module', ecmaVersion: 2022});
    console.log('✅', f);
  } catch (e) {
    console.log('❌', f + ':' + e.loc.line + ':' + e.loc.column, '-', e.message);
  }
}
"
```

### 4. 用 Hex Dump 驗證字串跳脫問題

當錯誤訊息指向字串字面量內的內容時，可確認實際位元組：

```bash
sed -n 'LINE_NUMBERp' path/to/file.js | xxd
```

這可區分以下情況：
- `\\'`（兩個反斜線 + 單引號）— ❌ 在 JS 單引號字串中：`\\` 被解析為 literal `\`，然後 `'` 終止字串
- `\'`（一個反斜線 + 單引號）— ✅ 正確的跳脫單引號

## 常見陷阱：雙反斜線跳脫 vs 單反斜線跳脫

### 情境：在 JS 單引號字串中嵌入 HTML onclick

```javascript
// 目標 HTML：onmouseover="this.style.color='#fff'"
// 在 JS 單引號字串中應寫為：
html += '<span onmouseover="this.style.color=\'#fff\'">';

// ❌ 錯誤（雙反斜線）：
html += '<span onmouseover="this.style.color=\\'#fff\\'">';
// 解析：\\ → literal \，然後 ' 終止字串 → #fff 在外頭 → SyntaxError
```

### 記憶口訣

| 字串 | 在 JS 內的意義 |
|------|---------------|
| `\'` | 跳脫的單引號（產生字元 `'`）— **正確** |
| `\\'` | literal `\` + 字串終止符 — **語法錯誤** |
| `\\\'` | literal `\` + 跳脫的單引號 `'` — 過度跳脫但語法正確 |

## 預防

1. 在 string-in-string（JS 字串內嵌 HTML 屬性內嵌 JS）情境中，仔細追蹤跳脫層級
2. 提交前對所有 `.js` 執行 ES Module 語法驗證
3. 瀏覽器 SyntaxError 指向 import 行時，**不要修 import 行**，去檢查所有被 import 的子模組
