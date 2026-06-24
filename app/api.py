import logging
import os
from functools import wraps

from flask import Blueprint, jsonify, request, session

from app.services.supabase import (
    add_contact,
    add_group,
    delete_conversation_history,
    get_all_settings,
    get_contacts,
    get_conversation_session,
    get_groups,
    get_message_history,
    get_setting,
    list_conversation_sessions,
    list_conversations_summary,
    patch_contact,
    remove_contact,
    remove_group,
    set_setting,
    upsert_conversation_session,
)
from app.services.books import list_books as _list_books, delete_book_by_id as _delete_book_by_id

logger = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__)


@api_bp.route("/admin/login", methods=["POST"])
def api_admin_login():
    data = request.get_json() or {}
    key = data.get("key", "")
    if key and key == os.environ.get("EVOLUTION_API_KEY", ""):
        session["authenticated"] = True
        return jsonify({"ok": True})
    return jsonify({"error": "Chave inválida"}), 401


def _require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == "OPTIONS":
            return f(*args, **kwargs)
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            expected = os.environ.get("EVOLUTION_API_KEY", "")
            if token and token == expected:
                return f(*args, **kwargs)
        if session.get("authenticated"):
            return f(*args, **kwargs)
        return jsonify({"error": "Não autenticado"}), 401
    return decorated


def _int_param(name: str, default: int) -> tuple[int, None] | tuple[None, str]:
    try:
        return int(request.args.get(name, default)), None
    except ValueError:
        return None, f"'{name}' deve ser inteiro"


# ── Groups ───────────────────────────────────────────────────────────────────

@api_bp.route("/groups", methods=["GET"])
@_require_auth
def list_groups():
    active_only = request.args.get("active_only", "true").lower() != "false"
    return jsonify({"groups": get_groups(active_only=active_only)})


@api_bp.route("/groups", methods=["POST"])
@_require_auth
def add_group_route():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    jid = data.get("jid", "").strip()
    if not name or not jid:
        return jsonify({"error": "name e jid são obrigatórios"}), 400
    if not add_group(name, jid, data.get("category", "").strip()):
        return jsonify({"error": "Erro ao cadastrar grupo"}), 500
    return jsonify({"ok": True, "name": name, "jid": jid}), 201


@api_bp.route("/groups/<name>", methods=["DELETE"])
@_require_auth
def remove_group_route(name):
    if not remove_group(name):
        return jsonify({"error": f"Grupo '{name}' não encontrado"}), 404
    return jsonify({"ok": True})


# ── Messages ─────────────────────────────────────────────────────────────────

@api_bp.route("/messages", methods=["GET"])
@_require_auth
def list_messages():
    limit, err = _int_param("limit", 20)
    if err:
        return jsonify({"error": err}), 400
    messages = get_message_history(limit=limit)
    return jsonify({"messages": messages, "count": len(messages)})


# ── Books ────────────────────────────────────────────────────────────────────

@api_bp.route("/books", methods=["GET"])
@_require_auth
def list_books():
    books = _list_books()
    return jsonify({"books": books, "count": len(books)})


@api_bp.route("/books/<book_id>", methods=["DELETE"])
@_require_auth
def delete_book(book_id):
    if not _delete_book_by_id(book_id):
        return jsonify({"error": "Livro não encontrado"}), 404
    return jsonify({"ok": True})


# ── Contacts ─────────────────────────────────────────────────────────────────

@api_bp.route("/contacts", methods=["GET"])
@_require_auth
def list_contacts():
    contacts = get_contacts()
    return jsonify({"contacts": contacts, "count": len(contacts)})


@api_bp.route("/contacts", methods=["POST"])
@_require_auth
def add_contact_route():
    data = request.get_json() or {}
    number = "".join(c for c in data.get("number", "") if c.isdigit())
    name = data.get("name", "").strip()
    if not number:
        return jsonify({"error": "number é obrigatório (apenas dígitos)"}), 400
    if not add_contact(number, name):
        return jsonify({"error": "Erro ao adicionar contato"}), 500
    return jsonify({"ok": True, "number": number, "name": name}), 201


@api_bp.route("/contacts/<number>", methods=["DELETE"])
@_require_auth
def delete_contact(number):
    number = "".join(c for c in number if c.isdigit())
    if not remove_contact(number):
        return jsonify({"error": "Contato não encontrado"}), 404
    return jsonify({"ok": True})


@api_bp.route("/contacts/<number>", methods=["PATCH"])
@_require_auth
def update_contact(number):
    number = "".join(c for c in number if c.isdigit())
    data = request.get_json() or {}
    active = data.get("active")
    name = data.get("name")
    if active is None and name is None:
        return jsonify({"error": "Informe ao menos 'active' ou 'name'"}), 400
    if not patch_contact(number, active=active, name=name):
        return jsonify({"error": "Contato não encontrado ou erro ao atualizar"}), 404
    return jsonify({"ok": True})


# ── Settings ──────────────────────────────────────────────────────────────────

