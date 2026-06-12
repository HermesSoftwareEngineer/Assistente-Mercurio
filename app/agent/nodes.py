import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from openai import OpenAI

from app.agent.prompts import CLASSIFY_SYSTEM_PROMPT, CONVERSATIONAL_SYSTEM_PROMPT, DRAFT_SYSTEM_PROMPT
from app.services.evolution import send_group_message
from app.services.obsidian import (
    append_to_note,
    read_note,
    search_notes,
    write_note,
)
from app.services.supabase import (
    add_group,
    get_group_by_name,
    get_groups,
    get_message_history,
    log_message,
    remove_group,
)

if TYPE_CHECKING:
    from app.agent.graph import AgentState

logger = logging.getLogger(__name__)

MODEL = "deepseek-v4-flash"
_llm: OpenAI | None = None


def _get_llm() -> OpenAI:
    global _llm
    if _llm is None:
        # DISABLE_SSL=true only for local environments with corporate SSL proxies
        verify_ssl = os.environ.get("DISABLE_SSL", "").lower() != "true"
        _llm = OpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com",
            http_client=httpx.Client(verify=verify_ssl),
        )
    return _llm


def _chat(system: str, user: str, temperature: float = 0.7) -> str:
    response = _get_llm().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
    )
    return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Memory nodes
# ---------------------------------------------------------------------------

_CHURCH_KW = {
    "culto", "célula", "aviso", "retiro", "reunião", "pastor", "líder",
    "horário", "evento", "domingo", "sábado", "dízimo", "oferta",
    "membro", "batismo", "louvor", "grupo", "célula", "pregação",
}
_CONTACT_KW = {"contato", "telefone", "celular", "email", "endereço"}


def recall_memory(state: "AgentState") -> dict:
    """Load relevant vault context before processing the user message."""
    vault_path = os.environ.get("OBSIDIAN_VAULT_PATH")
    if not vault_path:
        return {"memory_context": ""}

    message_lower = state["user_message"].lower()
    parts: list[str] = []

    if any(kw in message_lower for kw in _CHURCH_KW):
        note = read_note("00 - Contexto Pessoal/Igreja.md")
        if note:
            parts.append(f"### Igreja\n{note[:1000]}")

    if any(kw in message_lower for kw in _CONTACT_KW):
        note = read_note("04 - Referências/Contatos.md")
        if note:
            parts.append(f"### Contatos\n{note[:600]}")

    already = {"00 - Contexto Pessoal/Igreja.md", "04 - Referências/Contatos.md"}
    for hit in search_notes(state["user_message"], max_results=2):
        # Skip sent-messages archive and already-loaded notes
        if hit["path"] not in already and not hit["path"].startswith("02 -"):
            parts.append(f"### {Path(hit['path']).stem}\n{hit['excerpt']}")

    return {"memory_context": "\n\n".join(parts)}


def save_memory(state: "AgentState") -> dict:
    """Persist relevant information to the vault after an action completes."""
    vault_path = os.environ.get("OBSIDIAN_VAULT_PATH")
    if not vault_path:
        return {}

    intent = state.get("intent", "")

    if intent in ("send", "approve") or (intent == "generate" and state.get("send_direct")):
        return _save_sent_message(state)

    if intent == "update_context":
        return _save_context_update(state)

    if intent == "add_task":
        return _save_task(state)

    if intent == "manage_groups":
        _sync_groups_to_vault(state)

    return {}


def _save_sent_message(state: "AgentState") -> dict:
    draft = state.get("draft", "")
    if not draft:
        return {}

    date = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H:%M")

    # First non-empty line, stripped of WhatsApp formatting chars
    title = next(
        (re.sub(r"[*_~`#]", "", ln).strip() for ln in draft.split("\n") if ln.strip()),
        "Aviso",
    )[:60]

    groups_str = ", ".join(state.get("target_groups") or ["todos os grupos"])

    content = (
        f"# {title}\n\n"
        f"**Data:** {date} às {time_str}  \n"
        f"**Grupos:** {groups_str}\n\n"
        "---\n\n"
        f"{draft}\n"
    )
    write_note(f"02 - Avisos Enviados/{date} {title}.md", content)
    return {}


