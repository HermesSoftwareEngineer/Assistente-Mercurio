-- Contatos autorizados a conversar com o Mercúrio
CREATE TABLE IF NOT EXISTS authorized_contacts (
  id         uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  number     text NOT NULL UNIQUE,
  name       text DEFAULT '',
  created_at timestamptz DEFAULT now()
);

-- Configurações gerais do sistema (chave/valor)
CREATE TABLE IF NOT EXISTS app_settings (
  key   text PRIMARY KEY,
  value text NOT NULL DEFAULT ''
);

INSERT INTO app_settings (key, value) VALUES ('allow_all', 'false')
ON CONFLICT (key) DO NOTHING;
