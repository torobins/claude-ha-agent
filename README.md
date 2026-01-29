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
- `/clear` - Clear conversation history

## Configuration

### `config/config.yaml`

| Setting | Description |
|---------|-------------|
| `home_assistant.url` | Your HA instance URL |
| `claude.model` | Claude model to use (default: claude-sonnet-4-20250514) |
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

## Cost Considerations

The agent uses Claude API which has per-token costs:
- **Claude Sonnet** (recommended): ~$3/$15 per million input/output tokens
- **Claude Haiku** (budget): ~$0.80/$4 per million tokens
- **Claude Opus** (premium): ~$15/$45 per million tokens

A typical conversation costs fractions of a cent. Scheduled tasks are similarly inexpensive.

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
