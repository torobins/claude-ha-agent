"""Token usage tracking and budget management."""

import json
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class DailyUsage:
    date: str
    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def estimate_cost(self, model: str) -> float:
        """Estimate cost in USD based on model."""
        # Prices per million tokens (input/output)
        prices = {
            "haiku": (0.80, 4.00),
            "sonnet": (3.00, 15.00),
            "opus": (15.00, 75.00),
        }

        # Determine model tier
        model_lower = model.lower()
        if "haiku" in model_lower:
            input_price, output_price = prices["haiku"]
        elif "opus" in model_lower:
            input_price, output_price = prices["opus"]
        else:
            input_price, output_price = prices["sonnet"]

        input_cost = (self.input_tokens / 1_000_000) * input_price
        output_cost = (self.output_tokens / 1_000_000) * output_price
        return input_cost + output_cost


@dataclass
class UsageConfig:
    daily_token_limit: int = 100_000  # Default 100k tokens/day
    warning_threshold: float = 0.8    # Warn at 80% of limit
    hard_limit_enabled: bool = False  # If True, block requests over limit


class UsageTracker:
    """Tracks token usage with daily limits and warnings."""

    def __init__(self, data_dir: str, config: Optional[UsageConfig] = None):
        self.data_dir = Path(data_dir)
        self.usage_file = self.data_dir / "usage.json"
        self.config = config or UsageConfig()
        self.daily_usage: dict[str, DailyUsage] = {}
        self._load()

    def _load(self):
        """Load usage history from file."""
        if self.usage_file.exists():
            try:
                with open(self.usage_file) as f:
                    data = json.load(f)
                    for date_str, usage_data in data.get("daily", {}).items():
                        self.daily_usage[date_str] = DailyUsage(**usage_data)

                    # Load config overrides if present
                    if "config" in data:
                        cfg = data["config"]
                        self.config.daily_token_limit = cfg.get("daily_token_limit", self.config.daily_token_limit)
                        self.config.warning_threshold = cfg.get("warning_threshold", self.config.warning_threshold)
                        self.config.hard_limit_enabled = cfg.get("hard_limit_enabled", self.config.hard_limit_enabled)

                logger.info(f"Loaded usage data from {self.usage_file}")
            except Exception as e:
                logger.warning(f"Failed to load usage data: {e}")

    def _save(self):
        """Save usage history to file."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "daily": {date_str: asdict(usage) for date_str, usage in self.daily_usage.items()},
            "config": {
                "daily_token_limit": self.config.daily_token_limit,
                "warning_threshold": self.config.warning_threshold,
                "hard_limit_enabled": self.config.hard_limit_enabled,
            }
        }
        with open(self.usage_file, "w") as f:
            json.dump(data, f, indent=2)

    def _get_today(self) -> str:
        return date.today().isoformat()

    def _get_or_create_today(self) -> DailyUsage:
        today = self._get_today()
        if today not in self.daily_usage:
            self.daily_usage[today] = DailyUsage(date=today)
        return self.daily_usage[today]

    def record_usage(self, input_tokens: int, output_tokens: int):
        """Record token usage for today."""
        usage = self._get_or_create_today()
        usage.input_tokens += input_tokens
        usage.output_tokens += output_tokens
        usage.requests += 1
        self._save()
        logger.debug(f"Recorded usage: +{input_tokens} input, +{output_tokens} output")

    def get_today_usage(self) -> DailyUsage:
        """Get today's usage stats."""
        return self._get_or_create_today()

    def check_budget(self) -> tuple[bool, Optional[str]]:
        """
        Check if we're within budget.

        Returns:
            Tuple of (allowed, warning_message)
            - allowed: True if request should proceed
            - warning_message: Optional warning if approaching limit
        """
        usage = self.get_today_usage()
        limit = self.config.daily_token_limit

        if limit <= 0:
            return True, None

        percent_used = usage.total_tokens / limit

        # Hard limit check
        if self.config.hard_limit_enabled and percent_used >= 1.0:
            return False, f"Daily token limit reached ({usage.total_tokens:,}/{limit:,}). Try again tomorrow."

        # Warning check
        if percent_used >= self.config.warning_threshold:
            remaining = limit - usage.total_tokens
            return True, f"Warning: {percent_used:.0%} of daily token budget used ({remaining:,} tokens remaining)"

        return True, None

    def get_usage_summary(self, model: str) -> str:
        """Get a formatted usage summary for today."""
        usage = self.get_today_usage()
        limit = self.config.daily_token_limit
        percent = (usage.total_tokens / limit * 100) if limit > 0 else 0
        cost = usage.estimate_cost(model)

        return (
            f"Today's Usage:\n"
            f"- Requests: {usage.requests}\n"
            f"- Input tokens: {usage.input_tokens:,}\n"
            f"- Output tokens: {usage.output_tokens:,}\n"
            f"- Total: {usage.total_tokens:,} / {limit:,} ({percent:.1f}%)\n"
            f"- Est. cost: ${cost:.4f}"
        )

    def set_daily_limit(self, limit: int):
        """Update the daily token limit."""
        self.config.daily_token_limit = limit
        self._save()

    def set_hard_limit(self, enabled: bool):
        """Enable or disable hard limit enforcement."""
        self.config.hard_limit_enabled = enabled
        self._save()


# Global tracker instance
_tracker: Optional[UsageTracker] = None


def get_usage_tracker() -> UsageTracker:
    """Get the global usage tracker."""
    global _tracker
    if _tracker is None:
        raise RuntimeError("Usage tracker not initialized")
    return _tracker


def init_usage_tracker(data_dir: str) -> UsageTracker:
    """Initialize the global usage tracker."""
    global _tracker
    _tracker = UsageTracker(data_dir)
    return _tracker
