# 無法 SSH 的遠端 ComfyUI：讓它自己把 HF 模型抓下來

場景：ComfyUI 只開放 HTTP API（沒有 shell／SMB／SSH），但需要把一個 GB 級的 HuggingFace 模型放進 `models/` 目錄。

## 先確認這個版本有哪些端點

不同 ComfyUI-Manager 版本的端點形狀不同，**先探測再寫流程**，不要憑印象打：

- `POST /api/userdata/<path>`：接受 **URL-encoded 的路徑**（`ComfyUI-Manager%2Fmodel-list.json`）。
  裸斜線（`ComfyUI-Manager/model-list.json`）會拿到 `405 Method Not Allowed`；`..%2F` 之類的穿越嘗試會拿到 `403`。
- `DELETE /api/userdata/<url-encoded>` 可以清掉自己寫進去的探測檔。
- `PUT /api/userdata/x.json` 不被支援（`Allow: DELETE,GET,HEAD,POST`）。
- `POST /api/manager/queue/install_model` 對社群來源常回 `400 Invalid model install request is detected`
  —— 它只接受 registry 認得的條目，不能當「任意下載器」用。
- Manager 的 model 白名單是拿 `save_path` / `base` / `filename` 三欄去比對 `model-list.json` 的既有條目，
  所以「檔案寫對位置」還不夠，條目格式也要對得上 registry 的寫法。

（實際可用端點清單請以你安裝的版本為準：`GET /api/manager/db_mode`、`GET /object_info` 都可拿來確認版本差異。）

## 可行路徑：走下載節點，走 ComfyUI 自己的 HTTP API

最可靠的做法是**用一個 HF 下載節點**（例如 `FL_HFDatasetDownloader` 這類）＋ 一顆 output 節點：

```python
wf = {"1": {"class_type": "FL_HFDatasetDownloader", "inputs": {
        "repo_id": "<owner>/<model-repo>",
        "repo_type": "model",
        "local_dir": "<ComfyUI>/models/diffusion_models",
        "max_workers": 4, "download_trigger": True}},
      "2": {"class_type": "PreviewAny", "inputs": {"source": ["1", 0]}}}
# POST /prompt → 200 {"prompt_id": "...", "node_errors": {}}
# 任務會進 queue_running 並持續一段時間（GB 級下載本來就久）
```

- 🔴 下載節點**不是 output node** → 必須接一顆 output（`PreviewAny` 最輕，或 `SaveText`），
  否則會回 `400 {"error": {"type": "prompt_no_outputs"}}`。
- 只想拿單檔時，**挑「整個 repo 就只有那一顆權重」的 repo**，不要挑同時放著多個 quant 的 repo 再想辦法篩。
- 想確認節點有哪些同類可用：`GET /object_info/<class_type>` 看 schema，不要用猜的。

## 這條路上走不通的寫檔方式（留著別重試）

- 直接把連結丟給 `/api/models/download`、`/api/manager/download_model`、`/api/hf/download` 這類端點
  → 多半回 405（端點不存在，不是參數錯）。
- WAS 的 `Save Text File` 節點：輸出目錄與目標目錄**不在同一顆磁碟**時會 `ValueError: Paths don't have the same drive`
  （例外常由 `comfyui-lora-manager` 的 metadata hook 包裝層冒出來，別被 traceback 誤導去找那個套件）。
- 內建 `SaveText` 只能寫到 output 目錄。
- `ComfyUI-Lora-Manager` 只有 Civitai 下載（`download_from_civitai`），沒有任意 URL／HF 下載。
- Manager 的 `POST /api/manager/channel_url_list` **只接受既有 channel key**
  （default/recent/legacy/forked/dev/tutorial…），塞不進自製 URL。

## 收尾禮儀

- 探測時留下的檔案要清：`DELETE /api/userdata/<url-encoded>`。
- `component/save` 這類建出來的檔案可能沒有刪除 API → 只能覆寫成無害內容，並主動告知主機的使用者。
