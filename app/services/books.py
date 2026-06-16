import logging

from app.services.google_client import get_client
from app.services.supabase import get_client as get_supabase

logger = logging.getLogger(__name__)


def embed(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
    from google.genai import types
    result = get_client().models.embed_content(
        model="gemini-embedding-001",
        contents=text,
        config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=768),
    )
    return result.embeddings[0].values


def book_exists(title: str) -> str | None:
    """Return book_id if a book with this title already exists, else None."""
    try:
        result = (
            get_supabase()
            .table("books")
            .select("id")
            .ilike("title", title.strip())
            .limit(1)
            .execute()
        )
        return result.data[0]["id"] if result.data else None
    except Exception as e:
        logger.error(f"book_exists error: {e}")
        return None


def save_book(title: str, filename: str, pages: int, chunks: list[str]) -> str | None:
    try:
        db = get_supabase()

        # Idempotency: skip if already indexed
        existing_id = book_exists(title)
        if existing_id:
            logger.info(f"Book '{title}' already indexed (id={existing_id}), skipping.")
            return existing_id

        book = db.table("books").insert({
            "title": title,
            "filename": filename,
            "pages": pages,
            "chunks": len(chunks),
        }).execute()
        book_id = book.data[0]["id"]

        rows = []
        for i, chunk in enumerate(chunks):
            rows.append({
                "book_id": book_id,
                "chunk_index": i,
                "content": chunk,
                "embedding": embed(chunk),
            })

        for i in range(0, len(rows), 50):
            db.table("book_chunks").insert(rows[i:i + 50]).execute()

        logger.info(f"Book '{title}' saved: {pages}p, {len(chunks)} chunks")
        return book_id

    except Exception as e:
        logger.error(f"save_book error: {e}", exc_info=True)
        return None


def search(query: str, limit: int = 5) -> list[dict]:
    try:
        query_embedding = embed(query, task_type="RETRIEVAL_QUERY")
        result = get_supabase().rpc(
            "search_books",
            {"query_embedding": query_embedding, "match_count": limit},
        ).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"search error: {e}", exc_info=True)
        return []


def list_books() -> list[dict]:
    try:
        return (
            get_supabase()
            .table("books")
            .select("id, title, filename, pages, chunks, added_at")
            .order("added_at", desc=True)
            .execute()
            .data or []
        )
    except Exception as e:
        logger.error(f"list_books error: {e}")
        return []


def delete_duplicate_books() -> int:
    """Remove duplicate books keeping the most recent entry per title. Returns count removed."""
    try:
        db = get_supabase()
        books = (
            db.table("books")
            .select("id, title, added_at")
            .order("added_at", desc=True)
            .execute()
            .data or []
        )

        seen: set[str] = set()
        to_delete: list[str] = []
        for book in books:
            key = book["title"].strip().lower()
            if key in seen:
                to_delete.append(book["id"])
            else:
                seen.add(key)

        for book_id in to_delete:
            db.table("book_chunks").delete().eq("book_id", book_id).execute()
            db.table("books").delete().eq("id", book_id).execute()

        logger.info(f"Removed {len(to_delete)} duplicate book(s)")
        return len(to_delete)
    except Exception as e:
        logger.error(f"delete_duplicate_books error: {e}")
        return 0


def delete_book(title: str) -> bool:
    try:
        result = (
            get_supabase()
            .table("books")
            .delete()
            .ilike("title", f"%{title}%")
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        logger.error(f"delete_book error: {e}")
        return False


def delete_book_by_id(book_id: str) -> bool:
    try:
        result = (
            get_supabase()
            .table("books")
            .delete()
            .eq("id", book_id)
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        logger.error(f"delete_book_by_id error: {e}")
        return False
