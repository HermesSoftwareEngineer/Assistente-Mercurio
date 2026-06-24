import logging
import os
import re
from datetime import datetime
from pathlib import Path

import httpx
from langsmith import traceable
from langsmith.wrappers import wrap_openai
from openai import OpenAI

from app.agent.prompts import get_draft_prompt
from app.services.evolution import send_group_message, send_message as send_direct
from app.services.books import delete_book, delete_duplicate_books, list_books, search as search_books_db, save_book
from app.services.obsidian import append_to_note, delete_note, read_note as _obsidian_read, rename_note, search_notes, write_note as _obsidian_write
from app.services.pdf_processor import chunk_text, extract_text
from app.services.supabase import (
    add_group,
    get_group_by_name,
    get_groups,
    get_message_history,
    load_conversation_history,
    log_message,
    remove_group,
    save_conversation_history,
)

logger = logging.getLogger(__name__)
MODEL = "deepseek-v4-flash"

_llm: OpenAI | None = None


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


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

def _tool(name: str) -> dict:
    return next(t for t in _ALL_TOOLS if t["function"]["name"] == name)


TOOLS: list[dict] = []  # populated after _ALL_TOOLS is defined
TOOLS_NON_OWNER: list[dict] = []  # populated after _ALL_TOOLS is defined

