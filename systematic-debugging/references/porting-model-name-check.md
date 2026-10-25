# Porting: Model Names Must Come From Old Codebase

## Pattern

When writing/porting a chat service that calls AI APIs, DO NOT guess model names. The old (working) codebase has the exact model name strings — read them from there.

## What Happened (2026-06-24)

During a legacy-bot → new-framework migration, the ChatService was written with guessed model names:

| Position | Guessed (wrong) | Old Codebase (correct) |
|:---------|:----------------|:-----------------------|
| DeepSeek | `deepseek-chat` | `deepseek-v4-flash` |
| Gemini   | `gemini-2.0-flash` | `gemini-3.5-flash` |
| Grok     | `grok-4.3` | `grok-4.3` ✅ |

User's reaction: 「just read the model names the old bot was actually using?」

## Correct Workflow

```bash
# Search old codebase for model strings:
grep -rn '"grok-\|"deepseek-\|"gemini-"' old_project/ --include="*.py"
```

## Checklist

When migrating/creating a new chat engine:

- [ ] Search OLD codebase for model name strings used in API calls
- [ ] Verify old names are live/running (not dead code)
- [ ] Check backup order (primary model, first fallback, second fallback)
- [ ] Check if different models serve different purposes (chat vs search vs memory)
