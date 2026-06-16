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


def send_presence(number: str, presence: str = "composing") -> None:
    """Send a presence update (e.g. 'composing' for typing indicator)."""
    if not all([EVOLUTION_API_URL, EVOLUTION_API_KEY, EVOLUTION_INSTANCE]):
        return

    url = f"{EVOLUTION_API_URL}/chat/sendPresence/{EVOLUTION_INSTANCE}"
    payload = {"number": number, "options": {"presence": presence}}

    try:
        requests.post(url, json=payload, headers=_headers(), timeout=10)
    except requests.RequestException as e:
        logger.warning(f"Failed to send presence to {number}: {e}")


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
        body = e.response.text if hasattr(e, "response") and e.response is not None else ""
        logger.error(f"Failed to send message to {number}: {e} | body: {body}")
        return False


def send_group_message(jid: str, text: str) -> bool:
    """Send a text message to a group by JID."""
    return send_message(jid, text)


def download_media_base64(message_data: dict) -> tuple[str, str] | None:
    """Download media from a webhook message. Returns (base64, mimetype) or None."""
    if not all([EVOLUTION_API_URL, EVOLUTION_API_KEY, EVOLUTION_INSTANCE]):
        return None

    url = f"{EVOLUTION_API_URL}/chat/getBase64FromMediaMessage/{EVOLUTION_INSTANCE}"
    payload = {"message": message_data, "convertToMp4": False}

    try:
        response = requests.post(url, json=payload, headers=_headers(), timeout=30)
        response.raise_for_status()
        data = response.json()
        b64 = data.get("base64") or data.get("data")
        if not b64:
            logger.error(f"No base64 in media response: {data}")
            return None
        audio_msg = (
            message_data.get("message", {}).get("audioMessage")
            or message_data.get("message", {}).get("pttMessage")
            or {}
        )
        mimetype = audio_msg.get("mimetype", "audio/ogg; codecs=opus").split(";")[0]
        return b64, mimetype
    except requests.RequestException as e:
        body = e.response.text if hasattr(e, "response") and e.response is not None else ""
        logger.error(f"Failed to download media: {e} | body: {body}")
        return None