def _note_for_topic(message: str) -> str:
    """Map message keywords to the most relevant vault note."""
    msg = message.lower()
    if any(k in msg for k in _CHURCH_KW):
        return "00 - Contexto Pessoal/Igreja.md"
    if any(k in msg for k in _CONTACT_KW):
        return "04 - Referências/Contatos.md"
    if any(k in msg for k in {"grupo", "@g.us", "jid"}):
        return "04 - Referências/Grupos WhatsApp.md"
    return "00 - Contexto Pessoal/Hermes.md"


def _save_context_update(state: "AgentState") -> dict:
    note_path = _note_for_topic(state["user_message"])
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"**{date}** — {state['user_message']}"
    append_to_note(note_path, entry)
    note_name = Path(note_path).stem
    return {"response": f"✅ Anotado em _{note_name}_!"}


def _save_task(state: "AgentState") -> dict:
    task = _chat(
        "Extraia apenas o texto da tarefa da mensagem abaixo. "
        "Retorne somente a tarefa, sem introdução, sem explicações.",
        state["user_message"],
    )
    date = datetime.now().strftime("%Y-%m-%d")
    entry = f"- [ ] {task} _(adicionado em {date})_"
    append_to_note("03 - Tarefas/Pendentes.md", entry, separator="\n")
    return {"response": f"✅ Tarefa adicionada:\n_{task}_"}


def _sync_groups_to_vault(state: "AgentState") -> None:
    """Rebuild the vault groups reference note from Supabase."""
    cl = state.get("classification", {})
    if cl.get("subaction") not in ("add", "remove"):
        return

    groups = get_groups(active_only=False)
    if not groups:
        return

    lines = ["# Grupos WhatsApp\n"]
    for g in groups:
        status = "✅" if g.get("active") else "❌"
        cat = f" [{g['category']}]" if g.get("category") else ""
        lines.append(f"{status} **{g['name']}**{cat}  \n`{g['jid']}`\n")

    write_note("04 - Referências/Grupos WhatsApp.md", "\n".join(lines))


# ---------------------------------------------------------------------------
# Existing nodes (updated to use memory context where relevant)
# ---------------------------------------------------------------------------


def classify_intent(state: "AgentState") -> dict:
    pending = state.get("draft")
    existing_groups = state.get("target_groups", [])

    user_prompt = f"""Mensagem: {state['user_message']}
Rascunho pendente: {pending or 'Nenhum'}

Retorne JSON:
{{
  "intent": "generate|send|approve|manage_groups|history|update_context|add_task|unknown",
  "send_direct": true|false,
  "target_groups": ["nome1"],
  "subaction": "list|add|remove|null",
  "group_name": "nome ou null",
  "group_jid": "jid ou null",
  "group_category": "categoria ou null"
}}"""

    try:
        raw = _chat(CLASSIFY_SYSTEM_PROMPT, user_prompt, temperature=0.0)
        start, end = raw.find("{"), raw.rfind("}") + 1
        parsed = json.loads(raw[start:end]) if start >= 0 and end > start else {}
    except Exception as e:
        logger.error(f"classify_intent error: {e}")
        parsed = {}

    new_groups = parsed.get("target_groups") or []
    return {
        "intent": parsed.get("intent", "unknown"),
        "send_direct": bool(parsed.get("send_direct", False)),
        "target_groups": new_groups if new_groups else existing_groups,
        "classification": parsed,
    }


def generate_draft(state: "AgentState") -> dict:
    context = state.get("memory_context", "")
    user_msg = state["user_message"]

    prompt = (
        f"Contexto relevante do vault:\n{context}\n\n---\nInstrução: {user_msg}"
        if context
        else user_msg
    )

    draft = _chat(DRAFT_SYSTEM_PROMPT, prompt)

    if state.get("send_direct"):
        return {"draft": draft}

    response = (
        f"📝 *Rascunho gerado:*\n\n{draft}\n\n"
        "---\n"
        "Responda *sim* para enviar, *não* para cancelar.\n"
        "Para grupos específicos: _\"envia para [grupo]\"_"
    )
    return {"draft": draft, "response": response}


