"""
APScheduler setup for Mercúrio's proactive execution.

Two job types:
  1. CronTrigger  — heartbeat at fixed times read from app_settings (fallback: RegrasGerais.md)
  2. IntervalTrigger — polls Tarefas.md for past-due ad-hoc tasks (interval from app_settings)
  3. CronTrigger  — organize_memory weekly job (schedule from app_settings)
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
    """Read heartbeat_times from app_settings first, fall back to RegrasGerais.md."""
    try:
        from app.services.supabase import get_setting
        val = get_setting("heartbeat_times")
        if val:
            times = [t.strip() for t in val.split(",") if re.match(r"^\d{2}:\d{2}$", t.strip())]
            if times:
                return times
    except Exception:
        pass
    # fallback: RegrasGerais.md
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


def _get_poll_interval() -> int:
    """Read vault_poll_interval (minutes) from app_settings, default 5."""
    try:
        from app.services.supabase import get_setting
        val = get_setting("vault_poll_interval")
        return int(val) if val and val.isdigit() else 5
    except Exception:
        return 5


def _get_organize_memory_config() -> tuple[str, bool]:
    """Return (schedule_str, enabled) for the organize_memory job."""
    schedule = "mon 08:00"
    enabled = True
    try:
        from app.services.supabase import get_setting
        val_schedule = get_setting("organize_memory_schedule")
        if val_schedule:
            schedule = val_schedule.strip()
        val_enabled = get_setting("organize_memory_enabled")
        if val_enabled is not None:
            enabled = val_enabled.strip().lower() not in ("false", "0", "no")
    except Exception:
        pass
    return schedule, enabled


def _parse_weekly_schedule(schedule_str: str) -> tuple[str, int, int]:
    """Parse 'mon 08:00' → (day_of_week, hour, minute). Defaults to mon 08:00."""
    _DAY_MAP = {
        "mon": "mon", "tue": "tue", "wed": "wed", "thu": "thu",
        "fri": "fri", "sat": "sat", "sun": "sun",
        "seg": "mon", "ter": "tue", "qua": "wed", "qui": "thu",
        "sex": "fri", "sab": "sat", "dom": "sun",
    }
    parts = schedule_str.strip().lower().split()
    day = _DAY_MAP.get(parts[0], "mon") if parts else "mon"
    time_part = parts[1] if len(parts) > 1 else "08:00"
    try:
        hour, minute = [int(x) for x in time_part.split(":")]
    except (ValueError, IndexError):
        hour, minute = 8, 0
    return day, hour, minute


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


def _organize_memory_job() -> None:
    logger.info("scheduler: organize_memory triggered")
    try:
        from app.agent.proactive import organize_memory
        organize_memory()
    except Exception as e:
        logger.error(f"scheduler: organize_memory error: {e}", exc_info=True)


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

    poll_interval = _get_poll_interval()
    _scheduler.add_job(
        _poll_vault_tasks,
        IntervalTrigger(minutes=poll_interval, timezone=_TZ),
        id="poll_vault_tasks",
        replace_existing=True,
    )
    logger.info(f"scheduler: vault task poller registered (every {poll_interval} min)")

    schedule_str, om_enabled = _get_organize_memory_config()
    if om_enabled:
        day, hour, minute = _parse_weekly_schedule(schedule_str)
        _scheduler.add_job(
            _organize_memory_job,
            CronTrigger(day_of_week=day, hour=hour, minute=minute, timezone=_TZ),
            id="organize_memory",
            replace_existing=True,
        )
        logger.info(f"scheduler: organize_memory registered ({schedule_str})")
    else:
        logger.info("scheduler: organize_memory disabled via app_settings")

    _scheduler.start()
    logger.info("scheduler: started")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler: stopped")


def get_jobs_status() -> list[dict]:
    """Return status of all scheduler jobs."""
    if not _scheduler or not _scheduler.running:
        return []
    result = []
    for job in _scheduler.get_jobs():
        result.append({
            "id": job.id,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        })
    return result


def trigger_job(job_id: str) -> bool:
    """Trigger a job immediately in a background thread. Returns True if found."""
    _JOB_FNS = {
        "heartbeat": _heartbeat,
        "poll_vault_tasks": _poll_vault_tasks,
        "organize_memory": _organize_memory_job,
    }
    fn = _JOB_FNS.get(job_id)
    if not fn:
        return False
    import threading
    threading.Thread(target=fn, daemon=True).start()
    return True


def restart_scheduler() -> None:
    """Stop and restart the scheduler to pick up new config from app_settings."""
    stop_scheduler()
    start_scheduler()
