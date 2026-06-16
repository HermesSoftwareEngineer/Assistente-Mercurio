-- Adiciona session_id para vincular corretamente as threads no LangSmith
ALTER TABLE conversation_history
  ADD COLUMN IF NOT EXISTS session_id text NOT NULL DEFAULT '';