_ALL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "generate_draft",
            "description": (
                "Gera um rascunho de mensagem formatada para WhatsApp. "
                "Use quando o usuário pedir para criar, gerar ou redigir uma mensagem ou aviso."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "Instrução completa para gerar a mensagem, com todo o contexto fornecido.",
                    }
                },
                "required": ["instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "description": "Envia uma mensagem para grupos do WhatsApp e registra no histórico.",
            "parameters": {
                "type": "object",
                "properties": {
                    "draft": {
                        "type": "string",
                        "description": "Texto completo da mensagem a enviar.",
                    },
                    "groups": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Nomes dos grupos de destino. Lista vazia = todos os grupos ativos.",
                    },
                },
                "required": ["draft", "groups"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_direct_message",
            "description": (
                "Envia uma mensagem direta para um contato específico via WhatsApp. "
                "Use para iniciar ou continuar uma conversa com uma pessoa pelo número de telefone."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "number": {
                        "type": "string",
                        "description": "Número de telefone com DDI e DDD, apenas dígitos. Ex: 5585999998888",
                    },
                    "text": {
                        "type": "string",
                        "description": "Texto da mensagem a enviar.",
                    },
                },
                "required": ["number", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_groups",
            "description": "Lista todos os grupos cadastrados.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_group",
            "description": "Cadastra um novo grupo de WhatsApp.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "jid": {"type": "string", "description": "Ex: 120363xxxxxx@g.us"},
                    "category": {"type": "string"},
                },
                "required": ["name", "jid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_group",
            "description": "Remove um grupo cadastrado.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_history",
            "description": "Busca o histórico dos últimos envios de mensagens.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Número de registros (padrão 5)."}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_contact",
            "description": (
                "Insere ou atualiza um contato na tabela de Contatos do vault. "
                "Use SEMPRE que o usuário mencionar um contato com nome + telefone, nome + cargo, ou qualquer combinação. "
                "Chame sem pedir confirmação."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name":  {"type": "string", "description": "Nome do contato."},
                    "phone": {"type": "string", "description": "Telefone/WhatsApp (apenas dígitos ou formatado). Deixe vazio se não informado."},
                    "role":  {"type": "string", "description": "Cargo, função ou relação (ex: 'Pastor', 'irmão de Hermes'). Deixe vazio se não informado."},
                    "notes": {"type": "string", "description": "Observações adicionais. Deixe vazio se não houver."},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_note",
            "description": (
                "Salva uma informação ou tarefa no vault Obsidian (memória persistente). "
                "Use proativamente para guardar fatos relevantes sobre Hermes, compromissos, preferências, "
                "eventos ou decisões mencionados na conversa. NÃO use para contatos — use upsert_contact."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Informação a salvar."},
                    "topic": {
                        "type": "string",
                        "enum": ["church", "work", "task", "general"],
                        "description": "Tópico: church=assuntos da igreja, work=trabalho/estudo, task=tarefa pendente, general=sobre Hermes.",
                    },
                },
                "required": ["content", "topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_note",
            "description": "Renomeia ou move uma nota dentro do vault Obsidian.",
            "parameters": {
                "type": "object",
                "properties": {
                    "old_path": {"type": "string", "description": "Caminho atual da nota. Ex: 03 - Tarefas/Pendentes.md"},
                    "new_path": {"type": "string", "description": "Novo caminho/nome da nota."},
                },
                "required": ["old_path", "new_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_note",
            "description": "Deleta permanentemente uma nota do vault Obsidian.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note_path": {"type": "string", "description": "Caminho da nota a deletar."},
                },
                "required": ["note_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_books",
            "description": "Busca semanticamente nos livros indexados. Use para responder perguntas baseadas no conteúdo de livros enviados. Cada trecho retornado cobre ~1 página; 3 trechos já fornecem contexto amplo para a maioria das perguntas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Pergunta ou trecho a buscar nos livros."},
                    "limit": {"type": "integer", "description": "Número de trechos a retornar (padrão 3). Aumente para 5 apenas se precisar de mais cobertura."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_books",
            "description": "Lista todos os livros indexados na biblioteca.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_book",
            "description": "Remove um livro e todos os seus trechos da biblioteca.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título (ou parte do título) do livro a remover."},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cleanup_duplicate_books",
            "description": "Remove entradas duplicadas de livros do banco de dados, mantendo a versão mais recente de cada título.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notify_user",
            "description": (
                "Envia uma mensagem de status ao usuário no WhatsApp informando o que você está fazendo. "
                "Use quando o sistema solicitar ou quando uma operação demorada está em andamento."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Mensagem de status curta para o usuário. Ex: 'Estou buscando nos livros indexados...'",
                    }
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_vault",
            "description": "Busca informações relevantes no vault Obsidian.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Termos de busca."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_chat",
            "description": "Lê o histórico de conversa de outro usuário com o assistente. Exclusivo para o Hermes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "Número de telefone do usuário (apenas dígitos). Ex: 558596688778",
                    },
                    "last_n": {
                        "type": "integer",
                        "description": "Quantas mensagens mais recentes exibir (padrão: todas).",
                    },
                },
                "required": ["phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_to_vault",
            "description": (
                "Salva informação no vault de forma inteligente — faz triagem automática para decidir "
                "se deve atualizar nota existente, criar nota nova ou adicionar a nota de contexto existente. "
                "Use este tool em vez de write_note para qualquer informação nova que o Hermes mencionar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Informação a salvar no vault.",
                    },
                    "hint": {
                        "type": "string",
                        "description": (
                            "Dica de contexto para a triagem. Ex: 'contato novo: Pedro Silva', "
                            "'evento de igreja', 'preferência do Hermes'. Quanto mais específico, melhor."
                        ),
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transfer_to_human",
            "description": (
                "Transfere a conversa para atendimento humano direto com o Hermes. "
                "Use quando não souber responder, a situação exigir julgamento pessoal, "
                "ou o usuário pedir explicitamente para falar com uma pessoa."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Motivo interno da transferência (enviado ao Hermes como notificação).",
                    },
                    "message_to_user": {
                        "type": "string",
                        "description": "Mensagem enviada ao usuário confirmando a transferência. Deve ser cordial e informar que o Hermes entrará em contato.",
                    },
                },
                "required": ["reason", "message_to_user"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_note",
            "description": (
                "Lê o conteúdo completo de uma nota do vault pelo caminho. "
                "Use para ler mercurio/Tarefas.md, logs, instruções ou qualquer nota específica."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Caminho relativo ao vault. Ex: mercurio/Tarefas.md",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_note",
            "description": (
                "Cria ou sobrescreve uma nota no vault pelo caminho. "
                "Use para atualizar mercurio/Tarefas.md, escrever logs do dia ou criar notas de instrução. "
                "ATENÇÃO: sobrescreve o conteúdo anterior inteiramente — leia antes de editar partes específicas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Caminho relativo ao vault. Ex: mercurio/logs/2026-06-19.md",
                    },
                    "content": {
                        "type": "string",
                        "description": "Conteúdo completo da nota.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_task",
            "description": (
                "Agenda uma tarefa pontual para um horário específico no vault. "
                "Use quando o Hermes pedir para cobrar alguém, verificar algo ou executar uma ação num horário definido. "
                "Só chame com horário preciso e futuro — se ambíguo ou no passado, pergunte antes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Descrição curta da tarefa. Ex: Cobrar roteiro do Carlos",
                    },
                    "due_at": {
                        "type": "string",
                        "description": "Data e hora ISO 8601. Ex: 2026-06-19T19:00:00",
                    },
                    "details": {
                        "type": "string",
                        "description": "Detalhes: quem contatar, o que verificar, mensagem a enviar etc.",
                    },
                    "contact_phone": {
                        "type": "string",
                        "description": "Telefone do contato a acionar (somente dígitos), se aplicável.",
                    },
                    "context_links": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Caminhos de notas do vault com contexto relevante para esta tarefa. "
                            "Ex: ['06 - Igreja/Células.md', 'mercurio/Tarefas.md']. "
                            "O agente proativo lerá esses arquivos antes de agir."
                        ),
                    },
                },
                "required": ["title", "due_at"],
            },
        },
    },
]

TOOLS = _ALL_TOOLS
TOOLS_NON_OWNER = [_tool("send_direct_message"), _tool("transfer_to_human")]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _generate_draft(instruction: str) -> str:
    resp = _get_llm().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": get_draft_prompt()},
            {"role": "user", "content": instruction},
        ],
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()


def _send_message(draft: str, groups: list[str], phone: str) -> str:
    if groups:
        targets = [g for g in (get_group_by_name(n) for n in groups) if g]
    else:
        targets = [g for g in get_groups() if g.get("active")]

    if not targets:
        return "Nenhum grupo encontrado. Use list_groups para ver os disponíveis."

    sent_to = [g["name"] for g in targets if send_group_message(g["jid"], draft)]

    if not sent_to:
        return "Falha ao enviar. Verifique se a Evolution API está funcionando."

    log_message(draft, sent_to, phone)
    _save_sent_to_vault(draft, sent_to)
    return f"Enviado para: {', '.join(sent_to)}"


def _save_sent_to_vault(draft: str, sent_to: list[str]) -> None:
    if not os.environ.get("OBSIDIAN_VAULT_PATH"):
        return
    date = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H:%M")
    title = next(
        (re.sub(r"[*_~`#]", "", ln).strip() for ln in draft.split("\n") if ln.strip()),
        "Mensagem",
    )[:60]
    write_note(
        f"02 - Avisos Enviados/{date} {title}.md",
        f"# {title}\n\n**Data:** {date} às {time_str}  \n**Grupos:** {', '.join(sent_to)}\n\n---\n\n{draft}\n",
    )


def _send_direct_message(number: str, text: str) -> str:
    import uuid
    number = "".join(c for c in number if c.isdigit())
    if not number:
        return "Número inválido."
    if send_direct(number, text):
        msgs, sid = load_conversation_history(number)
        msgs.append({"role": "assistant", "content": text})
        save_conversation_history(number, msgs, sid or uuid.uuid4().hex)
        return f"Mensagem enviada para +{number}."
    return f"Falha ao enviar mensagem para +{number}."


def _list_groups() -> str:
    groups = get_groups(active_only=False)
    if not groups:
        return "Nenhum grupo cadastrado."
    lines = []
    for g in groups:
        status = "✅" if g.get("active") else "❌"
        cat = f" [{g['category']}]" if g.get("category") else ""
        lines.append(f"{status} {g['name']}{cat} — `{g['jid']}`")
    return "\n".join(lines)


def _add_group(name: str, jid: str, category: str = "") -> str:
    if add_group(name, jid, category):
        _sync_groups_to_vault()
        return f"Grupo '{name}' cadastrado."
    return f"Erro ao cadastrar grupo '{name}'."


