# ReplyKeyboardMarkup → Dedicated Handler Routing via Quick Intercept

## The Problem

A `ReplyKeyboardMarkup` button like `KeyboardButton("📸 一鍵拍照")` does NOT trigger a `CommandHandler` or `CallbackQueryHandler`. Instead, pressing it **sends the button text as a regular Telegram text message**, which goes through the catch-all `MessageHandler(filters.TEXT, ...)` → eventually into the AI chat flow.

If the AI responds with chat + function tags (e.g. `[RENDER:...]` but also `[SEARCH_<TYPE>:...]`), the user sees:
1. An image
2. Irrelevant search results (from history contamination)
3. AI chat advancing the narrative when the user just wanted a photo

## Root Cause

```
User presses "📸 一鍵拍照" (keyboard button)
  → Telegram sends text message "📸 一鍵拍照"
    → MessageHandler(filters.TEXT, ...)
      → group_city_weather_handler → chat_handler
        → AI generates chat + [RENDER:...] + [SEARCH_<TYPE>:...]  ❌
        → Chat advances narrative, search results sent
```

The user expected a **silent photo** (no chat, no history contamination), but the button text routed through the AI chat.

## Fix: Quick Intercept

Add a text-match check in `quick_intercept.py`'s `check_quick_intercepts()` that runs BEFORE the AI is called:

```python
# 📸 一鍵拍照（文字按鈕 → 直接拍照，不進 AI 聊天）
if "一鍵拍照" in user_text or "📸 一鍵拍照" in user_text:
    from myapp.handlers.ai_chat import take_photo
    await take_photo(update, context)
    return True  # ← chat_handler returns early, AI never runs
```

The intercept is placed at `chat_handler` line ~327, before any AI processing:

```python
if await check_quick_intercepts(update, context, user_id, chat_id, user_text, role, is_vip, is_admin_user):
    return
```

## When to Use This Pattern

Any time a `ReplyKeyboardMarkup` button should:
- Trigger a **dedicated handler** (like `take_photo`, `search_ledger`, etc.)
- **NOT** advance the conversation narrative
- **NOT** save to chat history
- Run silently in the background

## Alternative: Replace with Inline Button

If you control the UI, replace `ReplyKeyboardMarkup` with an `InlineKeyboardButton` that has `callback_data`:

```python
InlineKeyboardButton("📸 一鍵拍照", callback_data="take_photo")
```

Then handle it with a `CallbackQueryHandler`:

```python
application.add_handler(CallbackQueryHandler(button_handler, pattern="^take_photo$"))
```

The inline button approach is cleaner but requires a different UI pattern (inline buttons appear inside the chat, not above the keyboard).

## Diagnosing If the Intercept Is Working

Add a debug log at the start of `check_quick_intercepts()`:

```python
logger.info(f"🔍 check_quick_intercepts 收到 user_text={repr(user_text)[:80]}")
```

If the log appears → intercept IS reached. If the condition doesn't match → check the button text character-by-character (emoji encoding). If the log doesn't appear at all → the function isn't being called (check handler priority, circular imports, or a different MessageHandler catching the message earlier).
