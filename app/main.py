import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from app.agent.graph import run_agent
from app.services.evolution import send_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

AUTHORIZED_NUMBER = os.environ.get("AUTHORIZED_NUMBER", "")


def _normalize(number: str) -> str:
    """Strip everything except digits."""
    return "".join(c for c in number if c.isdigit())


def _extract(payload: dict) -> tuple[str, str] | None:
    """Return (phone, text) from Evolution API webhook payload, or None."""
    try:
        data = payload.get("data", {})
        key = data.get("key", {})

        if key.get("fromMe"):
            return None

        remote_jid: str = key.get("remoteJid", "")

        # Ignore group messages (only handle direct messages to the bot)
        if "@g.us" in remote_jid:
            return None

        message = data.get("message", {})
        text = (
            message.get("conversation")
            or message.get("extendedTextMessage", {}).get("text")
            or ""
        ).strip()

        if not text:
            return None

        phone = remote_jid.split("@")[0]
        return phone, text

    except Exception as e:
        logger.warning(f"Could not parse webhook payload: {e}")
        return None


@app.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_webhook():
    payload = request.get_json(silent=True) or {}

    event = payload.get("event", "")
    if event not in ("messages.upsert", "message.received"):
        return jsonify({"status": "ignored"}), 200

    extracted = _extract(payload)
    if not extracted:
        return jsonify({"status": "ignored"}), 200

    phone, text = extracted

    if AUTHORIZED_NUMBER and _normalize(phone) != _normalize(AUTHORIZED_NUMBER):
        logger.warning(f"Blocked unauthorized sender: {phone}")
        return jsonify({"status": "unauthorized"}), 200

    logger.info(f"[{phone}] {text[:80]}")

    response = run_agent(phone, text)

    if response:
        send_message(phone, response)

    return jsonify({"status": "ok"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
