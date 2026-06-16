"""
Obsidian vault service — direct filesystem access.

The mcp-obsidian npm server (npm run mcp) exposes this same vault via MCP
for Claude Desktop / IDE use. The Python agent reads and writes files directly
for low-latency, zero-subprocess access during webhook processing.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

VAULT_PATH = os.environ.get("OBSIDIAN_VAULT_PATH", "")


def _vault() -> Path | None:
    if not VAULT_PATH:
        return None
    p = Path(VAULT_PATH)
    if not p.exists():
        logger.warning(f"Vault path does not exist: {p}")
        return None
    return p


def read_note(note_path: str) -> str:
    """Return note contents, or empty string if not found."""
    vault = _vault()
    if vault is None:
        return ""
    try:
        return (vault / note_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except Exception as e:
        logger.error(f"read_note '{note_path}': {e}")
        return ""


def write_note(note_path: str, content: str) -> bool:
    """Write (create or overwrite) a note. Creates parent directories."""
    vault = _vault()
    if vault is None:
        logger.warning("Vault not available — skipping write")
        return False
    try:
        target = vault / note_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        logger.info(f"Vault note written: {note_path}")
        return True
    except Exception as e:
        logger.error(f"write_note '{note_path}': {e}")
        return False


def append_to_note(note_path: str, new_content: str, separator: str = "\n\n---\n\n") -> bool:
    """Append content to an existing note, or create if missing."""
    existing = read_note(note_path)
    merged = (existing.rstrip() + separator + new_content) if existing else new_content
    return write_note(note_path, merged)


def rename_note(old_path: str, new_path: str) -> bool:
    """Rename or move a note within the vault."""
    vault = _vault()
    if vault is None:
        return False
    try:
        src = vault / old_path
        dst = vault / new_path
        if not src.exists():
            logger.warning(f"rename_note: source not found '{old_path}'")
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        logger.info(f"Vault note renamed: '{old_path}' → '{new_path}'")
        return True
    except Exception as e:
        logger.error(f"rename_note '{old_path}' → '{new_path}': {e}")
        return False


def delete_note(note_path: str) -> bool:
    """Delete a note from the vault."""
    vault = _vault()
    if vault is None:
        return False
    try:
        target = vault / note_path
        if not target.exists():
            logger.warning(f"delete_note: not found '{note_path}'")
            return False
        target.unlink()
        logger.info(f"Vault note deleted: {note_path}")
        return True
    except Exception as e:
        logger.error(f"delete_note '{note_path}': {e}")
        return False


def list_notes(folder: str = "") -> list[str]:
    """Return relative paths of all .md files under folder (default: vault root)."""
    vault = _vault()
    if vault is None:
        return []
    base = vault / folder if folder else vault
    try:
        return [str(p.relative_to(vault)) for p in base.rglob("*.md")]
    except Exception as e:
        logger.error(f"list_notes '{folder}': {e}")
        return []


def search_notes(query: str, max_results: int = 3) -> list[dict]:
    """Full-text search across vault. Returns list of {path, excerpt}."""
    vault = _vault()
    if vault is None:
        return []

    terms = [t for t in query.lower().split() if len(t) > 2]
    if not terms:
        return []

    results: list[dict] = []

    for md_file in vault.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            cl = content.lower()
            fn = md_file.name.lower()

            if not any(t in cl or t in fn for t in terms):
                continue

            idx = next((cl.find(t) for t in terms if t in cl), 0)
            start = max(0, idx - 100)
            end = min(len(content), idx + 300)
            excerpt = content[start:end].strip()

            results.append({
                "path": str(md_file.relative_to(vault)),
                "excerpt": excerpt,
            })

            if len(results) >= max_results:
                break
        except Exception:
            continue

    return results
