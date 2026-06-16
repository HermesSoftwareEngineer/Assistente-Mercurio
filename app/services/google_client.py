import os

import httpx
from google import genai
from google.genai.types import HttpOptions

_client: genai.Client | None = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        verify_ssl = os.environ.get("DISABLE_SSL", "").lower() != "true"
        http_options = HttpOptions(httpxClient=httpx.Client(verify=verify_ssl))
        _client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"], http_options=http_options)
    return _client
