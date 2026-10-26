# 廠商自解壓包（SFX）＋ launcher 的行為

## 外層 exe 不是安裝程式本體

大廠（NVIDIA 系最典型）的 `<App>_v<ver>.exe` 常是 **自解壓縮包 ＋「Package Launcher」前端**：

- 檔案資訊常顯示 `NVIDIA Package Launcher`，版本號跟產品版號無關（例：1.0.14）。
- 可以直接用 7-Zip 列／解，**不需要先執行它**：
  ```bash
  "/c/Program Files/7-Zip/7z.exe" l "<下載的.exe"
  "/c/Program Files/7-Zip/7z.exe" x -y -o"<目標" "<下載的.exe"
  ```
- launcher 的典型行為：**檢查依賴（例如 NVIDIA App）→ 缺少就靜默退出**，
  不留程序、不留殘留、事件記錄乾淨。使用者看到的就是「按了同意就沒反應」。

## 解開後的典型佈局（用來判斷版本／功能）

| 路徑 | 是什麼 |
|---|---|
| `setup.exe` ＋ `setup.cfg` ＋ `NVI2/` | 真正的安裝程式＋廠商安裝框架 |
| `<App>/ui/<App>.exe` | App 本體 |
| `<App>/nv/<App>MCP.exe` | **MCP 伺服器**（能不能被 agent 驅動就看它） |
| `<App>VAD/`（`*vad*.sys/dll`） | 虛擬音訊裝置驅動 |
| `<App>VirtualCamera/` | 虛擬攝影機 filter |
| `<App>Models/` | 模型／OTA 更新工具 |

## 替代安裝路徑的優先序

1. **官方管理 app**（若使用者本來就有，用它裝最乾淨）。
2. **套件管理器**（`winget search <vendor/app>`）—— **不是每個廠商 app 都有**，先搜再下載。
3. **7z 解開後跑內層 `setup.exe`**（提權、`-s -noreboot`）—— 上面前兩條不通時走這條。

## 回報時要講清楚的

- 下載來源 URL ＋ byte 數／指紋（可對帳）。
- 裝在哪個路徑、哪個服務／驅動註冊了。
- 要不要重開機才生效。
- 實際跑過的證據（exit code、檔案存在、服務狀態）—— 沒驗到的部分老實說「還沒驗」。
