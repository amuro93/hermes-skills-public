# Chinese Keyword Detection False Positive Debug

## Pattern

Keyword-based behavior/intent triggers in Chinese text frequently suffer from false positives, because ordinary everyday words overlap with the words you picked as trigger signals. This is a language-level problem, not a bug in a single handler.

## Examples

| Keyword | Intended match | False-positive context |
|---------|---------------|----------------------|
| 「取消」 | 取消訂單 | 「我想取消訂閱電子報」、「取消鬧鐘」 |
| 「退」 | 申請退貨 | 「退回上一頁」、「把視窗退到背景」 |
| 「帳號」 | 帳號相關問題 | 「這筆帳號碼寫錯了」 |
| 「卡」 | 付款失敗 | 「卡片餘額查詢」、「卡片設計很好看」 |

## Root Cause

Simple substring matching (`any(w in msg_lower for w in keyword_list)`) cannot distinguish intent from context. Chinese is especially vulnerable because:

- Short 2-character words appear as substrings of longer, unrelated phrases
- Many common verbs and adjectives overlap with domain vocabulary
- There is no grammatical marker that separates one sense from another

## Diagnosis

When a user reports that normal chat triggered the wrong behavior:

```bash
grep -rn "is_<flag>\|should_trigger\|match_keyword" --include="*.py" .
```

Read the keyword list and test each word against innocent usage:

```python
test_words = ["取消", "退", "帳號", "卡"]
for word in test_words:
    freq = sum(1 for msg in sample_chat_log if word in msg.lower())
    print(f"{word}: {freq} occurrences in normal chat")
```

## Fix Strategy

1. **Remove overly broad keywords** — if a word appears in a large share of normal messages, it is too broad to be a trigger
2. **Add contextual checks** — only trigger when the word appears near other supporting words
3. **Use phrase matching** — match longer phrases instead of single words
4. **Confidence scoring** — require multiple hits before flipping a behavior flag

## Key Lesson

**Review keyword lists for false positives before shipping.** One over-broad keyword can cause continuous false triggering in production, which users experience as "the feature is broken" rather than "the keyword list is sloppy".
