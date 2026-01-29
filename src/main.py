"""Main entry point for Claude Home Assistant Agent."""

import asyncio
import logging
import os
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


async def main():
    """Initialize and run the agent."""
    from .config import init_config, get_config
    from .ha_client import init_ha_client, get_ha_client
    from .ha_cache import init_cache, get_cache
    from .aliases import init_alias_manager
    from .usage import init_usage_tracker
    from .telegram_bot import init_telegram_app
    from .scheduler import init_scheduler, start_scheduler

    # Determine config directory
    config_dir = os.getenv("CONFIG_DIR", "/app/config")
    logger.info(f"Loading config from: {config_dir}")

    try:
        # Load configuration
        config = init_config(config_dir)
        logger.info(f"Config loaded. Model: {config.claude.model}")

        # Initialize Home Assistant client
        ha_client = init_ha_client(
            url=config.home_assistant.url,
            token=config.home_assistant.token
        )
        logger.info(f"HA client initialized: {config.home_assistant.url}")

        # Check HA connection
        if await ha_client.check_connection():
            logger.info("Home Assistant connection successful")
        else:
            logger.error("Failed to connect to Home Assistant")
            sys.exit(1)

        # Initialize cache
        cache = init_cache(
            data_dir=config.cache.data_dir,
            refresh_hours=config.cache.refresh_interval_hours
        )

        # Refresh cache if needed
        if cache.needs_refresh():
            logger.info("Refreshing Home Assistant cache...")
            await cache.refresh(ha_client)
        else:
            logger.info(f"Using cached data: {cache.get_entity_summary()}")

        # Initialize alias manager
        init_alias_manager(config.cache.data_dir)
        logger.info("Alias manager initialized")

        # Initialize usage tracker
        init_usage_tracker(config.cache.data_dir)
        logger.info("Usage tracker initialized")

        # Initialize Telegram bot
        app = init_telegram_app()
        logger.info("Telegram bot initialized")

        # Initialize scheduler
        scheduler = init_scheduler()
        logger.info(f"Scheduler initialized with {len(config.schedules)} tasks")

        # Start scheduler
        start_scheduler()

        # Start Telegram bot (this blocks)
        logger.info("Starting Telegram bot...")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        # Keep running until stopped
        logger.info("Bot is running. Press Ctrl+C to stop.")
        try:
            # Wait forever
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass

    except KeyboardInterrupt:
        logger.info("Shutdown requested...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Cleanup
        logger.info("Shutting down...")
        try:
            from .scheduler import stop_scheduler
            stop_scheduler()
        except Exception:
            pass

        try:
            app = init_telegram_app()
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
        except Exception:
            pass

        try:
            ha_client = get_ha_client()
            await ha_client.close()
        except Exception:
            pass

        logger.info("Shutdown complete")


def run():
    """Entry point for running the application."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
