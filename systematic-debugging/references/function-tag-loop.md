# AI 把自己輸出的 function tag 抄進歷史的自我強化迴圈（本 repo 案例筆記）

> 本檔是 `systematic-debugging` 的案例筆記（原創），主文的方法論見 SKILL.md。

## ⚠️ AI Self-Reinforcing Loop: Function Tags in Conversation History

**Symptom:** The AI keeps outputting the same function tag (`[SEARCH: ...]`, `[RENDER: ...]`, etc.) in every response, even when the user didn't ask for it. The behavior persists across restarts.

**Root Cause:** The AI's raw response (including function tags like `[SEARCH: <query>]`) is saved directly to the conversation history database. On the next turn, the AI sees its own tagged response in the history and thinks it should output the same tag again → **self-reinforcing loop**.

```
Turn 1: AI outputs "[RENDER:...] [SEARCH:<query>] 好的～"
         ↓  saved to history with tags
Turn 2: AI sees history → copies the pattern → outputs tags again
         ↓  saved again with tags
Turn N: Infinite loop 🔄
```

**Fix:** Strip function tags from the AI response BEFORE saving to conversation history:

```python
clean_for_history = re.sub(
    r'\[(?:RENDER|DARKRENDER|SEARCH_\w+|EXPENSE|INCOME|WEATHER|VIDEO...):.*?\]',
    '', ai_reply, flags=re.IGNORECASE | re.DOTALL
).strip()
await save_message(user_id, chat_id, "assistant", clean_for_history, ...)
```

**Diagnostic steps:**
1. Check if `ai_reply` (raw response) is saved to history vs `clean_text` (processed, tag-free)
2. Look for `save_message(user_id, chat_id, "assistant", ai_reply, ...)` in the chat handler
3. Check if the history includes function tags by reading the DB directly

**⚠️ This also affects other features:**
- "一鍵拍照" buttons that route through AI chat instead of a dedicated handler
- Any tag the AI can output (WEATHER, DRAW, VIDEO, NOTE, REMIND, etc.)
