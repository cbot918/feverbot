"""
admin_config.py — JSON-backed runtime config for fever-bot admin panel.

Stores two pieces of state that the admin UI can edit:
  - first_questions: pool of Q1 candidates (replaces hard-coded BUILTIN_QUESTIONS at runtime)
  - suggestion_extra_guidelines: free-text appended to the suggestion system prompt

Persisted to a JSON file (path from env ADMIN_CONFIG_PATH, default ./admin_config.json).
Thread-safe; atomic writes via tmp-file + rename.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any

from fever_bot import BUILTIN_QUESTIONS

_CONFIG_PATH = Path(os.environ.get("ADMIN_CONFIG_PATH", "./admin_config.json"))

DEFAULT_WELCOME_MESSAGE = (
    "嗨 {name}！我是你的銷售輔導助手 🔥\n"
    "我會問你三個問題，最後給你個人化建議。\n"
    "隨時輸入「取消」可以中止。"
)

_DEFAULT_CONFIG: dict[str, Any] = {
    "first_questions": list(BUILTIN_QUESTIONS),
    "default_first_question": "",
    "welcome_message": DEFAULT_WELCOME_MESSAGE,
    "suggestion_override": "",
    "suggestion_extra_guidelines": "",
}

_lock = threading.Lock()
_config: dict[str, Any] | None = None


def _load_from_disk() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        cfg = copy.deepcopy(_DEFAULT_CONFIG)
        _write_to_disk(cfg)
        return cfg
    try:
        with _CONFIG_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[admin_config] failed to read {_CONFIG_PATH}: {e}; falling back to defaults")
        return copy.deepcopy(_DEFAULT_CONFIG)

    # Backfill missing keys with defaults so older config files still work
    merged = copy.deepcopy(_DEFAULT_CONFIG)
    if isinstance(data, dict):
        for k in merged:
            if k in data:
                merged[k] = data[k]
    return merged


def _write_to_disk(cfg: dict[str, Any]) -> None:
    tmp = _CONFIG_PATH.with_suffix(_CONFIG_PATH.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _CONFIG_PATH)


def _ensure_loaded() -> dict[str, Any]:
    global _config
    if _config is None:
        _config = _load_from_disk()
    return _config


def get_config() -> dict[str, Any]:
    with _lock:
        return copy.deepcopy(_ensure_loaded())


def update_config(patch: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        cfg = _ensure_loaded()
        if "first_questions" in patch:
            value = patch["first_questions"]
            if not isinstance(value, list) or not all(isinstance(q, str) for q in value):
                raise ValueError("first_questions must be a list of strings")
            cfg["first_questions"] = [q.strip() for q in value if q.strip()]
        if "default_first_question" in patch:
            value = patch["default_first_question"]
            if not isinstance(value, str):
                raise ValueError("default_first_question must be a string")
            cfg["default_first_question"] = value.strip()
        if "welcome_message" in patch:
            value = patch["welcome_message"]
            if not isinstance(value, str):
                raise ValueError("welcome_message must be a string")
            cfg["welcome_message"] = value
        if "suggestion_override" in patch:
            value = patch["suggestion_override"]
            if not isinstance(value, str):
                raise ValueError("suggestion_override must be a string")
            cfg["suggestion_override"] = value
        if "suggestion_extra_guidelines" in patch:
            value = patch["suggestion_extra_guidelines"]
            if not isinstance(value, str):
                raise ValueError("suggestion_extra_guidelines must be a string")
            cfg["suggestion_extra_guidelines"] = value
        # Cross-field: default must be empty or appear in the pool
        if cfg["default_first_question"] and cfg["default_first_question"] not in cfg["first_questions"]:
            cfg["default_first_question"] = ""
        _write_to_disk(cfg)
        return copy.deepcopy(cfg)


def get_first_questions() -> list[str]:
    with _lock:
        return list(_ensure_loaded()["first_questions"])


def get_default_first_question() -> str:
    with _lock:
        return _ensure_loaded()["default_first_question"]


def get_welcome_message() -> str:
    with _lock:
        return _ensure_loaded()["welcome_message"]


def get_suggestion_override() -> str:
    with _lock:
        return _ensure_loaded()["suggestion_override"]


def get_suggestion_extra_guidelines() -> str:
    with _lock:
        return _ensure_loaded()["suggestion_extra_guidelines"]
