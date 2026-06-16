import os
from functools import wraps

from flask import Blueprint, jsonify, render_template, request, session

from app.services.supabase import (
    add_contact,
    get_contacts,
    get_setting,
    remove_contact,
    set_setting,
)

admin_bp = Blueprint("admin", __name__)


def _load_config() -> dict:
    allow_all = get_setting("allow_all", "false") == "true"
    contacts = get_contacts()
    return {"allow_all": allow_all, "contacts": contacts}


def _load_numbers() -> list[str]:
    config = _load_config()
    if config.get("allow_all"):
        return []
    return [c["number"] for c in config.get("contacts", [])]


def _login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return jsonify({"error": "Não autenticado"}), 401
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/")
def index():
    return render_template("admin.html")


@admin_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    key = data.get("key", "")
    if key and key == os.environ.get("EVOLUTION_API_KEY", ""):
        session["authenticated"] = True
        return jsonify({"ok": True})
    return jsonify({"error": "Chave inválida"}), 401


@admin_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@admin_bp.route("/numbers", methods=["GET"])
@_login_required
def get_numbers():
    config = _load_config()
    return jsonify({"contacts": config["contacts"], "allow_all": config["allow_all"]})


@admin_bp.route("/numbers", methods=["POST"])
@_login_required
def add_number():
    data = request.get_json() or {}
    number = "".join(c for c in data.get("number", "") if c.isdigit())
    if not number:
        return jsonify({"error": "Número inválido"}), 400
    name = data.get("name", "").strip()
    if not add_contact(number, name):
        return jsonify({"error": "Erro ao salvar no banco."}), 500
    config = _load_config()
    return jsonify({"contacts": config["contacts"], "allow_all": config["allow_all"]})


@admin_bp.route("/numbers/<number>", methods=["DELETE"])
@_login_required
def remove_number(number):
    remove_contact(number)
    config = _load_config()
    return jsonify({"contacts": config["contacts"], "allow_all": config["allow_all"]})


@admin_bp.route("/settings", methods=["POST"])
@_login_required
def update_settings():
    data = request.get_json() or {}
    if "allow_all" in data:
        set_setting("allow_all", "true" if data["allow_all"] else "false")
    config = _load_config()
    return jsonify({"allow_all": config["allow_all"]})
