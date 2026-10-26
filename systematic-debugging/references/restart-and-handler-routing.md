# 「使用者說他重啟了」與 handler 路由陷阱（本 repo 案例筆記）

> 本檔是 `systematic-debugging` 的案例筆記（原創），主文的方法論見 SKILL.md。

## ⚠️ Don't Assume "User Didn't Restart" (When They Say They Did)

**Pitfall:** When a user reports your code fix isn't working after you made changes, the easiest (and wrong) hypothesis is "you need to restart the bot/server."

**What NOT to do:** Keep insisting the user restart when they've already confirmed they did. This wastes turns, frustrates the user, and delays finding the real bug.

**What TO do:**
- Accept their confirmation at face value: "你每次改完程式碼我就馬上重啟了" means the fix truly isn't working
- Look for the actual root cause: import timing, circular imports, handler registration order, different code path being hit, stale data in DB, etc.
- Add diagnostic logging if needed to trace the actual execution path
- Common sneaky causes:
  - **Import timing bug:** Module reads from `os.environ` at import time, but dotenv/`load_dotenv()` hasn't run yet → wrong value
  - **Handler priority:** Another handler (CommandHandler, CallbackQueryHandler, previous MessageHandler) catches the message before your interceptor
  - **Different code path:** The user's action triggers a completely different function than what you modified. Common example: a `ReplyKeyboardMarkup` button (appears above the keyboard) sends the button text as a regular TEXT message, which goes through the general `MessageHandler` → AI chat, NOT through the dedicated `CommandHandler` or `CallbackQueryHandler`. See `quick-intercept-handler-routing.md`.
  - **Stale data in DB:** Old conversation history with function tags contaminates future AI responses
  - **Incorrect route:** Keyboard button sends text through AI chat instead of the dedicated handler. Fix: add a `quick_intercept` check for the exact button text (`if "一鍵拍照" in user_text`) and call the dedicated handler directly. The intercept runs before AI processing, so the dedicated handler takes over cleanly.
