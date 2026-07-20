"""Load config.yaml + .env, validate. No secrets in yaml, no strategy params in .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

REQUIRED_STRATEGY_KEYS = [
    "swing_lookback", "zone_atr_mult", "min_touches", "zone_max_age_bars",
    "confirm_patterns", "sl_atr_mult", "rr_target", "time_exit_bars", "trend_filter",
]
REQUIRED_RISK_KEYS = [
    "risk_pct", "initial_equity", "fee_pct", "slippage_pct", "daily_loss_limit_pct",
]


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


@dataclass
class MarketConfig:
    name: str
    exchange: str
    symbol: str
    timeframe: str
    mode: str  # "trade" | "signal_only"

    @property
    def tradeable(self) -> bool:
        return self.mode == "trade"


@dataclass
class Secrets:
    telegram_bot_token: str
    telegram_chat_id: str
    binance_api_key: str
    binance_secret: str


@dataclass
class AppConfig:
    paper: bool
    markets: dict[str, MarketConfig]
    strategy: dict
    risk: dict
    data: dict
    db_path: str
    secrets: Secrets


def load_config(config_path: str = "config.yaml", env_path: str = ".env") -> AppConfig:
    root = Path(config_path).resolve().parent
    _load_dotenv(root / Path(env_path).name if not Path(env_path).is_absolute() else Path(env_path))

    raw = yaml.safe_load(Path(config_path).read_text())

    strategy = raw["strategy"]
    missing = [k for k in REQUIRED_STRATEGY_KEYS if k not in strategy]
    if missing:
        raise ValueError(f"config.yaml strategy: missing keys {missing}")

    risk = raw["risk"]
    missing = [k for k in REQUIRED_RISK_KEYS if k not in risk]
    if missing:
        raise ValueError(f"config.yaml risk: missing keys {missing}")

    markets = {}
    for name, m in raw["markets"].items():
        mode = m.get("mode", "trade")
        if mode not in ("trade", "signal_only"):
            raise ValueError(f"market {name}: invalid mode {mode!r}")
        markets[name] = MarketConfig(
            name=name, exchange=m["exchange"], symbol=m["symbol"],
            timeframe=m["timeframe"], mode=mode,
        )
    if not markets:
        raise ValueError("config.yaml: no markets defined")

    secrets = Secrets(
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        binance_api_key=os.environ.get("BINANCE_API_KEY", ""),
        binance_secret=os.environ.get("BINANCE_SECRET", ""),
    )
    paper = bool(raw.get("paper", True))
    if not paper and not (secrets.binance_api_key and secrets.binance_secret):
        raise ValueError("paper: false requires BINANCE_API_KEY and BINANCE_SECRET in .env")
    if not secrets.telegram_bot_token or not secrets.telegram_chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required in .env")

    return AppConfig(
        paper=paper,
        markets=markets,
        strategy=strategy,
        risk=risk,
        data=raw.get("data", {"history_bars": 800, "poll_after_close_sec": 20}),
        db_path=raw.get("db", {}).get("path", "data/livesignal.db"),
        secrets=secrets,
    )
