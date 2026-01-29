"""Scheduled task runner using APScheduler."""

import asyncio
import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import get_config, ScheduleTask
from .agent import run_scheduled_prompt
from .telegram_bot import get_telegram_app, send_notification

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None


async def run_scheduled_task(task: ScheduleTask):
    """Execute a scheduled task and send results via Telegram."""
    logger.info(f"Running scheduled task: {task.name}")

    try:
        # Run the prompt through the agent
        response = await run_scheduled_prompt(task.prompt)

        # Send result via Telegram
        app = get_telegram_app()
        message = f"**Scheduled: {task.name}**\n\n{response}"

        await send_notification(app, message)
        logger.info(f"Completed scheduled task: {task.name}")

    except Exception as e:
        logger.error(f"Scheduled task '{task.name}' failed: {e}", exc_info=True)

        # Try to notify about the failure
        try:
            app = get_telegram_app()
            await send_notification(
                app,
                f"**Scheduled task failed: {task.name}**\n\nError: {str(e)}"
            )
        except Exception:
            pass


def parse_cron(cron_expr: str) -> dict:
    """
    Parse a cron expression into APScheduler kwargs.
    Supports: minute hour day month day_of_week

    Examples:
    - "0 21 * * *" = 9:00 PM daily
    - "0 7 * * 1-5" = 7:00 AM weekdays
    - "*/15 * * * *" = every 15 minutes
    """
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {cron_expr}")

    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4]
    }


def init_scheduler() -> AsyncIOScheduler:
    """Initialize and configure the scheduler."""
    global _scheduler

    config = get_config()
    _scheduler = AsyncIOScheduler()

    # Add jobs for each enabled schedule
    for task in config.schedules:
        if not task.enabled:
            logger.info(f"Skipping disabled schedule: {task.name}")
            continue

        try:
            cron_kwargs = parse_cron(task.cron)
            trigger = CronTrigger(**cron_kwargs)

            _scheduler.add_job(
                run_scheduled_task,
                trigger=trigger,
                args=[task],
                id=f"scheduled_{task.name}",
                name=task.name,
                replace_existing=True
            )
            logger.info(f"Added schedule: {task.name} ({task.cron})")

        except Exception as e:
            logger.error(f"Failed to add schedule '{task.name}': {e}")

    return _scheduler


def get_scheduler() -> AsyncIOScheduler:
    """Get the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        raise RuntimeError("Scheduler not initialized")
    return _scheduler


def start_scheduler():
    """Start the scheduler."""
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started")


def stop_scheduler():
    """Stop the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        logger.info("Scheduler stopped")


def list_jobs() -> list[dict]:
    """List all scheduled jobs."""
    scheduler = get_scheduler()
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else None
        })
    return jobs