@api_bp.route("/settings", methods=["GET"])
@_require_auth
def list_settings():
    settings = get_all_settings()
    return jsonify({"settings": {s["key"]: s["value"] for s in settings}})


@api_bp.route("/settings", methods=["PATCH"])
@_require_auth
def update_settings():
    data = request.get_json() or {}
    if not data:
        return jsonify({"error": "Body vazio"}), 400
    errors = []
    for key, value in data.items():
        if not set_setting(key, str(value).lower() if isinstance(value, bool) else str(value)):
            errors.append(key)
    if errors:
        return jsonify({"error": f"Falha ao salvar: {errors}"}), 500
    return jsonify({"ok": True})


# ── Conversations ─────────────────────────────────────────────────────────────

@api_bp.route("/conversations", methods=["GET"])
@_require_auth
def list_conversations():
    conversations = list_conversations_summary()
    return jsonify({"conversations": conversations, "count": len(conversations)})


@api_bp.route("/conversations/<phone>", methods=["GET"])
@_require_auth
def get_conversation(phone):
    from app.services.supabase import load_conversation_history
    phone = "".join(c for c in phone if c.isdigit())
    messages, session_id = load_conversation_history(phone)
    session = get_conversation_session(phone)
    return jsonify({
        "phone": phone,
        "session_id": session_id,
        "mode": session.get("mode", "bot") if session else "bot",
        "messages": messages,
        "count": len(messages),
    })


@api_bp.route("/conversations/<phone>/reset", methods=["POST"])
@_require_auth
def reset_conversation(phone):
    from app.agent.agent import reset_session
    phone = "".join(c for c in phone if c.isdigit())
    reset_session(phone)
    return jsonify({"ok": True, "phone": phone})


# ── Sessions (handoff) ────────────────────────────────────────────────────────

@api_bp.route("/sessions", methods=["GET"])
@_require_auth
def list_sessions():
    sessions = list_conversation_sessions()
    contacts_map = {c["number"]: c.get("name", "") for c in get_contacts()}
    for s in sessions:
        s["name"] = contacts_map.get(s["phone"], "")
    return jsonify({"sessions": sessions, "count": len(sessions)})


@api_bp.route("/sessions/<phone>/mode", methods=["PATCH"])
@_require_auth
def set_session_mode(phone):
    phone = "".join(c for c in phone if c.isdigit())
    data = request.get_json() or {}
    mode = data.get("mode", "").lower()
    if mode not in ("bot", "human"):
        return jsonify({"error": "mode deve ser 'bot' ou 'human'"}), 400
    if not upsert_conversation_session(phone, mode=mode, transferred_by="admin"):
        return jsonify({"error": "Erro ao atualizar sessão"}), 500
    return jsonify({"ok": True, "phone": phone, "mode": mode})


# ── Prompts ───────────────────────────────────────────────────────────────────

_PROMPT_KEYS = {
    "prompt_draft": "Geração de rascunhos WhatsApp",
    "prompt_owner": "Agente — modo Hermes (owner)",
    "prompt_non_owner": "Agente — modo terceiros",
    "prompt_proactive": "Heartbeat proativo",
    "prompt_triage": "Triagem de notas do vault",
}

_PROMPT_KEY_ALIASES = {
    "draft": "prompt_draft",
    "owner": "prompt_owner",
    "non_owner": "prompt_non_owner",
    "proactive": "prompt_proactive",
}


@api_bp.route("/prompts", methods=["GET"])
@_require_auth
def list_prompts():
    from app.agent.prompts import (
        PROMPT_DRAFT_DEFAULT, PROMPT_OWNER_DEFAULT,
        PROMPT_NON_OWNER_DEFAULT, PROMPT_PROACTIVE_DEFAULT,
        PROMPT_TRIAGE_DEFAULT,
    )
    defaults = {
        "prompt_draft": PROMPT_DRAFT_DEFAULT,
        "prompt_owner": PROMPT_OWNER_DEFAULT,
        "prompt_non_owner": PROMPT_NON_OWNER_DEFAULT,
        "prompt_proactive": PROMPT_PROACTIVE_DEFAULT,
        "prompt_triage": PROMPT_TRIAGE_DEFAULT,
    }
    result = {}
    for key, label in _PROMPT_KEYS.items():
        value = get_setting(key)
        result[key] = {"label": label, "value": value or "", "default": defaults.get(key, "")}
    return jsonify({"prompts": result})


@api_bp.route("/prompts/<key>", methods=["PUT"])
@_require_auth
def update_prompt(key):
    key = _PROMPT_KEY_ALIASES.get(key, key)
    if key not in _PROMPT_KEYS:
        return jsonify({"error": f"Chave '{key}' inválida. Válidas: {list(_PROMPT_KEYS)}"}), 400
    data = request.get_json() or {}
    value = data.get("value") if data.get("value") is not None else data.get("content")
    if value is None:
        return jsonify({"error": "'value' ou 'content' é obrigatório"}), 400
    if not isinstance(value, str):
        return jsonify({"error": "'value' deve ser string"}), 400
    if not set_setting(key, value):
        return jsonify({"error": "Erro ao salvar"}), 500
    return jsonify({"ok": True, "key": key})


