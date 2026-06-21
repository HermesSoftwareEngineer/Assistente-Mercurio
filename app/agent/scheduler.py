"""
APScheduler setup for Mercúrio's proactive execution.

Two job types:
  1. CronTrigger  — heartbeat at fixed times read from RegrasGerais.md
  2. IntervalTrigger (5 min) — polls Tarefas.md for past-due ad-hoc tasks
"""

import logging
import re
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("America/Fortaleza")
_scheduler: BackgroundScheduler | None = None

_DEFAULT_HEARTBEAT_TIMES = ["08:00", "13:00", "18:00"]


def _parse_heartbeat_times() -> list[str]:
    """Read heartbeat_times from RegrasGerais.md, fall back to defaults."""
    try:
        from app.services.obsidian import read_note
        content = read_note("mercurio/instrucoes/RegrasGerais.md")
        for line in content.splitlines():
            if line.strip().startswith("heartbeat_times:"):
                raw = line.split(":", 1)[1].strip()
                times = [t.strip() for t in raw.split(",") if re.match(r"^\d{2}:\d{2}$", t.strip())]
                if times:
                    return times
    except Exception as e:
        logger.warning(f"scheduler: could not parse heartbeat_times: {e}")
    return _DEFAULT_HEARTBEAT_TIMES


def _heartbeat() -> None:
    logger.info("scheduler: heartbeat triggered")
    try:
        from app.agent.proactive import vault_check
        vault_check()
    except Exception as e:
        logger.error(f"scheduler: heartbeat error: {e}", exc_info=True)


def _poll_vault_tasks() -> None:
    """Check Tarefas.md for past-due pending tasks and trigger vault_check if found."""
    try:
        from app.services.obsidian import read_note
        content = read_note("mercurio/Tarefas.md")
        if not content:
            return

        now = datetime.now(_TZ)
        has_due = False

        # Find every prazo line in a pending block
        lines = content.splitlines()
        in_pending_block = False
        for line in lines:
            if "**status:** pendente" in line:
                in_pending_block = True
            elif line.startswith("## ") and in_pending_block:
                in_pending_block = False

            if in_pending_block and "**prazo:**" in line:
                raw_dt = line.split("**prazo:**", 1)[1].strip()
                try:
                    due = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
                    if due.tzinfo is None:
                        from zoneinfo import ZoneInfo as _ZI
                        due = due.replace(tzinfo=_ZI("America/Fortaleza"))
                    if due <= now:
                        has_due = True
                        break
                except ValueError:
                    continue

        if has_due:
            logger.info("scheduler: past-due task found — triggering vault_check")
            from app.agent.proactive import vault_check
            vault_check()
    except Exception as e:
        logger.error(f"scheduler: poll error: {e}", exc_info=True)


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        logger.warning("scheduler: already running")
        return

    _scheduler = BackgroundScheduler(timezone=_TZ)

    times = _parse_heartbeat_times()
    for t in times:
        hour, minute = t.split(":")
        _scheduler.add_job(
            _heartbeat,
            CronTrigger(hour=int(hour), minute=int(minute), timezone=_TZ),
            id=f"heartbeat_{t.replace(':', '')}",
            replace_existing=True,
        )
        logger.info(f"scheduler: heartbeat registered at {t}")

    _scheduler.add_job(
        _poll_vault_tasks,
        IntervalTrigger(minutes=5, timezone=_TZ),
        id="poll_vault_tasks",
        replace_existing=True,
    )
    logger.info("scheduler: vault task poller registered (every 5 min)")

    _scheduler.start()
    logger.info("scheduler: started")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler: stopped")
