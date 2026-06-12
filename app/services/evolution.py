import os
import logging
import requests

logger = logging.getLogger(__name__)

EVOLUTION_API_URL = os.environ.get("EVOLUTION_API_URL", "").rstrip("/")
EVOLUTION_API_KEY = os.environ.get("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.environ.get("EVOLUTION_INSTANCE", "")


def _headers() -> dict:
    return {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json",
    }


def send_message(number: str, text: str) -> bool:
    """Send a text message to a phone number or JID."""
    if not all([EVOLUTION_API_URL, EVOLUTION_API_KEY, EVOLUTION_INSTANCE]):
        logger.error("Evolution API not configured — check EVOLUTION_API_URL, EVOLUTION_API_KEY, EVOLUTION_INSTANCE")
        return False

    url = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}"
    payload = {"number": number, "text": text}

    try:
        response = requests.post(url, json=payload, headers=_headers(), timeout=30)
        response.raise_for_status()
        logger.info(f"Message sent to {number}")
        return True
    except requests.RequestException as e:
        logger.error(f"Failed to send message to {number}: {e}")
        return False


def send_group_message(jid: str, text: str) -> bool:
    """Send a text message to a group by JID."""
    return send_message(jid, text)
