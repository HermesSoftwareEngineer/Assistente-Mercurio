import os
import logging
from datetime import datetime, timezone
from supabase import create_client, Client

logger = logging.getLogger(__name__)

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_KEY", "")
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
        _client = create_client(url, key)
    return _client


def get_groups(active_only: bool = True) -> list[dict]:
    try:
        query = get_client().table("groups").select("*")
        if active_only:
            query = query.eq("active", True)
        return query.order("name").execute().data or []
    except Exception as e:
        logger.error(f"Error fetching groups: {e}")
        return []


def get_group_by_name(name: str) -> dict | None:
    try:
        result = (
            get_client()
            .table("groups")
            .select("*")
            .ilike("name", name)
            .eq("active", True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Error fetching group '{name}': {e}")
        return None


def add_group(name: str, jid: str, category: str = "") -> bool:
    try:
        get_client().table("groups").insert(
            {"name": name, "jid": jid, "category": category, "active": True}
        ).execute()
        return True
    except Exception as e:
        logger.error(f"Error adding group '{name}': {e}")
        return False


def remove_group(name: str) -> bool:
    try:
        result = (
            get_client()
            .table("groups")
            .update({"active": False})
            .ilike("name", name)
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        logger.error(f"Error removing group '{name}': {e}")
        return False


def log_message(content: str, groups_sent: list[str], approved_by: str) -> bool:
    try:
        get_client().table("messages").insert(
            {
                "content": content,
                "groups_sent": groups_sent,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "approved_by": approved_by,
            }
        ).execute()
        return True
    except Exception as e:
        logger.error(f"Error logging message: {e}")
        return False


def get_message_history(limit: int = 5) -> list[dict]:
    try:
        return (
            get_client()
            .table("messages")
            .select("*")
            .order("sent_at", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        return []