# ── Vault ─────────────────────────────────────────────────────────────────────

@api_bp.route("/vault/index", methods=["GET"])
@_require_auth
def vault_index():
    import re
    from app.services.obsidian import read_note as _rn
    content = _rn("07 - Mercurio/_index.md") or ""
    entries = []
    for line in content.splitlines():
        m = re.match(r"- \[\[([^\]]+)\]\] — (.+?) \((.+?)\)", line)
        if m:
            entries.append({"name": m.group(1), "description": m.group(2), "path": m.group(3)})
    return jsonify({"entries": entries, "raw": content})


@api_bp.route("/vault/convencoes", methods=["GET"])
@_require_auth
def vault_get_convencoes():
    from app.services.obsidian import read_note as _rn
    content = _rn("07 - Mercurio/instrucoes/_Convenções.md") or ""
    return jsonify({"content": content})


@api_bp.route("/vault/convencoes", methods=["PUT"])
@_require_auth
def vault_save_convencoes():
    from app.services.obsidian import write_note as _wn
    data = request.get_json() or {}
    content = data.get("content", "")
    if not isinstance(content, str):
        return jsonify({"error": "'content' deve ser string"}), 400
    _wn("07 - Mercurio/instrucoes/_Convenções.md", content)
    return jsonify({"ok": True})


@api_bp.route("/vault/suggestions", methods=["GET"])
@_require_auth
def vault_suggestions():
    import re
    from app.services.obsidian import read_note as _rn
    content = _rn("07 - Mercurio/organize_suggestions.md") or ""
    phantom = [
        {"link": m[0], "source": m[1]}
        for m in re.findall(r"- `\[\[([^\]]+)\]\]` referenciado em `([^`]+)`", content)
    ]
    duplicates = [
        {"a": m[0], "b": m[1]}
        for m in re.findall(r"- `([^`]+)` e `([^`]+)` podem ser a mesma entidade", content)
    ]
    generated_at = None
    for line in content.splitlines():
        m = re.search(r"<!-- Gerado automaticamente — (\d{4}-\d{2}-\d{2}) -->", line)
        if m:
            generated_at = m.group(1)
            break
    return jsonify({
        "phantom_links": phantom,
        "potential_duplicates": duplicates,
        "generated_at": generated_at,
        "raw": content,
    })


@api_bp.route("/vault/apply-suggestion", methods=["POST"])
@_require_auth
def vault_apply_suggestion():
    from app.services.obsidian import write_note as _wn, ensure_frontmatter, read_note as _rn
    data = request.get_json() or {}
    action = data.get("action")
    if action == "create_note":
        path = data.get("path", "")
        if not path:
            return jsonify({"error": "'path' é obrigatório para create_note"}), 400
        content = ensure_frontmatter("", tipo="contexto")
        _wn(path, content)
        return jsonify({"ok": True, "path": path})
    if action == "ignore":
        return jsonify({"ok": True})
    return jsonify({"error": f"Ação '{action}' inválida"}), 400


# ── Scheduler ─────────────────────────────────────────────────────────────────

@api_bp.route("/scheduler/jobs", methods=["GET"])
@_require_auth
def scheduler_get_jobs():
    from app.agent.scheduler import get_jobs_status
    jobs = get_jobs_status()
    heartbeat_times = get_setting("heartbeat_times") or "08:00, 13:00, 18:00"
    vault_poll_interval = get_setting("vault_poll_interval") or "5"
    organize_memory_schedule = get_setting("organize_memory_schedule") or "mon 08:00"
    organize_memory_enabled = get_setting("organize_memory_enabled") or "true"
    return jsonify({
        "jobs": jobs,
        "config": {
            "heartbeat_times": heartbeat_times,
            "vault_poll_interval": vault_poll_interval,
            "organize_memory_schedule": organize_memory_schedule,
            "organize_memory_enabled": organize_memory_enabled,
        },
    })


@api_bp.route("/scheduler/jobs", methods=["POST"])
@_require_auth
def scheduler_update_config():
    from app.agent.scheduler import restart_scheduler
    data = request.get_json() or {}
    allowed = {"heartbeat_times", "vault_poll_interval", "organize_memory_schedule", "organize_memory_enabled"}
    for key, value in data.items():
        if key in allowed:
            set_setting(key, str(value))
    restart_scheduler()
    return jsonify({"ok": True})


@api_bp.route("/scheduler/run/<job_id>", methods=["POST"])
@_require_auth
def scheduler_run_job(job_id):
    from app.agent.scheduler import trigger_job
    if trigger_job(job_id):
        return jsonify({"ok": True, "job": job_id})
    return jsonify({"error": f"Job '{job_id}' não encontrado"}), 404
