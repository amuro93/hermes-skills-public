# 無 shell 的遠端 ComfyUI：讓它自己把 HF 模型抓下來

2026-09-24 實戰（本機，把 FastH3 8-Step V2 裝進 5080）。
前情：5080 沒有 SSH/SMB，只能走 ComfyUI HTTP API。

## 閘門與端點行為（全部實測）

| 動作 | 結果 |
|:--|:--|
| `POST /api/manager/queue/install_model`（社群 gguf） | **400** `Invalid model install request is detected` |
| 同上，但先寫 local model-list.json 進 `user/default/ComfyUI-Manager/` | 仍 400（路徑錯，Manager 讀 `user/__manager/`） |
| `POST /api/userdata/ComfyUI-Manager/model-list.json`（含 `/`） | **405** Method Not Allowed |
| `POST /api/userdata/ComfyUI-Manager%2Fmodel-list.json` | **200** ✅ |
| `POST /api/userdata/..%2F__manager%2Fmodel-list.json` | **403** |
| `DELETE /api/userdata/x%2Fy.json` | **204** ✅（裸斜線一樣 405） |
| `PUT /api/userdata/x.json` | 405（Allow: DELETE,GET,HEAD,POST） |
| `POST /api/manager/component/save` | 200，**body 就是絕對路徑** |
| `POST /api/manager/snapshot/save` | 405（這版沒有） |
| `GET /api/manager/db_mode` | `cache` |
| `GET /api/lm/settings` | 吐 `default_lora_root` 等本機路徑 |

### 白名單原始碼（`glob/manager_server.py`）

```python
async def check_whitelist_for_model(item):
    json_obj = await core.get_data_by_mode('cache', 'model-list.json')
    for x in json_obj.get('models', []):
        if x['save_path'] == item['save_path'] and x['base'] == item['base'] and x['filename'] == item['filename']:
            return True
    json_obj = await core.get_data_by_mode('local', 'model-list.json')
    ...
    return False
```

→ 就算把檔案寫對位置，條目格式也要 `save_path`/`base`/`filename` 三欄對得上 registry 的寫法。
→ security level：`middle` 允許 `security_level in ['weak','normal','normal-']`；`.gguf`（非 safetensors）需要的
`high` 檢查在最外層是 `return True`（永遠放行）→ **403 不會出現，擋人的只有白名單**。

## 可行路徑：FL_HFDatasetDownloader

```python
wf = {"1": {"class_type": "FL_HFDatasetDownloader", "inputs": {
        "repo_id": "rzgar/FastVideo-FastH3-Motion-Enhanced-Comfy",
        "repo_type": "model",
        "local_dir": "D:/ComfyUI_windows_portable/ComfyUI/models/diffusion_models",
        "max_workers": 4, "download_trigger": True}},
      "2": {"class_type": "PreviewAny", "inputs": {"source": ["1", 0]}}}
# POST /api/prompt → 200 {"prompt_id": "...", "number": 31, "node_errors": {}}
# 任務進 queue_running 並持續（實測 60 秒仍在跑，GB 級下載本來就久）
```

- 🔴 `FL_HFDatasetDownloader` **不是 output node** → 必須接一顆 output（`PreviewAny` 最輕，或 `SaveText`）
  否則 `400 {"error": {"type": "prompt_no_outputs"}}`。
- 同一包的相關節點：`FL_HF_Character`（上傳到 HF，要 api_key）、`FL_HFHubModelUploader`、`FL_GoogleDriveDownloader`。
- 只想拿單檔 → **挑「整個 repo 就那一顆」的 repo**，不要挑 4 個 quant 都在的 repo。

## 失敗/踩過的寫檔路徑（留著別重試）

- `POST /api/models/download`、`/api/manager/download_model`、`/api/hf/download` → 405（不存在）。
- WAS `Save Text File`：`path="D:/..."` 而 output 在 `F:\` → `ValueError: Paths don't have the same drive`
  （例外從 `comfyui-lora-manager` 的 metadata hook 包裝層冒出來，別被 traceback 誤導去找那個套件）。
- `SaveText`（內建）：只能 output 目錄。
- ComfyUI-Lora-Manager：只有 Civitai 下載（`download_from_civitai`），**沒有任意 URL / HF 下載**。
- Manager channel 可設 `POST /api/manager/channel_url_list`，但**只接受 `channel_dict` 裡既有的 key**
  （default/recent/legacy/forked/dev/tutorial…），**塞不進自製 URL**。

## 收尾禮儀
- 試探時留下的檔案要清：`DELETE /api/userdata/<url-encoded>`。
- `component/save` 建出來的 probe 檔沒有刪除 API，只能覆寫成無害內容，**主動跟 使用者 說一聲**。
