# piper 本地 TTS 備援（edge/minimax 不可用時）

場景：需要中文語音配音，但 edge TTS 連續失敗、環境未配置雲端 TTS API key 時的輕量離線備援。

## 安裝
```bash
uv venv /tmp/ttsenv
uv pip install --python /tmp/ttsenv/bin/python piper-tts
```

## 下載中文語音模型（piper 1.7 download_voice() 有 bug，手動下載最穩）
`download_voice()` 實測兩個坑：缺 `download_dir` 參數；給了之後內部又有 `str / str` pathlib 錯誤。繞過：

```bash
mkdir -p /tmp/piper_models && cd /tmp/piper_models
curl -sL -o zh_CN-huayan-medium.onnx "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx"
curl -sL -o zh_CN-huayan-medium.onnx.json "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx.json"
```
（onnx 約 63MB + json 4.8KB）

## 生成語音
```bash
echo "櫻花好美，你也來看看。" | /tmp/ttsenv/bin/piper --model /tmp/piper_models/zh_CN-huayan-medium.onnx --output_file /tmp/out.wav
```

## 特性與注意
- zh_CN-huayan 女聲：可用但**偏機械**，比 edge 差；對自然度要求高時優先修 edge 或改接雲端 TTS
- 輸出 wav（一句話約 2 秒，22050Hz）
- `sh: 1: blkid: not found` warning 可忽略，不影響輸出
- 語速/音高可用 `--length-scale` / `--noise-scale` 調整
