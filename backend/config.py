"""Simple JSON-file settings store - just the dashboard's asset allowlist
for now. A personal single-user tool doesn't need a settings table in the
database for something this small; a plain file is enough, and it's easy
to hand-edit (data/config.json) if you ever want to bypass the UI.
"""
import json
from pathlib import Path
from typing import List

CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "config.json"
DEFAULT_CONFIG = {"tracked_symbols": ["BTC", "AVAX", "XRP"]}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return {**DEFAULT_CONFIG, **json.loads(CONFIG_PATH.read_text())}
        except (json.JSONDecodeError, OSError):
            return dict(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)


def save_config(config: dict):
    CONFIG_PATH.parent.mkdir(exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


def get_tracked_symbols() -> List[str]:
    return [s.upper() for s in load_config().get("tracked_symbols", [])]


def set_tracked_symbols(symbols: List[str]) -> List[str]:
    config = load_config()
    cleaned = [s.strip().upper() for s in symbols if s.strip()]
    config["tracked_symbols"] = cleaned
    save_config(config)
    return cleaned
