-- Histórico de conversas por número de telefone
-- Persiste entre reinicializações do servidor
CREATE TABLE IF NOT EXISTS conversation_history (
  phone      text PRIMARY KEY,
  messages   jsonb NOT NULL DEFAULT '[]',
  updated_at timestamptz DEFAULT now()
);
