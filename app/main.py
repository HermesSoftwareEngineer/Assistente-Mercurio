import logging
import os
import time

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

load_dotenv()

import base64
import os

import requests

from app.admin import admin_bp, _load_config
from app.api import api_bp
from app.agent.agent import run_agent, reset_session
from app.services.books import book_exists, save_book
from app.services.evolution import download_media_base64, send_message, send_presence
from app.services.obsidian import read_note, write_note
from app.services.pdf_processor import chunk_text, extract_text
from app.services.supabase import get_conversation_session, load_conversation_history, save_conversation_history
from app.services.transcribe import transcribe_audio

_EVOLUTION_API_URL = os.environ.get("EVOLUTION_API_URL", "").rstrip("/")
_EVOLUTION_API_KEY = os.environ.get("EVOLUTION_API_KEY", "")
_EVOLUTION_INSTANCE = os.environ.get("EVOLUTION_INSTANCE", "")
_AUTHORIZED_NUMBER = os.environ.get("AUTHORIZED_NUMBER", "")

_SISTEMA_NOTE = "00 - Contexto Pessoal/sistema.md"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def _read_last_restart() -> float:
    """Return the Unix timestamp of the previous startup from sistema.md, or 0.0 if absent."""
    content = read_note(_SISTEMA_NOTE)
    for line in content.splitlines():
        if line.startswith("ultimo_restart:"):
            try:
                return float(line.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                pass
    return 0.0


def _save_startup_timestamp(ts: float) -> None:
    content = read_note(_SISTEMA_NOTE)
    new_line = f"ultimo_restart: {ts}"
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("ultimo_restart:"):
            lines[i] = new_line
            write_note(_SISTEMA_NOTE, "\n".join(lines) + "\n")
            return
    lines.append(new_line)
    write_note(_SISTEMA_NOTE, "\n".join(lines) + "\n")


def _fetch_all_messages() -> list[dict]:
    if not all([_EVOLUTION_API_URL, _EVOLUTION_API_KEY, _EVOLUTION_INSTANCE]):
        logger.warning("startup_polling: Evolution API not fully configured — skipping")
        return []
    url = f"{_EVOLUTION_API_URL}/chat/findMessages/{_EVOLUTION_INSTANCE}"
    try:
        resp = requests.post(url, headers={"apikey": _EVOLUTION_API_KEY, "Content-Type": "application/json"}, json={}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("messages", "records", "data", "items"):
                val = data.get(key)
                if isinstance(val, list):
                    return val
        logger.warning(f"startup_polling: unexpected response structure: {type(data)} keys={list(data.keys()) if isinstance(data, dict) else 'n/a'}")
        return []
    except Exception as e:
        logger.error(f"startup_polling: failed to fetch messages: {e}")
        return []


def startup_polling() -> None:
    """Process messages received while the bot was offline."""
    logger.info("startup_polling: starting")

    last_restart = _read_last_restart()
    now = time.time()
    _save_startup_timestamp(now)

    if last_restart == 0.0:
        logger.info("startup_polling: no previous restart timestamp found — skipping replay")
        return

    messages = _fetch_all_messages()
    if not messages:
        logger.info("startup_polling: no messages returned from API")
        return

    messages.sort(key=lambda m: m.get("messageTimestamp", 0))

    # Index manual/bot replies by remoteJid so we can check per sender
    bot_replies: dict[str, list[float]] = {}
    for m in messages:
        if m.get("key", {}).get("fromMe"):
            jid = m.get("key", {}).get("remoteJid", "")
            if jid:
                bot_replies.setdefault(jid, []).append(float(m.get("messageTimestamp", 0)))

    # Incoming messages after last restart (individual chats only)
    incoming = [
        m for m in messages
        if not m.get("key", {}).get("fromMe")
        and "@g.us" not in m.get("key", {}).get("remoteJid", "")
        and m.get("messageTimestamp", 0) > last_restart
    ]

    if not incoming:
        logger.info("startup_polling: no pending messages after last restart")
        return

    # Skip if already replied to that sender (manually or by bot) after this message
    pending = [
        m for m in incoming
        if not any(
            bt > m.get("messageTimestamp", 0)
            for bt in bot_replies.get(m.get("key", {}).get("remoteJid", ""), [])
        )
    ]

    if not pending:
        logger.info("startup_polling: all messages already have replies")
        return

    config = _load_config()
    logger.info(f"startup_polling: processing {len(pending)} pending message(s)")

    for msg in pending:
        message_obj = msg.get("message", {})
        text = (
            message_obj.get("conversation")
            or message_obj.get("extendedTextMessage", {}).get("text")
            or ""
        ).strip()
        if not text:
            continue

        jid = msg.get("key", {}).get("remoteJid", "")
        phone = jid.split("@")[0]

        if not config.get("allow_all"):
            authorized = [_normalize(c["number"]) for c in config.get("contacts", []) if c.get("active", True)]
            if authorized and _normalize(phone) not in authorized:
                continue

        logger.info(f"startup_polling: replaying message from {phone}: {text[:80]}")
        try:
            response = run_agent(phone, text)
            if response:
                send_message(phone, response)
        except Exception as e:
            logger.error(f"startup_polling: error processing message: {e}", exc_info=True)

    logger.info("startup_polling: done")


app = Flask(__name__)
app.secret_key = os.environ.get("EVOLUTION_API_KEY", "mercurio-secret-key")
app.register_blueprint(admin_bp, url_prefix="/admin")
app.register_blueprint(api_bp, url_prefix="/api")
CORS(app, supports_credentials=True)


def _normalize(number: str) -> str:
    """Strip everything except digits."""
    return "".join(c for c in number if c.isdigit())


def _extract(payload: dict) -> tuple[str, str | None, dict | None] | None:
    """Return (phone, text_or_none, audio_data_or_none) from webhook payload, or None."""
    try:
        data = payload.get("data", {})
        key = data.get("key", {})

        if key.get("fromMe"):
            return None

        remote_jid: str = key.get("remoteJid", "")
        if "@g.us" in remote_jid:
            return None

        message = data.get("message", {})
        phone = remote_jid.split("@")[0]

        if "audioMessage" in message or "pttMessage" in message:
            return phone, None, data, None

        doc = message.get("documentMessage", {})
        if doc.get("mimetype") == "application/pdf":
            title = (data.get("message", {}).get("documentMessage", {}).get("caption")
                     or doc.get("fileName") or "Livro sem título")
            return phone, None, data, title

        text = (
            message.get("conversation")
            or message.get("extendedTextMessage", {}).get("text")
            or ""
        ).strip()

        if not text:
            return None

        return phone, text, None, None

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

    phone, text, audio_data, pdf_title = extracted

    config = _load_config()
    if not config.get("allow_all"):
        authorized = [_normalize(c["number"]) for c in config.get("contacts", []) if c.get("active", True)]
        if authorized and _normalize(phone) not in authorized:
            logger.warning(f"Blocked unauthorized sender: {phone}")
            return jsonify({"status": "unauthorized"}), 200

    if pdf_title:
        if book_exists(pdf_title):
            send_message(phone, f"📚 *{pdf_title}* já está indexado na biblioteca!")
            return jsonify({"status": "ok"}), 200
        send_message(phone, "📚 Recebi o PDF! Processando e indexando, aguarde...")
        result = download_media_base64(audio_data)
        if not result:
            send_message(phone, "❌ Não consegui baixar o PDF. Tente novamente.")
            return jsonify({"status": "ok"}), 200
        b64, _ = result
        try:
            pdf_bytes = base64.b64decode(b64)
            # Salva arquivo na biblioteca
            safe_name = "".join(c if c.isalnum() or c in " ._-" else "_" for c in pdf_title)
            lib_path = os.path.join(os.path.dirname(__file__), "..", "biblioteca", f"{safe_name}.pdf")
            with open(os.path.normpath(lib_path), "wb") as f:
                f.write(pdf_bytes)
            text_content, pages = extract_text(pdf_bytes)
            chunks = chunk_text(text_content)
            book_id = save_book(pdf_title, f"{safe_name}.pdf", pages, chunks)
            if book_id:
                send_message(phone, f"✅ *{pdf_title}* indexado!\n_{pages} páginas, {len(chunks)} trechos prontos para busca._")
            else:
                send_message(phone, "❌ Erro ao indexar o livro. Tente novamente.")
        except Exception as e:
            logger.error(f"PDF processing error: {e}", exc_info=True)
            send_message(phone, "❌ Erro ao processar o PDF.")
        return jsonify({"status": "ok"}), 200

    if audio_data:
        send_message(phone, "🎧 Estou ouvindo seu áudio...")
        result = download_media_base64(audio_data)
        if not result:
            send_message(phone, "❌ Não consegui baixar o áudio. Tente novamente.")
            return jsonify({"status": "ok"}), 200
        b64, mimetype = result
        text = transcribe_audio(b64, mimetype)
        if not text:
            send_message(phone, "❌ Não consegui transcrever o áudio. Tente enviar como texto.")
            return jsonify({"status": "ok"}), 200
        logger.info(f"[{phone}] 🎙️ {text[:80]}")

    if text.strip() == "/reset":
        reset_session(phone)
        send_message(phone, "🔄 Conversa reiniciada!")
        return jsonify({"status": "ok"}), 200

    conv_session = get_conversation_session(phone)
    if conv_session and conv_session.get("mode") == "human":
        msgs, sid = load_conversation_history(phone)
        msgs.append({"role": "user", "content": text})
        save_conversation_history(phone, msgs, sid or "")
        return jsonify({"status": "ok"}), 200

    send_presence(phone, "composing")
    response = run_agent(phone, text)
    send_presence(phone, "paused")

    if response:
        send_message(phone, response)

    return jsonify({"status": "ok"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"}), 200


if __name__ == "__main__":
    startup_polling()
    app.run(host="0.0.0.0", port=5000, debug=False)

