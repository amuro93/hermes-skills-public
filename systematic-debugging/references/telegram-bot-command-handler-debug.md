# Telegram Bot Command Handler Debugging

## CommandHandler Won't Match Photo Captions

**Key PTB quirk:** `CommandHandler` matches against `update.message.text`, NOT `update.message.caption`.

When a user sends a photo with `/setref` (or any command) written in the photo's caption field:
- `update.message.text` → `None` (photo messages have no `text`)
- `update.message.caption` → `"/setref"` (the command text lives here)
- CommandHandler does NOT check caption → handler never fires

**Fix:** The user must send the command as a separate text message, or — more commonly — **reply to the photo** with the command:
```
① Send photo as a standalone message
② Find the photo → Reply to it → Type /setref → Send
```

When replying:
- `update.message.text` → `"/setref"` (the command message text)
- `update.message.reply_to_message.photo` → the original photo data

## Common Handler Order Bug: Argument Processing After Early Return

**Pattern:** A command handler checks for required data (photo, file, user input) and returns early with help text if missing, BUT checks for `list`/`help`/`status` arguments **after** that early return:

```python
# ❌ BAD: list check is after the early return
async def setref_command(update, context):
    photo = get_photo(update)
    if not photo:
        await update.message.reply_text("請傳送照片...")
        return  # ← list never reached!

    if context.args and context.args[0].lower() == "list":
        await show_list()  # ← unreachable code

# ✅ GOOD: list check before data validation
async def setref_command(update, context):
    if context.args and context.args[0].lower() == "list":
        await show_list()
        return

    photo = get_photo(update)
    if not photo:
        await update.message.reply_text("請傳送照片...")
        return
```

**Diagnosis:** When a user reports `/command list` (or any argument variant) doesn't work but the base command works fine, look for early returns before argument processing.

## Silent Handler Interception by Photo/Voice/Audio MessageHandler

**Pattern:** When a user sends a photo, the general `MessageHandler(filters.PHOTO, ...)` fires BEFORE any CommandHandler gets a chance.

This means:
- Sending a photo → chat AI sees it via vision API, generates a response
- Then typing `/setref` as a new message → this IS a separate handler call, not blocked
- But typing `/setref` as a NEW message (not as a reply) → handler has no photo data → help text

**What happens in the message flow:**
```
User sends photo → MessageHandler(filters.PHOTO) catches it → AI vision processing
User types "/setref" → CommandHandler("setref") catches it → checks for photo → no photo → help text
```

**The photo handler does NOT block the CommandHandler from firing.** Each message triggers its own handler lookup. The issue is the user's workflow expectation vs the code's data expectation.

## Complete Checklist for "Command X Doesn't Work"

1. [ ] Is the handler registered? (grep `add_handler.*CommandHandler("X"`)
2. [ ] Is a MessageHandler catching the same trigger? (check `Filters.COMMAND` vs `Filters.TEXT`)
3. [ ] Is the update type correct? (text vs caption vs button callback)
4. [ ] Are there early-return conditions that skip the expected logic?
5. [ ] If the command processes argument variants (list/help/add), are those checks before or after data validation?
6. [ ] If the command expects a photo: was it sent as caption, same message, or reply?
7. [ ] Check bot's actual response text — help text vs confirmation vs nothing at all
8. [ ] Check logs for the handler's `INFO`/`ERROR` messages
