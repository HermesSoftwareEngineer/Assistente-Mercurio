-- Habilitar extensão pgvector (rodar uma vez por projeto)
CREATE EXTENSION IF NOT EXISTS vector;

-- Livros indexados
CREATE TABLE IF NOT EXISTS books (
  id         uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  title      text NOT NULL,
  filename   text,
  pages      int DEFAULT 0,
  chunks     int DEFAULT 0,
  added_at   timestamptz DEFAULT now()
);

-- Trechos vetorizados (embedding-001 → 768 dims)
CREATE TABLE IF NOT EXISTS book_chunks (
  id          uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  book_id     uuid REFERENCES books(id) ON DELETE CASCADE,
  chunk_index int NOT NULL,
  content     text NOT NULL,
  embedding   vector(768),
  created_at  timestamptz DEFAULT now()
);
  
-- Backend usa chave publishable — desabilitar RLS para acesso direto
ALTER TABLE books      DISABLE ROW LEVEL SECURITY;
ALTER TABLE book_chunks DISABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS book_chunks_embedding_idx
  ON book_chunks USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

-- Função de busca semântica
CREATE OR REPLACE FUNCTION search_books(
  query_embedding vector(768),
  match_count     int DEFAULT 5
)
RETURNS TABLE (
  chunk_id    uuid,
  book_title  text,
  content     text,
  similarity  float
)
LANGUAGE sql STABLE AS $$
  SELECT
    bc.id,
    b.title,
    bc.content,
    1 - (bc.embedding <=> query_embedding) AS similarity
  FROM book_chunks bc
  JOIN books b ON bc.book_id = b.id
  ORDER BY bc.embedding <=> query_embedding
  LIMIT match_count;
$$;
