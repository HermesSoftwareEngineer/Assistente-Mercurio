-- Grupos de WhatsApp
CREATE TABLE IF NOT EXISTS groups (
  id        uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  name      text NOT NULL,
  jid       text NOT NULL UNIQUE,
  category  text DEFAULT '',
  active    boolean DEFAULT true,
  created_at timestamptz DEFAULT now()
);

-- Histórico de mensagens enviadas
CREATE TABLE IF NOT EXISTS messages (
  id          uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  content     text NOT NULL,
  groups_sent text[] DEFAULT '{}',
  approved_by text,
  sent_at     timestamptz DEFAULT now()
);
