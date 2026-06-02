from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from momentum_hunter.models import TradingMode


APP_DIR = Path.home() / "MomentumHunter"
DATA_DIR = APP_DIR / "data"
CONFIG_PATH = APP_DIR / "config.json"


@dataclass
class AppConfig:
    mode: TradingMode = TradingMode.PAPER
    provider: str = "sample"
    review_timezone: str = "America/Chicago"
    evening_review_window: str = "7:00 PM - 8:00 PM CT"
    morning_review_window: str = "7:00 AM - 8:00 AM CT"


def ensure_app_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> AppConfig:
    ensure_app_dirs()
    if not CONFIG_PATH.exists():
        config = AppConfig()
        save_config(config)
        return config

    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    mode = TradingMode(raw.get("mode", TradingMode.PAPER.value))
    return AppConfig(
        mode=mode,
        provider=raw.get("provider", "sample"),
        review_timezone=raw.get("review_timezone", "America/Chicago"),
        evening_review_window=raw.get("evening_review_window", "7:00 PM - 8:00 PM CT"),
        morning_review_window=raw.get("morning_review_window", "7:00 AM - 8:00 AM CT"),
    )


def save_config(config: AppConfig) -> None:
    ensure_app_dirs()
    payload = asdict(config)
    payload["mode"] = config.mode.value
    CONFIG_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
