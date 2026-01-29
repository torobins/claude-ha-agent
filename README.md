# Claude Home Assistant Agent

A Dockerized AI agent that lets you control Home Assistant through natural language via Telegram. Powered by Claude (Anthropic).

## Features

- **Natural Language Control**: Just tell it what you want ("turn off the kitchen lights", "are all doors locked?")
- **Telegram Interface**: Chat with your home from anywhere
- **Scheduled Tasks**: Automatic checks like nightly door lock verification
- **Smart Entity Resolution**: Learns your nicknames for devices ("foyer light" → `light.zwave_switch_3`)
- **Intelligent Caching**: Fast responses through cached entity metadata

## Quick Start

### Prerequisites

1. **Home Assistant** with REST API access
2. **Anthropic API key** from [console.anthropic.com](https://console.anthropic.com)
3. **Telegram Bot** created via [@BotFather](https://t.me/BotFather)
4. **Docker** installed on your server

### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/torobins/claude-ha-agent.git
   cd claude-ha-agent
   ```

2. **Create your `.env` file**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` with your actual credentials:
   - `ANTHROPIC_API_KEY`: Your Anthropic API key
   - `HA_TOKEN`: Home Assistant long-lived access token (create in HA → Profile → Long-Lived Access Tokens)
   - `TELEGRAM_TOKEN`: Bot token from @BotFather

3. **Configure the application**

   Edit `config/config.yaml`:
   - Set your Home Assistant URL
   - Add your Telegram user ID to `authorized_users` (get it from [@userinfobot](https://t.me/userinfobot))
   - Set `notification_chat_id` for scheduled task notifications

4. **Configure scheduled tasks** (optional)

   Edit `config/schedules.yaml` to enable/customize scheduled checks.

5. **Build and run**
   ```bash
   docker-compose up -d
   ```

6. **Start chatting**

   Open Telegram, find your bot, and send `/start`

## Usage Examples

```
You: Are all my doors locked?
Bot: I checked all 3 door locks:
     - Front Door: locked
     - Back Door: locked
     - Garage Door: unlocked ⚠️

You: Lock the garage door
Bot: Done, garage door is now locked.

You: Turn on the foyer light
Bot: I turned on the Front Entryway Light (light.zwave_switch_3).
     I'll remember that "foyer light" refers to this.

You: What's the temperature?
Bot: Indoor: 72°F (thermostat)
     Outdoor: 45°F (weather sensor)
```

## Commands

- `/start` - Welcome message and help
- `/status` - Check bot and Home Assistant connection status
- `/model` - View or change Claude model (haiku/sonnet/opus)
- `/usage` - View today's token usage and estimated cost
- `/reset` - Reset today's usage stats to zero
- `/limit` - View or set daily token limit
- `/clear` - Clear conversation history

## Configuration

### `config/config.yaml`

| Setting | Description |
|---------|-------------|
| `home_assistant.url` | Your HA instance URL |
| `claude.model` | Claude model to use (default: claude-haiku-4-5-20251001) |
| `claude.max_history` | Conversation history length |
| `telegram.authorized_users` | List of allowed Telegram user IDs |
| `telegram.notification_chat_id` | Where to send scheduled task results |
| `cache.refresh_interval_hours` | How often to refresh entity cache |

### `config/schedules.yaml`

Define automated tasks with cron expressions:

```yaml
schedules:
  - name: "nightly_lock_check"
    cron: "0 21 * * *"  # 9 PM daily
    prompt: "Check all door locks and report their status"
    enabled: true
```

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Telegram      │────▶│  Claude Agent    │────▶│  Home Assistant │
│   (User Chat)   │◀────│  (Anthropic API) │◀────│  (REST API)     │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │                         │
                        ┌──────┴──────┐          ┌───────┴───────┐
                        │  Scheduler  │          │  Cache Layer  │
                        │ (APScheduler)│          │ + Aliases DB  │
                        └─────────────┘          └───────────────┘
```

## Available Tools

The agent can:
- Get entity states (lights, locks, sensors, climate, etc.)
- Turn devices on/off
- Lock/unlock doors
- Set climate/thermostat
- Query history
- Trigger automations
- Call any HA service
- Learn and remember entity aliases

## Unraid Installation

1. Install the Docker container using the Unraid Community Applications or manual Docker setup
2. Map the volumes:
   - `/app/config` → `/mnt/user/appdata/claude-ha-agent/config`
   - `/app/data` → `/mnt/user/appdata/claude-ha-agent/data`
3. Set the environment variables in the container settings

### Docker DNS for .local Hostnames

Docker containers cannot resolve mDNS `.local` hostnames by default. If your Home Assistant uses `homeassistant.local`, add an `extra_hosts` entry to `docker-compose.yml`:

```yaml
services:
  claude-ha-agent:
    # ... other config ...
    extra_hosts:
      - "homeassistant.local:192.168.1.XX"  # Replace with your HA IP
```

Find your HA IP by pinging it from the host: `ping homeassistant.local`

## Important: Config File Management

**The `config/config.yaml` file contains your personalized settings** (Telegram user ID, HA URL, model preference). The repository contains only a template with placeholder values.

### Avoiding Config Overwrites

When updating the deployment:

```bash
# SAFE: Pull and rebuild (preserves local config)
git pull
docker-compose build
docker-compose up -d

# DANGER: Hard reset will overwrite your config!
git reset --hard origin/master  # ⚠️ This destroys local config changes
```

If you accidentally reset your config, you'll see these errors:
- `"Sorry, you're not authorized"` - Telegram user ID was reset to placeholder
- `"Cannot connect to host homeassistant.local"` - Docker can't resolve mDNS
- `"Failed to connect to Home Assistant"` - HA URL or token issue

### Recommended: Backup Your Config

Before any git operations on the deployment server:

```bash
# Backup config
cp config/config.yaml config/config.yaml.backup
cp docker-compose.yml docker-compose.yml.backup

# After git operations, restore if needed
cp config/config.yaml.backup config/config.yaml
```

### Alternative: Use Environment Variables

For sensitive deployments, you can override config via environment variables instead of editing `config.yaml` directly. This keeps your secrets out of version control entirely.

## Cost Considerations

The agent uses Claude API which has per-token costs:
- **Claude Haiku** (default): ~$0.80/$4 per million input/output tokens - fastest, most cost-effective
- **Claude Sonnet**: ~$3/$15 per million tokens - good balance of capability and cost
- **Claude Opus**: ~$15/$75 per million tokens - most capable, highest cost

A typical conversation costs fractions of a cent. Use `/usage` to monitor your daily token consumption and `/model` to switch between models based on your needs.

## Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export ANTHROPIC_API_KEY=...
export HA_TOKEN=...
export TELEGRAM_TOKEN=...
export CONFIG_DIR=./config

# Run locally
python -m src.main
```

## License

MIT
