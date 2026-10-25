# Chinese Keyword Detection False Positive Debug

## Pattern

Keyword-based behavior triggers in Chinese chatbots (e.g., arousal/intensity keyword lists) frequently suffer from false positives because common everyday words overlap with sexual/trigger keywords.

## Real Examples

| Keyword | Intended Match | False Positive Context |
|---------|---------------|----------------------|
| "想要" | Sexual desire expression | "我想要看一下照片", "我想要知道" |
| "好硬" | Erection | "這塊蛋糕好硬", "床墊好硬" |
| "揉" | Sexual touching | "眼睛好酸揉一下" |
| "受不了" | Sexual overwhelm | "這天氣真的受不了" |

## Root Cause

Simple substring matching (`any(w in msg_lower for w in keyword_list)`) cannot distinguish sexual from non-sexual contexts. Chinese is especially vulnerable because:
- Short 2-character words can appear as substrings of longer phrases
- Many common verbs and adjectives overlap with sexual vocabulary
- No grammatical distinction between sexual and non-sexual usage

## Diagnosis

When a user reports that normal chat triggered a sexual behavior flag:

```bash
grep -rn "is_moderate\|is_intense\|is_extreme\|is_flirt\|is_teasing" --include="*.py" .
```

Read the keyword lists and check each word against common innocent usage:

```python
# Test specific keywords
test_words = ["想要", "好硬", "揉", "受不了", "好大"]
for word in test_words:
    freq = sum(1 for msg in sample_chat_log if word in msg.lower())
    print(f"{word}: {freq} occurrences in normal chat")
```

## Fix Strategy

1. **Remove overly broad keywords** — If a word appears in >5% of normal chat messages, it's too broad
2. **Add contextual checks** — Only trigger if the word appears near other sexual context words
3. **Use phrase matching** — Match longer phrases ("好想要你") instead of single words ("想要")
4. **Confidence scoring** — Require multiple keyword hits before triggering behavior flags

## Key Lesson

**Review keyword lists for false positives before shipping.** A single over-broad keyword like "想要" can cause continuous false triggering in a production chatbot, making the behavior system feel broken to the user.
