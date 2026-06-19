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
            .select("id, number, name, active, created_at")
            .order("created_at")
            .execute()
            .data
            or []
        )
    except Exception as e:
        logger.error(f"Error fetching contacts: {e}")
        return []


def patch_contact(number: str, active: bool | None = None, name: str | None = None) -> bool:
    try:
        updates: dict = {}
        if active is not None:
            updates["active"] = active
        if name is not None:
            updates["name"] = name
        if not updates:
            return True
        result = get_client().table("authorized_contacts").update(updates).eq("number", number).execute()
        return bool(result.data)
    except Exception as e:
        logger.error(f"Error patching contact '{number}': {e}")
        return False


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


def get_all_settings() -> list[dict]:
    try:
        return get_client().table("app_settings").select("*").order("key").execute().data or []
    except Exception as e:
        logger.error(f"Error fetching settings: {e}")
        return []


def get_conversation_session(phone: str) -> dict | None:
    try:
        result = (
            get_client()
            .table("conversation_sessions")
            .select("*")
            .eq("phone", phone)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Error fetching session for {phone}: {e}")
        return None


def upsert_conversation_session(phone: str, mode: str, transferred_by: str = "agent") -> bool:
    try:
        payload: dict = {"phone": phone, "mode": mode, "handoff_msg_sent": mode == "human"}
        if mode == "human":
            payload["transferred_at"] = datetime.now(timezone.utc).isoformat()
            payload["transferred_by"] = transferred_by
        else:
            payload["transferred_at"] = None
            payload["transferred_by"] = None
        get_client().table("conversation_sessions").upsert(payload, on_conflict="phone").execute()
        return True
    except Exception as e:
        logger.error(f"Error upserting session for {phone}: {e}")
        return False


def list_conversation_sessions() -> list[dict]:
    try:
        return get_client().table("conversation_sessions").select("*").execute().data or []
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        return []


def get_prompt(key: str) -> str:
    """Returns prompt content from DB, or '' if not found (caller falls back to hardcoded)."""
    try:
        result = (
            get_client()
            .table("prompts")
            .select("content")
            .eq("key", key)
            .limit(1)
            .execute()
        )
        return result.data[0]["content"] if result.data else ""
    except Exception as e:
        logger.error(f"Error fetching prompt '{key}': {e}")
        return ""


def set_prompt(key: str, content: str) -> bool:
    try:
        get_client().table("prompts").upsert(
            {"key": key, "content": content, "updated_at": datetime.now(timezone.utc).isoformat()},
            on_conflict="key",
        ).execute()
        return True
    except Exception as e:
        logger.error(f"Error saving prompt '{key}': {e}")
        return False


def get_all_prompts() -> list[dict]:
    try:
        return get_client().table("prompts").select("key, content, updated_at").order("key").execute().data or []
    except Exception as e:
        logger.error(f"Error fetching all prompts: {e}")
        return []


def list_conversations_summary() -> list[dict]:
    """Returns one summary row per phone: name, message count, last message, mode."""
    try:
        histories = (
            get_client()
            .table("conversation_history")
            .select("phone, messages, updated_at")
            .order("updated_at", desc=True)
            .execute()
            .data or []
        )
        contacts_map = {c["number"]: c for c in get_contacts()}
        sessions_map = {s["phone"]: s for s in list_conversation_sessions()}

        result = []
        for h in histories:
            phone = h["phone"]
            msgs: list = h.get("messages") or []
            contact = contacts_map.get(phone, {})
            sess = sessions_map.get(phone, {})

            last_msg = ""
            for m in reversed(msgs):
                if m.get("content"):
                    last_msg = m["content"][:120]
                    break

            result.append({
                "phone": phone,
                "name": contact.get("name", ""),
                "message_count": len(msgs),
                "last_message": last_msg,
                "mode": sess.get("mode", "bot"),
                "transferred_at": sess.get("transferred_at"),
                "transferred_by": sess.get("transferred_by"),
                "updated_at": h.get("updated_at"),
            })
        return result
    except Exception as e:
        logger.error(f"Error listing conversations summary: {e}")
        return []


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
