import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("startup")


def register_webhook() -> None:
    base_url = os.environ.get("EVOLUTION_API_URL", "").rstrip("/")
    api_key = os.environ.get("EVOLUTION_API_KEY", "")
    instance = os.environ.get("EVOLUTION_INSTANCE", "")
    webhook_url = os.environ.get("WEBHOOK_URL", "")

    if not all([base_url, api_key, instance, webhook_url]):
        logger.warning("register_webhook: WEBHOOK_URL ou variáveis da Evolution não configuradas — pulando")
        return

    headers = {"apikey": api_key, "Content-Type": "application/json"}

    # Verifica se a instância existe; cria se não existir
    try:
        resp = requests.get(
            f"{base_url}/instance/{instance}/connectionState",
            headers=headers,
            timeout=10,
        )
        data = resp.json() if resp.ok else {}
        if resp.status_code == 404 or not data.get("state"):
            logger.info(f"register_webhook: instância '{instance}' não encontrada — criando...")
            create = requests.post(
                f"{base_url}/instance/create",
                headers=headers,
                json={"instanceName": instance, "qrcode": True},
                timeout=10,
            )
            create.raise_for_status()
            logger.info(f"register_webhook: instância '{instance}' criada")
        else:
            logger.info(f"register_webhook: instância '{instance}' já existe (state={data.get('state')})")
    except requests.RequestException as e:
        logger.error(f"register_webhook: erro ao verificar/criar instância: {e}")

    # Registra o webhook
    try:
        resp = requests.put(
            f"{base_url}/webhook/set/{instance}",
            headers=headers,
            json={
                "url": webhook_url,
                "enabled": True,
                "events": ["MESSAGES_UPSERT"],
            },
            timeout=10,
        )
        resp.raise_for_status()
        logger.info(f"register_webhook: webhook registrado → {webhook_url}")
    except requests.RequestException as e:
        logger.error(f"register_webhook: erro ao registrar webhook: {e}")


if __name__ == "__main__":
    register_webhook()

    from app.main import app, startup_polling

    startup_polling()
    app.run(host="0.0.0.0", port=5000, debug=False)