def _remove_group(name: str) -> str:
    if remove_group(name):
        _sync_groups_to_vault()
        return f"Grupo '{name}' removido."
    return f"Grupo '{name}' não encontrado."


def _sync_groups_to_vault() -> None:
    if not os.environ.get("OBSIDIAN_VAULT_PATH"):
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


def _query_history(limit: int = 5) -> str:
    messages = get_message_history(limit=limit)
    if not messages:
        return "Nenhum envio no histórico."
    lines = []
    for msg in messages:
        groups = ", ".join(msg.get("groups_sent") or [])
        sent_at = (msg.get("sent_at") or "")[:16].replace("T", " ")
        preview = (msg.get("content", "")[:80] + "…") if len(msg.get("content", "")) > 80 else msg.get("content", "")
        lines.append(f"{sent_at} | {groups}\n{preview}")
    return "\n\n".join(lines)


_TOPIC_TO_NOTE = {
    "church": "00 - Contexto Pessoal/Igreja.md",
    "work": "00 - Contexto Pessoal/Trabalho.md",
    "task": "03 - Tarefas/Pendentes.md",
    "general": "00 - Contexto Pessoal/Hermes.md",
}

_CONTACTS_NOTE = "04 - Referências/Contatos.md"


def _upsert_contact(name: str, phone: str = "", role: str = "", notes: str = "") -> str:
    if not os.environ.get("OBSIDIAN_VAULT_PATH"):
        return "Vault não configurado."

    from app.services.obsidian import read_note, write_note as _write

    content = read_note(_CONTACTS_NOTE)
    rows: list[list[str]] = []
    past_sep = False

    for line in content.splitlines():
        s = line.strip()
        if s.startswith("| Nome"):
            continue
        if s.startswith("|---"):
            past_sep = True
            continue
        if past_sep and s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.split("|")[1:-1]]
            if len(cells) >= 4 and any(cells):
                rows.append(cells)
        elif past_sep and s and not s.startswith("|"):
            break

    name_lower = name.strip().lower()
    updated = False
    for row in rows:
        if row[0].lower() == name_lower:
            if phone: row[1] = phone
            if role:  row[2] = role
            if notes: row[3] = notes
            updated = True
            break

    if not updated:
        rows.append([name.strip(), phone, role, notes])

    table = [
        "| Nome | Telefone / WhatsApp | Função | Observações |",
        "|------|---------------------|--------|-------------|",
    ] + [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |" for r in rows]

    _write(
        _CONTACTS_NOTE,
        "# Contatos\n\n> O agente atualiza esta nota automaticamente.\n\n" + "\n".join(table) + "\n",
    )
    return f"Contato '{name}' {'atualizado' if updated else 'adicionado'} em Contatos."


def _save_note(content: str, topic: str) -> str:
    if not os.environ.get("OBSIDIAN_VAULT_PATH"):
        return "Vault não configurado."
    note_path = _TOPIC_TO_NOTE.get(topic, "00 - Contexto Pessoal/Hermes.md")
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    if topic == "task":
        append_to_note(note_path, f"- [ ] {content} _(adicionado em {date})_", separator="\n")
    else:
        append_to_note(note_path, f"**{date}** — {content}")
    return f"Salvo em '{Path(note_path).stem}'."


def _search_books(query: str, limit: int = 3) -> str:
    results = search_books_db(query, limit=limit)
    if not results:
        return "Nenhum trecho relevante encontrado nos livros."
    parts = []
    for r in results:
        sim = round(r.get("similarity", 0) * 100)
        parts.append(f"📖 *{r['book_title']}* ({sim}% relevância)\n{r['content']}")
    return "\n\n---\n\n".join(parts)


def _list_books() -> str:
    books = list_books()
    if not books:
        return "Nenhum livro indexado ainda."
    lines = [f"📚 *{b['title']}* — {b['pages']}p, {b['chunks']} trechos" for b in books]
    return "\n".join(lines)


def _delete_book(title: str) -> str:
    if delete_book(title):
        return f"Livro '{title}' removido da biblioteca."
    return f"Livro '{title}' não encontrado."


def _cleanup_duplicate_books() -> str:
    removed = delete_duplicate_books()
    if removed == 0:
        return "Nenhuma duplicata encontrada na biblioteca."
    return f"✅ {removed} entrada(s) duplicada(s) removida(s) da biblioteca."


def _rename_note(old_path: str, new_path: str) -> str:
    if rename_note(old_path, new_path):
        return f"Nota renomeada: '{old_path}' → '{new_path}'."
    return f"Erro ao renomear '{old_path}'. Verifique se o caminho existe."


def _delete_note(note_path: str) -> str:
    if delete_note(note_path):
        return f"Nota '{note_path}' deletada."
    return f"Nota '{note_path}' não encontrada."


def _notify_user(message: str, phone: str) -> str:
    if send_direct(phone, message):
        return f"Status enviado ao usuário: '{message}'"
    return "Falha ao enviar status."


def _search_vault(query: str) -> str:
    results = search_notes(query, max_results=3)
    if not results:
        return "Nenhuma informação encontrada no vault."
    return "\n\n".join(
        f"### {Path(r['path']).stem}\n{r['excerpt']}" for r in results
    )


def _read_chat(phone: str, last_n: int | None = None) -> str:
    phone = "".join(c for c in phone if c.isdigit())
    messages, _ = load_conversation_history(phone)
    if not messages:
        return f"Nenhuma conversa encontrada para +{phone}."
    if last_n:
        messages = messages[-last_n:]
    lines = []
    for m in messages:
        role = "Usuário" if m["role"] == "user" else "Mercúrio"
        content = (m.get("content") or "").strip()
        if content:
            lines.append(f"*{role}:* {content}")
    return "\n\n".join(lines) if lines else "Conversa sem mensagens de texto."


def _read_note(path: str) -> str:
    content = _obsidian_read(path)
    return content if content else f"(nota '{path}' não encontrada)"


def _write_note(path: str, content: str) -> str:
    if _obsidian_write(path, content):
        return f"Nota '{path}' salva."
    return f"Erro ao salvar nota '{path}'."


def _schedule_task(
    title: str,
    due_at: str,
    details: str = "",
    contact_phone: str = "",
    context_links: list[str] | None = None,
) -> str:
    try:
        from datetime import datetime as _dt
        due = _dt.fromisoformat(due_at.replace("Z", "+00:00"))
        if due.tzinfo is None and due < _dt.now():
            return f"❌ Horário '{due_at}' já passou. Informe um horário futuro."
    except ValueError:
        return f"❌ Formato inválido: '{due_at}'. Use ISO 8601 (ex: 2026-06-19T19:00:00)."

    lines = [
        f"\n## {title}",
        f"- **status:** pendente",
        f"- **prazo:** {due_at}",
    ]
    if contact_phone:
        lines.append(f"- **contato:** {''.join(c for c in contact_phone if c.isdigit())}")
    if details:
        lines.append(f"- **detalhes:** {details}")
    if context_links:
        links_str = ", ".join(f"[[{p}]]" for p in context_links)
        lines.append(f"- **contexto:** {links_str}")

    append_to_note("mercurio/Tarefas.md", "\n".join(lines), separator="\n")
    return f"✅ Tarefa agendada: _{title}_ para {due_at}."


def _save_to_vault(content: str, hint: str = "") -> str:
    import json as _json
    from app.agent.prompts import get_triage_prompt, PROMPT_TRIAGE_DEFAULT
    from app.services.obsidian import (
        ensure_frontmatter, read_note as _obs_read,
        write_note as _obs_write, append_to_note as _obs_append,
        update_vault_index,
    )

    conventions = _obs_read("07 - Mercurio/instrucoes/_Convenções.md") or ""
    index = _obs_read("07 - Mercurio/_index.md") or ""

    triage_prompt = get_triage_prompt(conventions, index, content, hint)

    try:
        resp = _get_llm().chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": triage_prompt}],
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = "\n".join(raw.splitlines()[1:])
            raw = raw.rsplit("```", 1)[0].strip()
        decision = _json.loads(raw)
    except Exception as e:
        logger.warning(f"save_to_vault: triage failed ({e}), falling back to append on Hermes.md")
        _obs_append("00 - Contexto Pessoal/Hermes.md", content)
        return f"⚠️ Triagem falhou, salvo em Hermes.md como fallback."

    action = decision.get("action", "append")
    path = decision.get("path", "00 - Contexto Pessoal/Hermes.md")
    tipo = decision.get("tipo", "contexto")
    tags = decision.get("tags", [])
    description = decision.get("description", "")

    if action == "create":
        new_content = ensure_frontmatter(content, tipo=tipo, tags=tags)
        _obs_write(path, new_content)
        update_vault_index(path, description, action="add")
        return f"✅ Nota criada: `{path}`"
    elif action == "update":
        existing = _obs_read(path) or ""
        from datetime import date as _d
        updated = ensure_frontmatter(existing, tipo=tipo, tags=tags)
        updated = updated.rstrip() + f"\n\n**{_d.today().isoformat()}** — {content}\n"
        _obs_write(path, updated)
        return f"✅ Nota atualizada: `{path}`"
    else:  # append
        _obs_append(path, content)
        return f"✅ Adicionado em: `{path}`"


def _transfer_to_human(reason: str, message_to_user: str, phone: str) -> str:
    from app.services.supabase import upsert_conversation_session
    owner_phone = "".join(c for c in os.environ.get("AUTHORIZED_NUMBER", "") if c.isdigit())
    upsert_conversation_session(phone, mode="human", transferred_by="agent")
    send_direct(phone, message_to_user)
    if owner_phone and owner_phone != phone:
        send_direct(
            owner_phone,
            f"📲 *Atendimento humano solicitado*\n*Contato:* +{phone}\n*Motivo:* {reason}",
        )
    return "Conversa transferida para atendimento humano. Usuário e Hermes notificados."



# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

@traceable(name="execute_tool")
def execute_tool(name: str, args: dict, phone: str) -> str:
    try:
        match name:
            case "generate_draft":
                return _generate_draft(args["instruction"])
            case "send_direct_message":
                return _send_direct_message(args["number"], args["text"])
            case "send_message":
                return _send_message(args["draft"], args.get("groups", []), phone)
            case "list_groups":
                return _list_groups()
            case "add_group":
                return _add_group(args["name"], args["jid"], args.get("category", ""))
            case "remove_group":
                return _remove_group(args["name"])
            case "query_history":
                return _query_history(args.get("limit", 5))
            case "upsert_contact":
                return _upsert_contact(
                    args["name"],
                    args.get("phone", ""),
                    args.get("role", ""),
                    args.get("notes", ""),
                )
            case "save_note":
                return _save_note(args["content"], args["topic"])
            case "rename_note":
                return _rename_note(args["old_path"], args["new_path"])
            case "delete_note":
                return _delete_note(args["note_path"])
            case "search_books":
                return _search_books(args["query"], args.get("limit", 5))
            case "list_books":
                return _list_books()
            case "delete_book":
                return _delete_book(args["title"])
            case "cleanup_duplicate_books":
                return _cleanup_duplicate_books()
            case "notify_user":
                return _notify_user(args["message"], phone)
            case "search_vault":
                return _search_vault(args["query"])
            case "read_chat":
                return _read_chat(args["phone"], args.get("last_n"))
            case "save_to_vault":
                return _save_to_vault(args["content"], args.get("hint", ""))
            case "transfer_to_human":
                return _transfer_to_human(args["reason"], args["message_to_user"], phone)
            case "read_note":
                return _read_note(args["path"])
            case "write_note":
                return _write_note(args["path"], args["content"])
            case "schedule_task":
                return _schedule_task(
                    args["title"],
                    args["due_at"],
                    args.get("details", ""),
                    args.get("contact_phone", ""),
                    args.get("context_links"),
                )
            case _:
                return f"Tool '{name}' não reconhecida."
    except Exception as e:
        logger.error(f"Tool '{name}' error: {e}", exc_info=True)
        return f"Erro ao executar '{name}': {e}"
