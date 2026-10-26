# 壓縮摘要裡的宣稱不可信（本 repo 案例筆記）

> 本檔是 `systematic-debugging` 的案例筆記（原創），主文的方法論見 SKILL.md。

## ⚠️ Context Compaction Claims Are NOT Verified Facts

**Problem:** Context compaction summaries (written by previous agent instances across context windows) can contain claims that sound definitive but were never actually verified.

**Example:** A compaction summary asserted "video generation succeeded" — but investigation showed NO video files were saved to disk. The "success" was an optimistic reading of an intermediate API result, not an end-to-end confirmed save.

**Rule:** Treat any claim in a context compaction that describes a concrete result ("成功", "完成", "已修復", "運作正常", "部署成功") as **unverified until proven otherwise**. Specifically:

- **"File/result saved"** → `stat` or `ls` the claimed path
- **"DB record inserted/updated/deleted"** → `sqlite3 ... "SELECT * FROM table WHERE ..."` to confirm the row exists. **Compaction frequently fabricates SQL INSERTs that were never executed** — always SELECT to verify.
- **"API works"** → run a live test or check logs
- **"Deployed"** → `curl` the deployed file and grep for your fix
- **"Running"** → `ps` / Get-Process to confirm PID exists
- **"Bug fixed"** → read the actual source and check the fix is present

**🔴 Critical DB pattern:** Compaction summaries frequently claim successful SQL INSERT/UPDATE/DELETE operations that were never actually executed. The compaction agent writes the INSERT into the summary as a "completed action" during context window closure, but the SQL was either never sent to the DB or targeted the wrong database file. The only way to catch this is to **actually SELECT the data** in the current session — don't trust what a previous context window claimed it did to the database.

**This is NOT optional** — context compaction is lossy and written by an agent that may not have verified its own conclusions.

---
