---
name: windows-app-install-verification
description: Use when 在 Windows 裝第三方 app／驅動並驗收。
version: 1.0.0
author: Drizzt Studio
license: MIT
platforms: [windows]
tags: [windows, install, powershell, driver, uac, verification]
metadata:
  hermes:
    tags: [windows, install, powershell, driver, uac, verification]
    related_skills: [windows-python-tool-compat]
---

# 在 Windows 主機安裝第三方 App／驅動元件

## When to Use

- 使用者丟一個 Windows 應用過來要求「裝起來」（NVIDIA 系、廠商 launcher、帶虛擬裝置驅動的 app）。
- 使用者自己裝卻「按了同意就沒反應」，重試與重開機都一樣。
- 裝的東西會碰系統層（驅動、服務、虛擬裝置、帶來重開機風險）。

適用：任何**不是 Hermes 本體**的外部應用；Hermes 自身的升級／修復走作者內部的 `hermes-upgrade-bitwarden` 流程（**本系列未收錄**）。

## 鐵律

1. 🔴 **先講再動**：開跑前先告訴使用者「會跳 UAC ＋ 可能要求重開機」；
   **重開機會直接中斷對話** —— 要重開前先告知他一聲，別靜默觸發。
2. 🔴 **提權交給使用者本人按**：`Start-Process -Verb RunAs` 的 UAC 視窗出現在他的互動桌面，
   他不在電腦前就不要跑。
3. 🔴 **靜默安裝要「依廠商支援的旗標」＋ 自己收 exit code**：`-s -noreboot` 是 NVIDIA／NSIS 系安裝器的慣例，
   **不是所有 installer 都吃**（MSI 走 `/qn`／`REBOOT=ReallySuppress`，Inno Setup 走 `/SILENT /NORESTART`，
   有些廠商版甚至刻意只支援互動式）。先看官方文件或解壓出來的 `setup.cfg`／`*.iss` 再決定旗標；
   靜默安裝不會自己講結果，所以必須 `-PassThru -Wait` 拿 exit code。
4. 🔴 **佔用共用資源前先查所有權**：GPU／VRAM／服務可能是**別的使用者或其他 agent 的**（本地 LLM 是本機 VRAM 的常客）。
   那不是閒置資源 —— **未經使用者明示不得停、卸載、改設定**；能不能跑得動由實測決定，不拿推算數字回報。

## 步驟

### 1. 驗檔案（別把好檔當壞檔，也別把壞檔當好檔）

```bash
curl -sIL --max-time 30 "<url>" | grep -i content-length   # 伺服器大小
stat -c%s "<本機檔>"                                        # 對 byte 數
```
```powershell
(Get-AuthenticodeSignature -FilePath "<檔>") | Select-Object Status,@{n='Signer';e={$_.SignerCertificate.Subject}}
```
簽章 `Valid` ＋ 大小一致 → **只證明「檔案沒被改動、發行者是它宣稱的那家」**，不代表內容安全
（簽章只驗完整性與來源，不驗行為）。要判定安全仍得看它來自哪個官方網域、必要時比對官方公布的 hash。

真正要排除的兩種情況：
- **大小不一致** → 下載不完整（重下）；來源與官方公布值都拿不到時，別直接執行
- **簽章 `NotSigned`／`HashMismatch`** → 別執行；換官方連結

### 2. 判斷「根本沒跑」還是「跑了失敗」

三處痕跡一次看，**全乾淨 ＝ 連啟動都沒有**（常見病根：廠商 launcher 缺依賴就靜默退出）：

- 程序：`tasklist | grep -i <app名>`
- 解壓／暫存殘留：`C:\NVIDIA\*`、`%LOCALAPPDATA%\Temp\<vendor>*`
- 事件記錄 ＋ 防毒：近幾小時 Application log、`Get-MpThreatDetection`
- 順手看 `Zone.Identifier` 串流（有＝SmartScreen 可能擋；用 MSYS `curl` 下載的通常沒有這道）

### 3. 廠商自解壓包（SFX）→ 繞過 launcher

NVIDIA 等大廠的 `.exe` 常是**自解壓縮包＋前端 launcher**，launcher 依賴官方管理 app（如 NVIDIA App），
沒有就靜默退出。做法：不跑它，直接拆開看（見 `references/vendor-packaged-installers.md`）。

```bash
"/c/Program Files/7-Zip/7z.exe" l "<下載的.exe"                    # 先看有什麼
"/c/Program Files/7-Zip/7z.exe" x -y -o"<解壓目標>" "<下載的.exe"   # 注意 -o 與路徑之間沒有空白，路徑要整段加引號
# 找內層 setup.exe／setup.cfg／廠商安裝框架目錄，跑那個
```
⚠️ 7-Zip 的 `-o` 後面**不能有空白**、且引號要包住整個路徑（`-o"C:\tmp\out"`）；
寫成 `-o "路徑"` 會被當成「另一個參數」而解壓到當前目錄。

### 4. 提權執行（腳本要純 ASCII）

> 從 git-bash 驅動 PowerShell 的兩個固定坑（inline `$_`／反引號被 MSYS 吃掉、
> **PS 5.1 在中文系統把 UTF-8 .ps1 當 Big5 → 整支腳本連第一行都不跑**）詳見作者內部的 `hermes-windows-migration` 踩坑速查（**本系列未收錄**）。
> 本 skill 下的原則：**一律寫成純 ASCII 的 `.ps1` 再 `-File`**，中文訊息改成輸出到檔案用英文寫。

```powershell
$p = Start-Process -FilePath "<dir>\setup.exe" -ArgumentList "-s","-noreboot" `
     -WorkingDirectory "<dir>" -Verb RunAs -PassThru -Wait
"ExitCode = $($p.ExitCode)"        # 靜默安裝只有這裡吐結果
```

長工作用背景跑（`notify=true`），不要卡住對話；但背景工作不能自己回答 UAC。

### 5. 驗收（拿實跡回報，不是「應該裝好了」）

- 安裝目錄／主程式檔案真的存在
- 設定檔與實際埠（例：MCP 型 app 的 `gateway.json`）
- 服務／驅動有沒有註冊（`sc query type= service state= all`）
- 能不能起、能不能被驅動（MCP 型要走 `hermes mcp add` 再 `hermes mcp test`）

## 常見坑

- **中文 `.ps1` 編碼**：症狀像「腳本寫錯」（`ExpectedValueExpression`／`MissingEndCurlyBrace`），其實只是編碼。
- **靜默安裝沒有輸出 ≠ 成功**：沒拿 exit code 就別下結論。
- **廠商 launcher 沒反應不代表權限不足**：先看它依賴什麼（官方管理 app／較新驅動），再繞。
- **驅動類元件可能要重開機才生效**：安裝完成≠功能可用，驗收時把那一步講清楚。
- **不要未經同意改別人的服務設定**：要借資源只能「他用不到時啟、用完還他」，時機由使用者決定。

## 收尾

- 安裝檔、解壓目錄、診斷腳本與 log 集中放在同一資料夾（例如 `~/projects/research/<app>/`），回報時給路徑。
- 把「裝在哪台、能不能被驅動、限制是什麼」寫進對應的產線 skill（下次不用重新摸底）。
