# Assistente Mercúrio — WhatsApp Agent para Igreja

Agente pessoal que recebe mensagens no WhatsApp, gera avisos formatados com IA e os envia para grupos cadastrados.

## Stack

| Componente | Tecnologia |
|---|---|
| Interface | WhatsApp via [Evolution API](https://github.com/EvolutionAPI/evolution-api) (baileys) |
| Backend | Python + Flask |
| Agente | LangGraph (StateGraph) |
| LLM | DeepSeek V4 Flash |
| Memória | Obsidian vault via [mcp-obsidian](https://www.npmjs.com/package/mcp-obsidian) |
| Banco | Supabase (PostgreSQL) |
| Infra | Docker Compose |

---

## Pré-requisitos

- Docker e Docker Compose instalados
- Conta no [Supabase](https://supabase.com) (plano gratuito funciona)
- Chave de API do [DeepSeek](https://platform.deepseek.com)
- Evolution API rodando e acessível

---

## 1. Configurar o Supabase

No painel do Supabase, abra o **SQL Editor** e execute:

```sql
-- Grupos de WhatsApp
CREATE TABLE groups (
  id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  name        TEXT NOT NULL,
  jid         TEXT NOT NULL,
  category    TEXT DEFAULT '',
  active      BOOLEAN DEFAULT true,
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- Histórico de mensagens enviadas
CREATE TABLE messages (
  id           UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  content      TEXT NOT NULL,
  groups_sent  TEXT[] DEFAULT '{}',
  sent_at      TIMESTAMPTZ DEFAULT now(),
  approved_by  TEXT
);
```

Copie a **URL do projeto** e a **anon key** em *Project Settings → API*.

---

## 2. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Edite `.env`:

```env
EVOLUTION_API_URL=http://evolution-api:8080   # URL da Evolution API
EVOLUTION_API_KEY=sua-chave-aqui
EVOLUTION_INSTANCE=nome-da-instancia
DEEPSEEK_API_KEY=sua-chave-deepseek
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=sua-anon-key
AUTHORIZED_NUMBER=5511999999999              # Somente este número pode usar o agente
```

> `AUTHORIZED_NUMBER` deve ter apenas dígitos (DDD + número, sem + ou espaços).

---

## 3. Subir o projeto

```bash
docker compose up -d --build
```

Verifique os logs:

```bash
docker compose logs -f whatsapp-agent
```

---

## 4. Conectar o número via QR Code

### Se a Evolution API também estiver no Docker Compose

Acesse o painel da Evolution API no navegador (por padrão `http://localhost:8080/manager`) e:

1. Crie uma instância com o mesmo nome que você definiu em `EVOLUTION_INSTANCE`
2. Clique em **Connect** e escaneie o QR Code com o WhatsApp do número que será o bot

### Via API (curl)

```bash
# Criar instância
curl -X POST http://localhost:8080/instance/create \
  -H "apikey: SUA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"instanceName": "nome-da-instancia", "qrcode": true}'

# Ver QR code
curl http://localhost:8080/instance/connect/nome-da-instancia \
  -H "apikey: SUA_API_KEY"
```

---

## 5. Registrar o webhook

Após conectar o número, configure o webhook para apontar para este agente:

```bash
curl -X POST http://localhost:8080/webhook/set/nome-da-instancia \
  -H "apikey: SUA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "http://whatsapp-agent:5000/webhook/whatsapp",
    "webhook_by_events": false,
    "webhook_base64": false,
    "events": ["MESSAGES_UPSERT"]
  }'
```

> Se o agente não estiver no mesmo Docker Compose que a Evolution API, use o IP/domínio acessível externamente no lugar de `whatsapp-agent`.

---

## 6. Cadastrar os primeiros grupos

Mande uma mensagem do número autorizado para o número do bot:

```
cadastra grupo Jovens | 120363xxxxxx@g.us
cadastra grupo Adultos | 120363yyyyyy@g.us
```

Para descobrir o JID de um grupo, você pode usar a Evolution API:

```bash
curl http://localhost:8080/group/fetchAllGroups/nome-da-instancia?getParticipants=false \
  -H "apikey: SUA_API_KEY"
```

O JID termina em `@g.us`.

---

## Obsidian — Memória Persistente

O agente usa um vault Obsidian como memória de longo prazo. Antes de processar qualquer mensagem ele lê o contexto relevante; após executar ações ele salva registros automaticamente.

### Estrutura do vault

```
vault/
├── 00 - Contexto Pessoal/
│   ├── Hermes.md          # perfil, preferências
│   ├── Trabalho.md        # Stylus Assessoria
│   └── Igreja.md          # nome, horários, líderes, grupos ← lido antes de gerar avisos
├── 01 - Projetos/
│   └── Mercurio.md        # descrição deste assistente
├── 02 - Avisos Enviados/   # ← uma nota por envio, criada automaticamente
├── 03 - Tarefas/
│   └── Pendentes.md       # ← tarefas adicionadas via chat
└── 04 - Referências/
    ├── Contatos.md
    └── Grupos WhatsApp.md  # ← espelhado do Supabase automaticamente
```

### O que é salvo automaticamente

| Ação | O que é salvo |
|---|---|
| Aviso enviado | `02 - Avisos Enviados/YYYY-MM-DD Título.md` |
| "o culto agora é às 19h" | Atualiza `Igreja.md` com o novo horário |
| "me lembra de comprar flores" | Adiciona item em `Pendentes.md` |
| Grupo cadastrado/removido | Sincroniza `Grupos WhatsApp.md` |

### Configurar o vault path

No `.env`, aponte para a pasta do vault:

```env
# Use a pasta vault/ incluída no projeto (já pronta para uso):
OBSIDIAN_VAULT_PATH=./vault

# Ou use um vault Obsidian existente:
OBSIDIAN_VAULT_PATH=C:/Users/Hermes/Documents/MeuVault
```

> O agente funciona sem `OBSIDIAN_VAULT_PATH` — os nós de memória são silenciosamente ignorados. Configure quando quiser ativar a memória persistente.

### Instalar e rodar o servidor MCP

O servidor MCP expõe o vault para Claude Desktop, VS Code e outras ferramentas compatíveis com MCP. Isso é **separado** do agente Python — use quando quiser navegar pelo vault via IA external.

**Pré-requisito:** Node.js 18+

```bash
# Instalar dependências npm (apenas uma vez)
npm install

# Iniciar o servidor MCP (lê OBSIDIAN_VAULT_PATH do .env)
npm run mcp
```

Ou sem instalar nada:

```bash
npx -y mcp-obsidian C:/Users/Hermes/Documents/MeuVault
```

### Conectar ao Claude Desktop

Adicione em `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "obsidian-mercurio": {
      "command": "npx",
      "args": ["-y", "mcp-obsidian", "C:/Users/Hermes/Documents/MeuVault"]
    }
  }
}
```

Reinicie o Claude Desktop. O vault aparecerá como ferramenta disponível.

---

## Uso

Mande mensagens do número autorizado para o bot:

| Exemplo | Ação |
|---|---|
| `gera um aviso sobre o culto de domingo às 19h` | Gera rascunho usando Igreja.md como contexto |
| `gera aviso e envia direto para Jovens` | Gera e envia sem pedir confirmação |
| `sim` / `ok` / `pode enviar` | Aprova e envia o rascunho pendente |
| `envia para o grupo Adultos` | Envia rascunho pendente para grupo específico |
| `listar grupos` | Lista todos os grupos cadastrados |
| `remove grupo Jovens` | Desativa um grupo |
| `histórico` | Mostra os últimos 5 envios |
| `o culto agora é às 19h` | Salva info em Igreja.md |
| `me lembra de comprar flores para o culto` | Adiciona em Pendentes.md |

---

## Estrutura do projeto

```
app/
├── main.py              # Flask app + webhook handler
├── agent/
│   ├── graph.py         # LangGraph StateGraph + sessão em memória
│   ├── nodes.py         # Nós do grafo (recall_memory, classify, draft, send, save_memory…)
│   └── prompts.py       # Prompts do sistema
├── services/
│   ├── evolution.py     # Envio de mensagens via Evolution API
│   ├── supabase.py      # CRUD de grupos e histórico
│   └── obsidian.py      # Leitura/escrita do vault Obsidian
└── models/
    └── group.py         # Modelo Pydantic do grupo
vault/                   # Vault Obsidian — memória persistente do agente
package.json             # Dependências npm (mcp-obsidian)
start-mcp.js             # Script de inicialização do servidor MCP
```

### Fluxo do grafo LangGraph

```
START
  └─→ recall_memory        (lê vault: Igreja.md + busca contextual)
        └─→ classify_intent (DeepSeek classifica intenção)
              ├─→ generate_draft  ──(send_direct?)──→ send_to_groups ─→ save_memory ─→ END
              │                  └─→ END (mostra rascunho)
              ├─→ send_to_groups ──────────────────────────────────→ save_memory ─→ END
              ├─→ manage_groups ───────────────────────────────────→ save_memory ─→ END
              ├─→ save_memory  (update_context / add_task) ──────────────────────→ END
              ├─→ query_history ───────────────────────────────────────────────→ END
              └─→ handle_unknown ──────────────────────────────────────────────→ END
```

---

## Desenvolvimento local (sem Docker)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # preencha o .env

flask --app app.main run --port 5000
```

Para expor o webhook localmente, use [ngrok](https://ngrok.com):

```bash
ngrok http 5000
```

Use a URL gerada pelo ngrok como webhook na Evolution API.

---

## Docker

O projeto roda como um container isolado. Há dois modos de deploy.

### Rodar local (conectado ao Olimpo)

O Nginx do Olimpo roteia `/mercurio/` para o container via rede interna Docker.

1. Garanta que o Olimpo está rodando:
   ```bash
   # no diretório olimpo/
   docker compose up -d
   ```

2. Adicione ao `nginx.conf` do Olimpo:
   ```nginx
   location /mercurio/ {
       proxy_pass http://mercurio:5000/;
   }
   ```

3. Suba o Mercúrio com a extensão de rede:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.olimpo.yml up -d --build
   ```

### Rodar em VPS (independente)

1. Copie o repositório e configure o `.env`:
   ```bash
   cp .env.example .env
   # Edite .env: ajuste WEBHOOK_URL para a URL pública da VPS
   ```

2. Suba com o compose base:
   ```bash
   docker compose up -d --build
   ```

A porta `5000` ficará exposta diretamente. Configure seu proxy reverso (Nginx/Caddy) ou abra a porta no firewall conforme necessário.

### Variáveis obrigatórias para Docker

| Variável | Descrição |
|---|---|
| `EVOLUTION_API_URL` | URL da Evolution API (ex: `http://evolution-api:8080`) |
| `EVOLUTION_API_KEY` | Chave da Evolution API |
| `EVOLUTION_INSTANCE` | Nome da instância WhatsApp |
| `WEBHOOK_URL` | URL pública deste bot (ex: `https://dominio.com/webhook/whatsapp`) |
| `DEEPSEEK_API_KEY` | Chave do DeepSeek |
| `SUPABASE_URL` / `SUPABASE_KEY` | Credenciais do Supabase |

> Ao iniciar, `startup.py` registra automaticamente o webhook na Evolution API antes de subir o Flask.
