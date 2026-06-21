-- Configurações do scheduler e vault (inseridas com fallback — não sobrescreve se já existir)
INSERT INTO app_settings (key, value) VALUES
  ('heartbeat_times',          '08:00, 13:00, 18:00'),
  ('vault_poll_interval',      '5'),
  ('organize_memory_schedule', 'mon 08:00'),
  ('organize_memory_enabled',  'true')
ON CONFLICT (key) DO NOTHING;
