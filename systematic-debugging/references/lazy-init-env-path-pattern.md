# Lazy Initialization for Module-Level Env-Dependent Paths

## The Problem

When a Python module reads from `os.environ` at import time to construct a file path, but the environment variables are set by `load_dotenv()` (which runs when `config.py` is imported later), the path resolves to a wrong default like `/data`.

```python
# ❌ BAD: Runs at import time, before dotenv loads
_REF_IMAGE_FILE = os.path.join(
    os.environ.get("BOT_DATA_DIR", "/data"),  # → "/data" until dotenv runs
    "ref_images_<instance>.json"
)
```

## The Fix: Lazy Initialization with `_get_ref_image_file()`

Move the singleton variable behind a function that initializes on first call:

```python
# ✅ GOOD: Module-level variable starts as None
_REF_IMAGE_FILE = None

def _get_ref_image_file() -> str:
    """Lazy init: ensures config.py / dotenv has loaded before resolving path"""
    global _REF_IMAGE_FILE
    if _REF_IMAGE_FILE is None:
        try:
            from config import BOT_DATA_DIR  # ← now safe: dotenv already ran
            data_dir = BOT_DATA_DIR
        except ImportError:
            data_dir = os.environ.get("BOT_DATA_DIR", "/data")
        _REF_IMAGE_FILE = os.path.join(data_dir, "ref_images_<instance>.json")
    return _REF_IMAGE_FILE
```

## When to Use

- Module-level path/filename depends on `os.environ` + a config module
- The config module calls `load_dotenv()` at import time
- The module may be imported before config is fully loaded
- The value is read many times and should be cached after first resolution

## Common Signs You Need This Pattern

- FileNotFoundError for a file that you confirmed exists on disk
- Default fallback value (`/data`, `/tmp`, `.`) instead of the real configured path
- Log shows different path at import time vs runtime
- Bug only appears when module is imported early in the startup sequence
