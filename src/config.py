"""Configuration loading for Claude HA Agent."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import yaml
from dotenv import load_dotenv


@dataclass
class HomeAssistantConfig:
    url: str
    token: str = field(repr=False)  # Don't print token in logs


@dataclass
class ClaudeConfig:
    api_key: str = field(repr=False)
    model: str = "claude-sonnet-4-20250514"
    max_history: int = 10


@dataclass
class TelegramConfig:
    token: str = field(repr=False)
    authorized_users: list[int] = field(default_factory=list)
    notification_chat_id: Optional[int] = None


@dataclass
class CacheConfig:
    refresh_interval_hours: int = 6
    data_dir: str = "/app/data"


@dataclass
class ScheduleTask:
    name: str
    cron: str
    prompt: str
    enabled: bool = True


@dataclass
class Config:
    home_assistant: HomeAssistantConfig
    claude: ClaudeConfig
    telegram: TelegramConfig
    cache: CacheConfig
    schedules: list[ScheduleTask] = field(default_factory=list)


def load_config(config_dir: str = "/app/config") -> Config:
    """Load configuration from environment and YAML files."""
    # Load .env file if it exists
    load_dotenv()

    # Required environment variables
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
    ha_token = os.getenv("HA_TOKEN")
    telegram_token = os.getenv("TELEGRAM_TOKEN")

    if not anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is required")
    if not ha_token:
        raise ValueError("HA_TOKEN environment variable is required")
    if not telegram_token:
        raise ValueError("TELEGRAM_TOKEN environment variable is required")

    config_path = Path(config_dir)

    # Load main config
    config_file = config_path / "config.yaml"
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    with open(config_file) as f:
        yaml_config = yaml.safe_load(f)

    # Load schedules
    schedules_file = config_path / "schedules.yaml"
    schedules = []
    if schedules_file.exists():
        with open(schedules_file) as f:
            schedules_yaml = yaml.safe_load(f) or {}
            for sched in schedules_yaml.get("schedules", []):
                schedules.append(ScheduleTask(
                    name=sched["name"],
                    cron=sched["cron"],
                    prompt=sched["prompt"],
                    enabled=sched.get("enabled", True)
                ))

    # Build config objects
    ha_config = yaml_config.get("home_assistant", {})
    claude_config = yaml_config.get("claude", {})
    telegram_config = yaml_config.get("telegram", {})
    cache_config = yaml_config.get("cache", {})

    return Config(
        home_assistant=HomeAssistantConfig(
            url=ha_config.get("url", "http://homeassistant.local:8123"),
            token=ha_token
        ),
        claude=ClaudeConfig(
            api_key=anthropic_api_key,
            model=claude_config.get("model", "claude-sonnet-4-20250514"),
            max_history=claude_config.get("max_history", 10)
        ),
        telegram=TelegramConfig(
            token=telegram_token,
            authorized_users=telegram_config.get("authorized_users", []),
            notification_chat_id=telegram_config.get("notification_chat_id")
        ),
        cache=CacheConfig(
            refresh_interval_hours=cache_config.get("refresh_interval_hours", 6),
            data_dir=cache_config.get("data_dir", "/app/data")
        ),
        schedules=schedules
    )


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global config instance."""
    global _config
    if _config is None:
        raise RuntimeError("Config not loaded. Call load_config() first.")
    return _config


def init_config(config_dir: str = "/app/config") -> Config:
    """Initialize and store the global config."""
    global _config
    _config = load_config(config_dir)
    return _config
