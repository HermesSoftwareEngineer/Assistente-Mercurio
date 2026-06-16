"""Re-indexa todos os livros da biblioteca com os novos parâmetros de chunking."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from app.services.books import delete_book, list_books, save_book
from app.services.pdf_processor import chunk_text, extract_text

BIBLIOTECA = Path(__file__).parent / "biblioteca"


def reindex():
    books = list_books()
    if not books:
        print("Nenhum livro encontrado no banco.")
        return

    print(f"Livros encontrados: {len(books)}\n")

    for book in books:
        title = book["title"]
        filename = book.get("filename", "")
        old_chunks = book.get("chunks", 0)

        pdf_path = BIBLIOTECA / filename
        if not pdf_path.exists():
            print(f"[SKIP] '{title}' — arquivo não encontrado: {pdf_path}")
            continue

        print(f"[RE-INDEX] '{title}'")
        print(f"  Arquivo : {pdf_path.name}")
        print(f"  Chunks antigos: {old_chunks}")

        pdf_bytes = pdf_path.read_bytes()
        text, pages = extract_text(pdf_bytes)
        chunks = chunk_text(text)

        print(f"  Chunks novos  : {len(chunks)}")

        delete_book(title)
        book_id = save_book(title, filename, pages, chunks)

        if book_id:
            print(f"  OK — {pages}p, {len(chunks)} trechos\n")
        else:
            print(f"  ERRO ao salvar '{title}'\n")
            sys.exit(1)

    print("Re-indexação concluída.")


if __name__ == "__main__":
    reindex()
