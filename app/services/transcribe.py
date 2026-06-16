import base64
import logging

from app.services.google_client import get_client

logger = logging.getLogger(__name__)


def transcribe_audio(audio_base64: str, mimetype: str = "audio/ogg") -> str | None:
    try:
        from google.genai import types
        audio_bytes = base64.b64decode(audio_base64)
        response = get_client().models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=audio_bytes, mime_type=mimetype),
                "Transcreva este áudio em português brasileiro. Retorne apenas o texto transcrito, sem comentários.",
            ],
        )
        text = response.text.strip()
        logger.info(f"Transcription ({len(audio_bytes)} bytes): {text[:100]}")
        return text or None
    except Exception as e:
        logger.error(f"Transcription error: {e}", exc_info=True)
        return None
