# DESC + reversed() 切片方向 Bug 模式

## 問題

從 DB 取「最近 N 筆」的常見錯誤模式：

```python
query = "SELECT * FROM table ORDER BY timestamp DESC LIMIT ?"
# 回傳：最新 N 筆（由新到舊）

rows = list(reversed(rows))
# 翻轉為由舊到新（chronological order）

result = rows[:limit]
# ❌ BUG：取了最舊的 limit 筆，不是最新的！
```

## 根因

`reversed()` 把 `[msg100(newest), msg99, ..., msg1(oldest)]` 變成 `[msg1(oldest), ..., msg99, msg100(newest)]`。

此時 `rows[:20]` = **最舊的 20 筆**（msg1~msg20），`rows[-20:]` = **最新的 20 筆**（msg81~msg100）。

## 正確寫法

```python
result = rows[-limit:]  # ✅ 取最新的 limit 筆
```

## 這個 Bug 的常見觸發情境

1. **多一步過濾後取 slice** — 先 `reversed()` 再 filter，然後 `[:N]` 而不是 `[-N:]`
2. **原本以為 filter 後數量不會超過 N** — 所以 `[:N]` 和 `[-N:]` 應該沒差 → 結果 filter 後數量遠超 N
3. **重構時舊邏輯沒更新** — 以前支援多人格時需要多抓再 filter，單一人格後沒改寫法
4. **Persona/role 過濾器變成無意義但仍執行** — 重構後只剩單一人格，persona 過濾全部命中，但程式仍用 `own[:limit]` 取了最舊的。**教訓：每次重構（人格統一、角色系統合併）後要檢查相關的過濾/切片邏輯是否還有存在必要。**

## 檢查清單

當你看到以下模式時，檢查 slice 方向：

```python
ORDER BY timestamp DESC
reversed() / reverse()
[:N]    # ← 危險！想一下是要最舊還是最新
```
