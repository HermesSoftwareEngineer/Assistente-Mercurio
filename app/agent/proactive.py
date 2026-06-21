"""
Proactive agent — headless LLM execution triggered by the scheduler.

vault_check()               — reads vault state and acts autonomously
vault_check_with_response() — called when a contact replies to a task-related cobrança
"""

import json
import logging
import os
from datetime import datetime

from langsmith import traceable

logger = logging.getLogger(__name__)

MODEL = "deepseek-v4-flash"
MAX_TOOL_CALLS = 20

_OWNER_PHONE = "".join(c for c in os.environ.get("AUTHORIZED_NUMBER", "") if c.isdigit())


def _get_llm():
    import httpx
    from langsmith.wrappers import wrap_openai
    from openai import OpenAI

    verify_ssl = os.environ.get("DISABLE_SSL", "").lower() != "true"
    return wrap_openai(OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
        http_client=httpx.Client(verify=verify_ssl),
    ))


def _today() -> str:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/Fortaleza")).strftime("%Y-%m-%d")


def _now_str() -> str:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/Fortaleza")).strftime("%H:%M")


def _read_vault_state() -> tuple[str, str, str]:
    """Return (tarefas, log_hoje, regras) from vault."""
    from app.services.obsidian import read_note
    today = _today()
    tarefas = read_note("mercurio/Tarefas.md") or "(sem tarefas registradas)"
    log_hoje = read_note(f"mercurio/logs/{today}.md") or "(nenhuma ação registrada hoje)"
    regras = read_note("mercurio/instrucoes/RegrasGerais.md") or ""
    return tarefas, log_hoje, regras


@traceable(name="vault_check")
def vault_check() -> None:
    """Headless proactive run: reads vault, decides, acts, logs."""
    if not _OWNER_PHONE:
        logger.warning("vault_check: AUTHORIZED_NUMBER not set — skipping")
        return

    from app.agent.prompts import get_proactive_prompt
    from app.agent.tools import TOOLS, execute_tool

    tarefas, log_hoje, regras = _read_vault_state()
    today = _today()
    hora = _now_str()

    system_prompt = get_proactive_prompt(
        hora=hora,
        data=today,
        tarefas=tarefas,
        log_hoje=log_hoje,
        regras=regras,
    )

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    llm = _get_llm()

    tool_count = 0
    while tool_count < MAX_TOOL_CALLS:
        response = llm.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            content = msg.content or ""
            logger.info(f"vault_check: done after {tool_count} tool calls. LLM: {content[:200]}")
            return

        messages.append(msg)

        for tc in msg.tool_calls:
            result = execute_tool(tc.function.name, json.loads(tc.function.arguments), _OWNER_PHONE)
            tool_count += 1
            logger.info(f"vault_check [tool:{tc.function.name}] ({tool_count}/{MAX_TOOL_CALLS}) → {result[:120]}")
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

            if tool_count >= MAX_TOOL_CALLS:
                logger.warning("vault_check: MAX_TOOL_CALLS reached — stopping")
                return


def organize_memory() -> None:
    """Periodic vault maintenance: find phantom links and potential duplicates."""
    import re
    from pathlib import Path as _Path
    from app.services.obsidian import list_notes, read_note as _read, write_note as _write

    logger.info("organize_memory: starting")
    all_notes = list_notes()
    stems = {_Path(n).stem.lower(): n for n in all_notes}

    phantom: list[dict] = []
    duplicates: list[dict] = []

    for note_path in all_notes:
        content = _read(note_path) or ""
        for link in re.findall(r'\[\[([^\]|#]+)\]\]', content):
            link_clean = link.strip()
            if link_clean.lower() not in stems:
                phantom.append({"link": link_clean, "source": note_path})

    note_names = list(stems.keys())
    for i, name_a in enumerate(note_names):
        for name_b in note_names[i + 1:]:
            if len(name_a) > 3 and len(name_b) > 3:
                if (name_a in name_b or name_b in name_a) and name_a != name_b:
                    duplicates.append({"a": stems[name_a], "b": stems[name_b]})

    today = _today()
    lines = [
        "# Sugestões de Organização",
        f"<!-- Gerado automaticamente — {today} -->",
        "",
    ]
    if phantom:
        lines += ["## Links Fantasma", ""]
        for item in phantom:
            lines.append(f"- `[[{item['link']}]]` referenciado em `{item['source']}` — nota não existe")
        lines.append("")
    if duplicates:
        lines += ["## Possíveis Duplicatas", ""]
        for item in duplicates:
            lines.append(f"- `{item['a']}` e `{item['b']}` podem ser a mesma entidade")
        lines.append("")
    if not phantom and not duplicates:
        lines += ["## Tudo OK", "", f"Nenhuma inconsistência encontrada em {today}."]

    _write("07 - Mercurio/organize_suggestions.md", "\n".join(lines))

    summary_parts = []
    if phantom:
        summary_parts.append(f"{len(phantom)} link(s) fantasma")
    if duplicates:
        summary_parts.append(f"{len(duplicates)} possível(is) duplicata(s)")

    if summary_parts and _OWNER_PHONE:
        from app.services.evolution import send_message as _send
        msg = (
            f"🗂 *Revisão do vault concluída.*\n"
            f"Encontrei: {', '.join(summary_parts)}.\n"
            f"Veja as sugestões no painel admin."
        )
        _send(_OWNER_PHONE, msg)

    logger.info(f"organize_memory: {len(phantom)} phantom links, {len(duplicates)} duplicates")


def vault_check_with_response(phone: str, message: str) -> None:
    """Called when a contact replies to a task-related message.

    Appends the reply to today's log so vault_check can see it, then
    triggers a proactive run so the LLM can update Tarefas.md and respond.
    """
    from app.services.obsidian import append_to_note

    today = _today()
    hora = _now_str()
    log_path = f"mercurio/logs/{today}.md"
    log_entry = f"\n**{hora}** — Resposta de +{phone}: {message}"
    append_to_note(log_path, log_entry, separator="\n")

    logger.info(f"vault_check_with_response: logged reply from {phone}, triggering vault_check")
    vault_check()
