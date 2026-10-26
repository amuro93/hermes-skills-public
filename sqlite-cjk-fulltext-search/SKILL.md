---
name: sqlite-cjk-fulltext-search
description: Use when 為中文內容做 SQLite 全文檢索（FTS5 trigram + 短詞 LIKE 分流）。
version: 1.0.0
author: Drizzt Studio
metadata:
  hermes:
    tags: [sqlite, fts5, cjk, fulltext-search, memory-system]
    related_skills: [systematic-debugging]
---

# SQLite 中文全文檢索（CJK Full-Text Search）

## When to Use / 適用時機

要在應用程式裡為**中文內容**做關鍵字檢索：聊天紀錄、日記、長篇小說、帳目備註、知識庫片段。前提是資料已經在 SQLite（或願意放進 SQLite）—— 這個規模不需要向量 DB，`FTS5` 就夠。

## 步驟

### 1. 選 tokenizer：`trigram`，不要用預設

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
  content,
  tokenize='trigram'
);
```

- **預設的 `unicode61` 對中文近乎無效**：它按空白與標點切詞，一整句中文會被當成**一個 token** ⇒ 除非使用者整句一字不差地打，否則搜不到。
- `trigram` 把內容切成 **3 字元的滑動視窗**，因此支援中文子字串檢索 —— 這是中文場景的重點。

### 2. 🔴 `trigram` 的硬限制：查詢字串必須 ≥3 個字元

**短於 3 字時回空集合、不報錯**（不是 exception，是安靜地 0 筆）。使用者搜「今天」「記帳」「股利」這種 2 字詞**永遠搜不到，而你看不到任何錯誤**。

- ✅ 加引號（`MATCH '"今天"'`）**不能**突破這個限制 —— 引號只是把查詢變成片語查詢，底層仍需要 trigram。
- ✅ **正確做法是查詢端分流**：

```python
def search(keyword: str, limit: int = 5) -> list:
    kw = (keyword or "").strip()
    if not kw:
        return []
    try:
        with sqlite3.connect(DB_PATH) as conn:
            if len(kw) < 3:
                # trigram 建不出索引 ⇒ 直接回退 LIKE
                # 🔴 LIKE 的 % 與 _ 是萬用字元：使用者輸入含這兩個字元時要轉義，
                #    否則「50%」會被當成「50 開頭」而多回一堆。
                safe = kw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                rows = conn.execute(
                    "SELECT id, content FROM messages WHERE content LIKE ? ESCAPE '\\' "
                    "ORDER BY ts DESC LIMIT ?", (f"%{safe}%", limit)).fetchall()
            else:
                # 🔴 FTS5 的 MATCH 參數是「查詢語法」不是純字串：kw 內含雙引號會讓
                #    語法直接炸掉（unterminated string）。內部引號要加倍轉義再包成片語。
                phrase = '"' + kw.replace('"', '""') + '"'
                rows = conn.execute(
                    "SELECT m.id, m.content FROM messages_fts f "
                    "JOIN messages m ON m.id = f.rowid WHERE f.content MATCH ? "
                    "ORDER BY m.ts DESC LIMIT ?", (phrase, limit)).fetchall()
            return rows
    except sqlite3.OperationalError as e:
        # 🔴 回 None（＝查詢壞了）而不是 []（＝真的沒有）：
        #    使用者分不出這兩種，而靜默吞例外會讓「索引建壞了」永遠沒人發現。
        log.warning("fts search unavailable: %s", e)
        return None
```

- 把 `len(kw) < 3` 的分支寫成 **LIKE 回退**，不要寫成「回一個空結果」—— 使用者分不出「沒有」和「壞了」。

### 3. 索引與主表寫在同一個 transaction

```python
with sqlite3.connect(DB_PATH) as conn:
    cur = conn.execute(
        "INSERT INTO messages (session_id, role, content, ts) VALUES (?,?,?,?)",
        (session_id, role, content, ts))
    conn.execute("INSERT INTO messages_fts (rowid, content) VALUES (?, ?)",
                 (cur.lastrowid, content))
    conn.commit()
