---
name: autoip-video-api
description: Use when AutoIP (autoip.app) API — MSR 影片鎖臉、雙人、配音坑、點數計價查詢。
version: 1.0.0
author: Drizzt Studio
tags:
  - autoip
  - video
  - msr
  - face-lock
  - tts
prerequisites: []
---

# AutoIP API（autoip.app）

雲端影片/圖片生成 API。主力價值：**MSR（multi-subject-reference）多主體參考影片**——給 1~4 張參考圖，影片鎖臉換場景。雙人鎖臉已實測成功，是單純文生圖/圖生影片模型「雙人臉部混雜」問題之外的強力替代。

## 基本資訊
- Key：`.env` 的 `AUTOIP_API_KEY`
- Base：`https://autoip.app/api/v1`
- 無公開 API 文件（`/docs`、`/openapi.json` 都 404）

## 計價方式
- 走點數制、單價會隨官方調整而變動，**本文不抄價目表**：呼叫前直接打 `GET /api/v1/pricing` 取當下價目，或看帳號後台。
- 能力上限（非價格）：MSR 最高 **720p，無 1080p**。
- 佇列限制：同帳號可同時進行的佇列任務數有限（實測為個位數），影音任務更少 → **多幕影片必須一次一支順序 submit，不能並行**；實際上限以官方回傳為準。
- 生成時間實測：MSR 480p 5s 約 50 秒；MSR 720p 10s 約 335~350 秒（5.5~6 分鐘/支）。

## MSR 出片流程
1. 準備參考圖：**鎖臉必裁頭肩特寫**——全身照臉只佔畫面 5%，鎖臉會失敗（實測全身照不像 → 裁頭肩特寫後明顯一致）
2. `submit_msr(images=[...], prompt=..., duration=5, resolution="480p"/"720p", aspect="9:16", dialogue=None, descriptions=[...], seed=...)`
   - `descriptions[i]` 對應 `images[i]`，多主體時各自描述清楚（髮型/年齡/服裝）
   - prompt 中文可混英文，包含 MUSIC & SFX / SHOT / VISUAL STYLE 結構
3. poll 約 40~350 秒完成（視解析度與秒數）→ download_output
4. 執行前建議先用最低檔（480p 5s）試水確認 prompt 與動作符合預期，再上 720p 10s 量產——省點數也省等待時間。

## 雙人/多主體（已驗證）
- 2 張不同人參考圖（角色 A 頭肩特寫 + 角色 B 大半身）→ 咖啡廳對坐聊天，**兩張臉各鎖各的，不會混成第三張臉**
- prompt 要把每個人的位置/動作/視線全寫死（例：「左邊女子右手輕托下巴看著右邊，右邊女子左手放在桌上微微前傾說話」）
- 參考圖彼此造型差異大（例如髮色、髮長明顯不同）反而更好鎖定

## ⚠️ 配音坑與靜音疊軌做法（實測驗證）
- 給 `dialogue_text` → 前面會自動加「新聞主播式開場白」+ 無意義語句，後面才唸到設定的台詞
- **不給 dialogue → 一樣自動生成假中文旁白**（聽起來像中文又不是中文）
- 結論：**內建配音關不掉**。要乾淨配音 → 出片後先把原音軌靜音/丟棄，再疊外部 TTS（如 piper 等）
- 直接疊 TTS 會跟內建旁白同時講（兩個語音打架）——必先抽掉原軌：

```bash
# 1. 抽原軌（AutoIP 假旁白丟棄）——video only
ffmpeg -y -i raw_clip.mp4 -an -c:v copy step_silent.mp4
# 2. 疊外部 TTS 音軌
ffmpeg -y -i step_silent.mp4 -i tts_voice.wav -c:v copy -c:a aac -map 0:v -map 1:a step_voiced.mp4
# 3. 多幕 concat 組片（-c copy，編碼一致時）
ffmpeg -y -f concat -safe 0 -i list.txt -c copy final_output.mp4
```

⚠️ **不要用 `-shortest`**——會把 10s 影片截到 TTS 音軌長度（TTS 只有 2~8s）。TTS 比影片短沒關係，音軌播完自然無聲。

## 踩坑
- 內嵌 python heredoc 記得 `import json`（忘了會 NameError，任務已跑完白白浪費點數）
- edge TTS 可能掛掉 → 用 `references/piper-tts-fallback.md` 的本地 piper 備援

## References
- `references/piper-tts-fallback.md` — edge TTS 不可用時的本地中文 TTS 備援（piper-tts 安裝 + 模型手動下載 workaround + 用法）
