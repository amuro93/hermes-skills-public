# qdrant-client API 遷移注意事項

> qdrant-client 1.12+ → 1.17+ 的 breaking changes

## 方法名變更

| 舊 API (≤1.11) | 新 API (≥1.12) | 備註 |
|:--|:--|:--|
| `client.search()` | `client.query_points()` | 參數 `query_vector=` → `query=` |
| `client.search()` 回傳 `list[ScoredPoint]` | `query_points()` 回傳 `QueryResponse`，用 `.points` 取 list | |
| `min_should=1` (int) | `min_should=MinShould(conditions=[...], min_count=1)` | 需 import MinShould |

## 索引強制要求（Strict Mode）

Qdrant Cloud 的 strict mode 默認啟用。使用 `Range` / `should` 條件時，對應欄位**必須**有 payload index，否則回傳 400：

```python
# ❌ 會失敗 — timestamp 和 persona 沒有 index
scroll_filter=Filter(
    must=[FieldCondition(key="timestamp", range=Range(gte=week_start))],
)
```

```python
# ✅ 需要在 init_qdrant() 中建立 index
await qdrant.create_payload_index(
    collection_name=collection_name,
    field_name="timestamp",
    field_schema="integer"
)
await qdrant.create_payload_index(
    collection_name=collection_name,
    field_name="persona",
    field_schema="keyword"
)
```

## 常見錯誤與排查

| 錯誤訊息 | 可能原因 | 修復 |
|:--|:--|:--|
| `'AsyncQdrantClient' object has no attribute 'search'` | 使用了舊 API `search()` | 改用 `query_points()` |
| `Index required but not found for "XXX"` | Strict mode 下 filter 欄位沒建 index | 建立 payload index |
| `ValidationError: min_should` | `min_should=1` 寫法不合法 | 改為 `MinShould(conditions=[...], min_count=1)` |
| `points_count=0` 但 bot 有對話 | Embedding 模型失敗 → 記憶未寫入 | 檢查 `get_embedding()` 的 model name 是否有效 |
