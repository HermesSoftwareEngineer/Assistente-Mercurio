import logging
import os
from functools import wraps

from flask import Blueprint, jsonify, request, session

from app.services.supabase import (
    add_contact,
    add_group,
    delete_conversation_history,
    get_all_prompts,
    get_all_settings,
    get_contacts,
    get_conversation_session,
    get_groups,
    get_message_history,
    get_prompt,
    list_conversation_sessions,
    list_conversations_summary,
    patch_contact,
    remove_contact,
    remove_group,
    set_prompt,
    set_setting,
    upsert_conversation_session,
)
from app.services.books import list_books as _list_books, delete_book_by_id as _delete_book_by_id

logger = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__)


def _require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
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

@api_bp.route("/prompts", methods=["GET"])
@_require_auth
def list_prompts():
    prompts = get_all_prompts()
    return jsonify({"prompts": prompts})


@api_bp.route("/prompts/<key>", methods=["PUT"])
@_require_auth
def update_prompt(key):
    if key not in ("owner", "non_owner"):
        return jsonify({"error": "key deve ser 'owner' ou 'non_owner'"}), 400
    data = request.get_json() or {}
    content = data.get("content", "").strip()
    if not content:
        return jsonify({"error": "content não pode ser vazio"}), 400
    if not set_prompt(key, content):
        return jsonify({"error": "Erro ao salvar prompt"}), 500
    return jsonify({"ok": True, "key": key})
