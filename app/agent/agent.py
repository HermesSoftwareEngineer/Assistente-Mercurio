import json
import logging
import os
import uuid
from datetime import datetime

import httpx
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree
from langsmith.wrappers import wrap_openai
from openai import OpenAI

from app.agent.prompts import build_system_prompt
from app.agent.tools import TOOLS, TOOLS_NON_OWNER, execute_tool
from app.services.obsidian import read_note
from app.services.supabase import (
    delete_conversation_history,
    load_conversation_history,
    save_conversation_history,
)

logger = logging.getLogger(__name__)

MODEL = "deepseek-v4-flash"
MAX_HISTORY = 40
WARN_AT = 34
MAX_TOOL_CALLS = 30
NOTIFY_EVERY = 5

_llm: OpenAI | None = None
_history: dict[str, list] = {}
_session_ids: dict[str, str] = {}   # phone → current session_id for LangSmith
_pending_reset: dict[str, str] = {}  # phone → summary awaiting save confirmation

_OWNER_PHONE = "".join(c for c in os.environ.get("AUTHORIZED_NUMBER", "") if c.isdigit())


def _get_llm() -> OpenAI:
    global _llm
    if _llm is None:
        verify_ssl = os.environ.get("DISABLE_SSL", "").lower() != "true"
        _llm = wrap_openai(OpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com",
            http_client=httpx.Client(verify=verify_ssl),
        ))
    return _llm


def _load_vault_context() -> str:
    parts = []
    for path, label in [
        ("00 - Contexto Pessoal/Hermes.md", "Hermes"),
        ("04 - Referências/Contatos.md", "Contatos"),
        ("00 - Contexto Pessoal/Igreja.md", "Igreja"),
    ]:
        content = read_note(path).strip()
        if content:
            parts.append(f"### {label}\n{content}")
    return "\n\n".join(parts)


def _new_session_id() -> str:
    return uuid.uuid4().hex


def reset_session(phone: str) -> None:
    _history.pop(phone, None)
    _session_ids.pop(phone, None)
    _pending_reset.pop(phone, None)
    delete_conversation_history(phone)


def _generate_summary(history: list[dict]) -> str:
    turns = [m for m in history if m["role"] in ("user", "assistant")]
    transcript = "\n".join(
        f"{'Usuário' if m['role'] == 'user' else 'Mercúrio'}: {m['content'][:300]}"
        for m in turns
    )
    response = _get_llm().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Você gera resumos concisos de conversas em português brasileiro."},
            {"role": "user", "content": f"Resuma esta conversa em 3 a 5 pontos principais:\n\n{transcript}"},
        ],
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()


def _save_conversation(phone: str, summary: str) -> None:
    from app.services.obsidian import write_note
    caller = "".join(c for c in phone if c.isdigit())
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    write_note(
        f"05 - Conversas/{date} - {caller}.md",
        f"# Conversa {date}\n\n**Número:** +{caller}\n\n## Resumo\n\n{summary}\n",
    )
    logger.info(f"Conversation saved to vault for {caller}")


@traceable(name="run_agent")
def run_agent(phone: str, message: str) -> str:
    caller = "".join(c for c in phone if c.isdigit())
    is_owner = bool(_OWNER_PHONE and caller == _OWNER_PHONE)

    # Handle pending save confirmation
    if phone in _pending_reset:
        summary = _pending_reset.pop(phone)
        if any(w in message.lower() for w in ("sim", "salva", "salvar", "yes", "quero", "pode")):
            _save_conversation(phone, summary)
            return "✅ Resumo salvo no vault! Pode continuar."
        return "Ok, resumo descartado. Pode continuar."

    # Load from DB on first message after server restart
    if phone not in _history:
        messages_db, session_id_db = load_conversation_history(phone)
        _history[phone] = messages_db
        # Restore session_id if continuing an existing conversation, else start fresh
        _session_ids[phone] = session_id_db if session_id_db else _new_session_id()

    # Assign a new session_id if this is genuinely a fresh conversation (no history)
    if phone not in _session_ids:
        _session_ids[phone] = _new_session_id()

    run = get_current_run_tree()
    if run:
        run.metadata.update({"thread_id": _session_ids[phone], "is_owner": is_owner})

    history = _history[phone]

    # Auto-reset at limit
    if len(history) >= MAX_HISTORY:
        logger.info(f"[{phone}] History limit reached — generating summary")
        summary = _generate_summary(history)
        _pending_reset[phone] = summary
        _history[phone] = []
        _session_ids[phone] = _new_session_id()  # new thread in LangSmith after reset
        return (
            f"⚠️ *Limite da conversa atingido* ({MAX_HISTORY} mensagens).\n\n"
            f"📝 *Resumo:*\n{summary}\n\n"
            "Deseja salvar este resumo no vault? Responda *sim* para salvar."
        )

    history.append({"role": "user", "content": message})

    vault_context = _load_vault_context() if is_owner else ""
    messages = [{"role": "system", "content": build_system_prompt(is_owner, caller, vault_context, _OWNER_PHONE)}] + history

    kwargs: dict = {"model": MODEL, "messages": messages}
    if is_owner:
        kwargs["tools"] = TOOLS
        kwargs["tool_choice"] = "auto"
    else:
        kwargs["tools"] = TOOLS_NON_OWNER
        kwargs["tool_choice"] = "auto"

    try:
        tool_count = 0

        while True:
            response = _get_llm().chat.completions.create(**kwargs)
            msg = response.choices[0].message

            if not msg.tool_calls:
                reply = msg.content or ""
                history.append({"role": "assistant", "content": reply})
                _history[phone] = history
                save_conversation_history(phone, history, _session_ids[phone])

                if len(history) >= WARN_AT:
                    remaining_turns = (MAX_HISTORY - len(history)) // 2
                    reply += f"\n\n_⚠️ Restam aproximadamente {remaining_turns} turnos nesta conversa antes do reset._"

                return reply

            messages.append(msg)

            for tc in msg.tool_calls:
                is_last = tool_count >= MAX_TOOL_CALLS - 1
                result = execute_tool(
                    tc.function.name,
                    json.loads(tc.function.arguments),
                    phone,
                )
                tool_count += 1
                logger.info(f"[tool:{tc.function.name}] ({tool_count}/{MAX_TOOL_CALLS}) → {result[:120]}")

                if is_last:
                    result += (
                        f"\n\n⚠️ [Sistema] Você atingiu o limite de {MAX_TOOL_CALLS} operações. "
                        "Responda ao usuário agora com o que você sabe. Não chame mais ferramentas."
                    )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

                if is_last:
                    kwargs["messages"] = messages
                    kwargs["tool_choice"] = "none"
                    final = _get_llm().chat.completions.create(**kwargs)
                    reply = final.choices[0].message.content or "❌ Não consegui concluir a operação."
                    history.append({"role": "assistant", "content": reply})
                    _history[phone] = history
                    save_conversation_history(phone, history, _session_ids[phone])
                    return reply

            # After all tool calls in this turn: inject status reminder every NOTIFY_EVERY
            if tool_count % NOTIFY_EVERY == 0:
                messages.append({
                    "role": "system",
                    "content": (
                        f"[Sistema] Você já usou {tool_count} ferramentas nesta solicitação. "
                        "Use `notify_user` para informar brevemente o usuário sobre o que você está fazendo antes de continuar."
                    ),
                })

            kwargs["messages"] = messages

    except Exception as e:
        logger.error(f"Agent error for {phone}: {e}", exc_info=True)
        return "❌ Erro interno. Tente novamente."