def send_to_groups(state: "AgentState") -> dict:
    draft = state.get("draft")
    if not draft:
        return {"response": "❌ Nenhum rascunho pendente. Gere uma mensagem primeiro."}

    group_names = state.get("target_groups", [])

    if group_names:
        candidates = [get_group_by_name(n) for n in group_names]
        targets = [g for g in candidates if g]
    else:
        targets = [g for g in get_groups() if g.get("active")]

    if not targets:
        return {
            "response": (
                "❌ Nenhum grupo encontrado. "
                "Use _listar grupos_ para ver os disponíveis."
            )
        }

    sent_to = []
    for group in targets:
        if send_group_message(group["jid"], draft):
            sent_to.append(group["name"])

    if sent_to:
        log_message(draft, sent_to, state["phone"])
        response = f"✅ Mensagem enviada para: {', '.join(sent_to)}"
    else:
        response = "❌ Falha ao enviar. Verifique se a Evolution API está funcionando."

    return {"response": response}


def manage_groups(state: "AgentState") -> dict:
    cl = state.get("classification", {})
    subaction = cl.get("subaction") or "list"
    name = cl.get("group_name")
    jid = cl.get("group_jid")
    category = cl.get("group_category") or ""

    if subaction == "list":
        groups = get_groups(active_only=False)
        if not groups:
            return {"response": "📋 Nenhum grupo cadastrado ainda."}
        lines = ["📋 *Grupos cadastrados:*\n"]
        for g in groups:
            status = "✅" if g.get("active") else "❌"
            cat = f" [{g['category']}]" if g.get("category") else ""
            lines.append(f"{status} *{g['name']}*{cat}\n`{g['jid']}`")
        return {"response": "\n".join(lines)}

    if subaction == "add":
        if not name or not jid:
            return {
                "response": (
                    "❌ Informe nome e JID do grupo.\n"
                    "Exemplo: _cadastra grupo Jovens | 120363xxxxxx@g.us_"
                )
            }
        if add_group(name, jid, category):
            return {"response": f"✅ Grupo *{name}* cadastrado com sucesso!"}
        return {"response": "❌ Erro ao cadastrar grupo."}

    if subaction == "remove":
        if not name:
            return {"response": "❌ Informe o nome do grupo para remover."}
        if remove_group(name):
            return {"response": f"✅ Grupo *{name}* removido."}
        return {"response": f"❌ Grupo *{name}* não encontrado."}

    return {
        "response": (
            "ℹ️ O que deseja fazer com os grupos?\n"
            "• _listar grupos_\n"
            "• _cadastrar grupo [nome] | [JID]_\n"
            "• _remover grupo [nome]_"
        )
    }


def query_history(state: "AgentState") -> dict:
    messages = get_message_history(limit=5)
    if not messages:
        return {"response": "📊 Nenhum envio encontrado no histórico."}

    lines = ["📊 *Últimos envios:*\n"]
    for msg in messages:
        groups = ", ".join(msg.get("groups_sent") or [])
        sent_at = (msg.get("sent_at") or "")[:16].replace("T", " ")
        preview = msg.get("content", "")[:80]
        if len(msg.get("content", "")) > 80:
            preview += "…"
        lines.append(f"🕐 {sent_at}\n📤 {groups}\n💬 {preview}\n")

    return {"response": "\n".join(lines)}


def handle_unknown(state: "AgentState") -> dict:
    context = state.get("memory_context", "")
    user_msg = state["user_message"]

    prompt = (
        f"Contexto do vault:\n{context}\n\n---\nMensagem: {user_msg}"
        if context
        else user_msg
    )

    response = _chat(CONVERSATIONAL_SYSTEM_PROMPT, prompt)
    return {"response": response}
