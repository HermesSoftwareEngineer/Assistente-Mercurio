import logging

logger = logging.getLogger(__name__)

CHUNK_SIZE = 4000
CHUNK_OVERLAP = 400


def extract_text(pdf_bytes: bytes) -> tuple[str, int]:
    """Extract full text and page count from PDF bytes."""
    import fitz  # pymupdf
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = len(doc)
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    logger.info(f"Extracted {len(text)} chars from {pages} pages")
    return text, pages


def chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks."""
    chunks = []
    start = 0
    text = text.strip()
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks
