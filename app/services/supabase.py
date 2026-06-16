import os
import logging
from datetime import datetime, timezone
import httpx
from supabase import create_client, Client, ClientOptions

logger = logging.getLogger(__name__)

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_KEY", "")
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
        verify_ssl = os.environ.get("DISABLE_SSL", "").lower() != "true"
        options = ClientOptions(httpx_client=httpx.Client(verify=verify_ssl))
        _client = create_client(url, key, options=options)
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


def get_contacts() -> list[dict]:
    try:
        return (
            get_client()
            .table("authorized_contacts")
            .select("number, name")
            .order("created_at")
            .execute()
            .data
            or []
        )
    except Exception as e:
        logger.error(f"Error fetching contacts: {e}")
        return []


def add_contact(number: str, name: str = "") -> bool:
    try:
        get_client().table("authorized_contacts").upsert(
            {"number": number, "name": name}, on_conflict="number"
        ).execute()
        return True
    except Exception as e:
        logger.error(f"Error adding contact '{number}': {e}")
        return False


def remove_contact(number: str) -> bool:
    try:
        get_client().table("authorized_contacts").delete().eq("number", number).execute()
        return True
    except Exception as e:
        logger.error(f"Error removing contact '{number}': {e}")
        return False


def save_conversation_history(phone: str, messages: list[dict], session_id: str) -> bool:
    try:
        get_client().table("conversation_history").upsert(
            {
                "phone": phone,
                "messages": messages,
                "session_id": session_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="phone",
        ).execute()
        return True
    except Exception as e:
        logger.error(f"Error saving history for {phone}: {e}")
        return False


def load_conversation_history(phone: str) -> tuple[list[dict], str]:
    """Returns (messages, session_id). session_id is '' when no history exists."""
    try:
        result = (
            get_client()
            .table("conversation_history")
            .select("messages, session_id")
            .eq("phone", phone)
            .limit(1)
            .execute()
        )
        if result.data:
            row = result.data[0]
            return row["messages"], row.get("session_id", "")
        return [], ""
    except Exception as e:
        logger.error(f"Error loading history for {phone}: {e}")
        return [], ""


def delete_conversation_history(phone: str) -> bool:
    try:
        get_client().table("conversation_history").delete().eq("phone", phone).execute()
        return True
    except Exception as e:
        logger.error(f"Error deleting history for {phone}: {e}")
        return False


def get_setting(key: str, default: str = "") -> str:
    try:
        result = get_client().table("app_settings").select("value").eq("key", key).limit(1).execute()
        return result.data[0]["value"] if result.data else default
    except Exception as e:
        logger.error(f"Error fetching setting '{key}': {e}")
        return default


def set_setting(key: str, value: str) -> bool:
    try:
        get_client().table("app_settings").upsert({"key": key, "value": value}, on_conflict="key").execute()
        return True
    except Exception as e:
        logger.error(f"Error saving setting '{key}': {e}")
        return False
