import logging
from functools import wraps

from flask import Blueprint, jsonify, request, session

from app.services.supabase import (
    get_groups,
    add_group,
    remove_group,
    get_message_history,
)
from app.services.books import list_books as _list_books, delete_book_by_id as _delete_book_by_id

logger = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__)


def _require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return jsonify({"error": "Não autenticado"}), 401
        return f(*args, **kwargs)
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
