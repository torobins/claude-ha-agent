"""Telegram bot interface for Claude HA Agent."""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from .config import get_config, set_model, get_current_model, AVAILABLE_MODELS
from .agent import run_agent
from .usage import get_usage_tracker

logger = logging.getLogger(__name__)

# Per-user conversation histories
_conversation_histories: dict[int, list] = {}


def get_history(user_id: int) -> list:
    """Get conversation history for a user."""
    return _conversation_histories.get(user_id, [])


def set_history(user_id: int, history: list):
    """Set conversation history for a user."""
    _conversation_histories[user_id] = history


def clear_history(user_id: int):
    """Clear conversation history for a user."""
    _conversation_histories.pop(user_id, None)


def is_authorized(user_id: int) -> bool:
    """Check if a user is authorized to use the bot."""
    config = get_config()
    authorized = config.telegram.authorized_users
    # If no users configured, allow all (for testing)
    if not authorized:
        logger.warning("No authorized users configured - allowing all users")
        return True
    return user_id in authorized


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user_id = update.effective_user.id

    if not is_authorized(user_id):
        await update.message.reply_text(
            "Sorry, you're not authorized to use this bot. "
            f"Your user ID is: {user_id}"
        )
        return

    await update.message.reply_text(
        "Hello! I'm your Home Assistant controller. "
        "You can ask me to:\n\n"
        "- Check device status: \"Are all doors locked?\"\n"
        "- Control devices: \"Turn off the kitchen lights\"\n"
        "- Get information: \"What's the temperature?\"\n"
        "- And more!\n\n"
        "Commands:\n"
        "/status - Bot status\n"
        "/model - View/change AI model\n"
        "/usage - Token usage stats\n"
        "/reset - Reset today's usage\n"
        "/limit - Set daily token limit\n"
        "/clear - Reset conversation"
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clear command."""
    user_id = update.effective_user.id

    if not is_authorized(user_id):
        return

    clear_history(user_id)
    await update.message.reply_text("Conversation history cleared.")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command - show bot status."""
    user_id = update.effective_user.id

    if not is_authorized(user_id):
        return

    from .ha_client import get_ha_client
    from .ha_cache import get_cache

    ha = get_ha_client()
    cache = get_cache()

    try:
        connected = await ha.check_connection()
        status = "Connected" if connected else "Disconnected"
    except Exception:
        status = "Error"

    history_len = len(get_history(user_id))
    cache_summary = cache.get_entity_summary()
    friendly_model, full_model = get_current_model()

    await update.message.reply_text(
        f"Bot Status:\n"
        f"- Home Assistant: {status}\n"
        f"- Model: {friendly_model}\n"
        f"- {cache_summary}\n"
        f"- Your conversation history: {history_len} messages"
    )


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /model command - view or change the Claude model."""
    user_id = update.effective_user.id

    if not is_authorized(user_id):
        return

    # Check if user provided a model name
    if context.args and len(context.args) > 0:
        model_name = context.args[0]
        success, message = set_model(model_name)
        await update.message.reply_text(message)
    else:
        # Show current model and available options
        friendly_name, full_id = get_current_model()
        models_list = "\n".join([
            f"  - {name}: {desc}"
            for name, desc in [
                ("haiku", "Fastest, cheapest"),
                ("sonnet", "Balanced"),
                ("opus", "Most capable"),
            ]
        ])
        await update.message.reply_text(
            f"Current model: {friendly_name}\n\n"
            f"Available models:\n{models_list}\n\n"
            f"Usage: /model <name>\n"
            f"Example: /model haiku"
        )


async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /usage command - show token usage stats."""
    user_id = update.effective_user.id

    if not is_authorized(user_id):
        return

    tracker = get_usage_tracker()
    friendly_model, _ = get_current_model()
    summary = tracker.get_usage_summary(friendly_model)
    await update.message.reply_text(summary)


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reset command - reset today's usage stats."""
    user_id = update.effective_user.id

    if not is_authorized(user_id):
        return

    tracker = get_usage_tracker()
    tracker.reset_today()
    await update.message.reply_text("Today's usage has been reset to zero.")


async def limit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /limit command - view or set daily token limit."""
    user_id = update.effective_user.id

    if not is_authorized(user_id):
        return

    tracker = get_usage_tracker()

    if context.args and len(context.args) > 0:
        arg = context.args[0].lower()

        # Handle "hard" subcommand
        if arg == "hard":
            if len(context.args) > 1:
                enabled = context.args[1].lower() in ("on", "true", "yes", "1")
                tracker.set_hard_limit(enabled)
                status = "enabled" if enabled else "disabled"
                await update.message.reply_text(f"Hard limit {status}. Bot will {'block' if enabled else 'warn only'} when limit is reached.")
            else:
                status = "enabled" if tracker.config.hard_limit_enabled else "disabled"
                await update.message.reply_text(f"Hard limit is currently {status}.\nUsage: /limit hard on|off")
            return

        # Set new limit
        try:
            new_limit = int(arg.replace(",", "").replace("k", "000"))
            tracker.set_daily_limit(new_limit)
            await update.message.reply_text(f"Daily token limit set to {new_limit:,}")
        except ValueError:
            await update.message.reply_text("Invalid limit. Use a number like: /limit 50000")
    else:
        # Show current limits
        cfg = tracker.config
        hard_status = "ON (will block)" if cfg.hard_limit_enabled else "OFF (warn only)"
        await update.message.reply_text(
            f"Token Limits:\n"
            f"- Daily limit: {cfg.daily_token_limit:,} tokens\n"
            f"- Warning at: {cfg.warning_threshold:.0%} of limit\n"
            f"- Hard limit: {hard_status}\n\n"
            f"Commands:\n"
            f"/limit <number> - Set daily limit\n"
            f"/limit hard on|off - Enable/disable hard limit"
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages."""
    user_id = update.effective_user.id
    user_message = update.message.text

    if not is_authorized(user_id):
        await update.message.reply_text(
            f"Sorry, you're not authorized. Your user ID: {user_id}"
        )
        return

    logger.info(f"Message from {user_id}: {user_message}")

    # Show typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    try:
        # Get conversation history
        history = get_history(user_id)

        # Run agent
        response, updated_history, warning = await run_agent(user_message, history)

        # Save updated history
        set_history(user_id, updated_history)

        # Ensure response is not empty before sending
        if not response or not response.strip():
            response = "I processed your request but have no additional information to report."
            logger.warning("Empty response from agent, using fallback")

        # Send response (split if too long)
        max_length = 4096
        if len(response) > max_length:
            for i in range(0, len(response), max_length):
                chunk = response[i:i + max_length]
                if chunk.strip():  # Only send non-empty chunks
                    await update.message.reply_text(chunk)
        else:
            await update.message.reply_text(response)

        # Send budget warning if applicable
        if warning:
            await update.message.reply_text(f"⚠️ {warning}")

    except Exception as e:
        logger.error(f"Error handling message: {e}", exc_info=True)
        await update.message.reply_text(
            f"Sorry, I encountered an error: {str(e)}"
        )


async def send_notification(app: Application, message: str, chat_id: Optional[int] = None):
    """Send a notification message (used by scheduler)."""
    config = get_config()
    target_chat_id = chat_id or config.telegram.notification_chat_id

    if not target_chat_id:
        logger.warning("No notification chat_id configured")
        return

    try:
        await app.bot.send_message(chat_id=target_chat_id, text=message)
        logger.info(f"Sent notification to {target_chat_id}")
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")


def create_application() -> Application:
    """Create and configure the Telegram application."""
    config = get_config()

    app = Application.builder().token(config.telegram.token).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("usage", usage_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("limit", limit_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app


# Global application instance
_app: Optional[Application] = None


def get_telegram_app() -> Application:
    """Get the global Telegram application."""
    global _app
    if _app is None:
        raise RuntimeError("Telegram app not initialized")
    return _app


def init_telegram_app() -> Application:
    """Initialize the global Telegram application."""
    global _app
    _app = create_application()
    return _app