```

- 用**獨立的（非 `content=` 外部內容）fts5 表**，插入時**自己指定 `rowid = messages.id`**。
- 🔴 **只寫 INSERT 是不完整的**：改過／刪過之後索引會留著舊內容（搜到已刪的訊息、搜不到改過的句子）。**三條寫入路徑**都要在同一 transaction 內同步，這是最不容易壞的做法：

  ```python
  # UPDATE
  with sqlite3.connect(DB_PATH) as conn:
      conn.execute("UPDATE messages SET content=? WHERE id=?", (content, mid))
      conn.execute("DELETE FROM messages_fts WHERE rowid=?", (mid,))
      conn.execute("INSERT INTO messages_fts(rowid, content) VALUES (?,?)", (mid, content))
      conn.commit()

  # DELETE
  with sqlite3.connect(DB_PATH) as conn:
      conn.execute("DELETE FROM messages WHERE id=?", (mid,))
      conn.execute("DELETE FROM messages_fts WHERE rowid=?", (mid,))
      conn.commit()
  ```

  真的需要「DB 自己維護」時，用 **`content=` 外部內容表**（SQLite 內建同步，不會漏），
  並用 `INSERT INTO messages_fts(messages_fts) VALUES('rebuild')` 重建。
- 🔴 **不要**用 external-content ＋ 手寫 trigger：trigger 少寫一個（尤其 DELETE／UPDATE）就造成索引與主表**靜默不同步** —— 症狀是「明明有這筆、就是搜不到」，而且只在改過／刪過的資料上發生，極難重現。
- 同一個 transaction 保證「有訊息就有索引」，不需要補償邏輯。
- 驗收要一次驗三種：insert 後搜得到、update 後**搜不到舊詞**、delete 後搜不到該筆。

### 4. 驗收：必須真的用中文關鍵詞搜到東西

- 🔴 **「搜尋不丟例外」不算驗收** —— FTS 表根本沒建起來時，它也會「不丟例外」（回空）。
- 正確斷言：寫一筆含中文的訊息 → **用該訊息裡的 3 字以上中文片段去搜** → 斷言**命中 ≥1 筆且 id 對得上**。關鍵詞要**從實際寫入的內容取出來**，不要寫死一個剛好不在庫裡的詞。
- 另外**單獨斷言短詞路徑**（2 字）回得出結果（走 LIKE），否則短詞回退是死碼。
- ⚠️ **驗收腳本自己的陷阱**：若程式在後端連不上時會回一句優雅的錯誤字串，而你的斷言只檢查「非空／含中文」，就會出現**假 PASS**（拿錯誤訊息當檢索詞也會「命中」）。斷言要明列不得出現的錯誤樣式。

## 🔴 索引要建在「自己的 DB」，不要接管別的框架的 state.db

- 已經有一個 agent 框架在跑的 `state.db`：
  它帶 **WAL**，**多一個寫入者會讓原框架拒寫**；schema 又綁死該框架的專用表（`schema_version`／租約／路由表），任何一次框架升級都可能改 schema。
- **跨機共用同一個 SQLite 檔**（網路磁碟／雲端同步資料夾）＝WAL 一致性直接失效。
  ⚠️ **不要用「反正只讀」當理由** —— 光是開檔就可能觸發 WAL recovery 而寫入檔案；要真唯讀就用 `mode=ro` URI 或**先複製一份**再開。
- ⇒ 正解：**新服務建自己的 DB**，自己控制 schema 與寫入者；需要舊歷史時做**一次性的「唯讀複本 → 萃取摘要」匯入**，匯入後舊庫維持唯讀。

## 何時不該用這個

- 需要**語意／模糊**匹配（「使用者問的是同一件事但用詞完全不同」）時，關鍵字檢索不夠，得靠 embedding。
- 但 embedding 多一層「外部 API 悄悄被棄用」的風險（歷史實證：embedding 模型無預警 404，取向量回空 → 寫入靜默失敗，兩個月後才發現）⇒ **先用 FTS5 撐著**，真的不夠再上向量，且上之前先確認呼叫端有 `logger.warning`。
