# Mercúrio — API Reference

> Base URL local: `http://localhost:5000`  
> Autenticação: session cookie (`EVOLUTION_API_KEY` como senha). Endpoints marcados com 🔒 exigem login.

---

## Autenticação

O painel admin usa **session cookie** (Flask). O fluxo é:

1. `POST /admin/login` → recebe cookie de sessão
2. Todas as rotas `🔒` enviam o cookie automaticamente
3. `POST /admin/logout` → invalida a sessão

```
Header de autenticação: cookie de sessão (gerenciado pelo browser/axios com withCredentials: true)
Senha padrão: valor da env EVOLUTION_API_KEY (ex: "senha123")
```

---

## Endpoints Existentes

### Sistema

#### `GET /health`
Verifica se o servidor está no ar.

**Response 200**
```json
{ "status": "healthy" }
```

---

#### `POST /webhook/whatsapp`
Recebe eventos da Evolution API (WhatsApp). **Não chamado pelo frontend** — uso exclusivo da Evolution API.

**Request body** (enviado pela Evolution API)
```json
{
  "event": "messages.upsert",
  "instance": "Mercurio",
  "data": {
    "key": { "fromMe": false, "remoteJid": "5585999990001@s.whatsapp.net", "id": "MSG_ID" },
    "pushName": "Nome do Usuário",
    "message": { "conversation": "Texto da mensagem" },
    "messageType": "conversation",
    "messageTimestamp": 1718400000
  }
}
```

**Response 200**
```json
{ "status": "ok" }
{ "status": "ignored" }
{ "status": "unauthorized" }
```

---

### Admin — Autenticação

#### `GET /admin/`
Serve o HTML do painel admin (`templates/admin.html`).

**Response 200** — página HTML

---

#### `POST /admin/login`
Autentica o usuário e inicia sessão.

**Request body**
```json
{ "key": "senha123" }
```

**Response 200**
```json
{ "ok": true }
```

**Response 401**
```json
{ "error": "Chave inválida" }
```

---

#### `POST /admin/logout`
Encerra a sessão atual.

**Response 200**
```json
{ "ok": true }
```

---

### Admin — Contatos Autorizados

#### 🔒 `GET /admin/numbers`
Lista todos os contatos autorizados e o modo de acesso.

**Response 200**
```json
{
  "contacts": [
    { "number": "558596688778", "name": "Hermes" }
  ],
  "allow_all": false
}
```

---

#### 🔒 `POST /admin/numbers`
Adiciona um contato autorizado.

**Request body**
```json
{ "number": "5585999990001", "name": "João" }
```

**Response 200** — retorna lista atualizada (igual ao GET)

**Response 400**
```json
{ "error": "Número inválido" }
```

**Response 500**
```json
{ "error": "Erro ao salvar no banco." }
```

---

#### 🔒 `DELETE /admin/numbers/<number>`
Remove um contato autorizado.

**Path param:** `number` — apenas dígitos (ex: `558596688778`)

**Response 200** — retorna lista atualizada (igual ao GET)

---

### Admin — Configurações

#### 🔒 `POST /admin/settings`
Atualiza configurações do sistema.

**Request body**
```json
{ "allow_all": true }
```

**Response 200**
```json
{ "allow_all": true }
```

---

## Banco de Dados (Supabase)

> URL: `https://ljyofbcfboluiqilszqu.supabase.co`  
> Acesso via service key (backend) — o frontend **não** deve consultar o Supabase diretamente.

### Tabelas

#### `authorized_contacts`
| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | uuid PK | |
| `number` | text UNIQUE | Telefone só dígitos |
| `name` | text | Nome do contato |
| `created_at` | timestamptz | |

#### `app_settings`
| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `key` | text PK | Ex: `"allow_all"` |
| `value` | text | Ex: `"true"` / `"false"` |

#### `groups`
| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | uuid PK | |
| `name` | text | Nome do grupo |
| `jid` | text UNIQUE | Ex: `120363xxxxxx@g.us` |
| `category` | text | Opcional |
| `active` | boolean | |
| `created_at` | timestamptz | |

#### `messages`
| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | uuid PK | |
| `content` | text | Texto da mensagem enviada |
| `groups_sent` | text[] | Nomes dos grupos destinatários |
| `approved_by` | text | Telefone de quem aprovou |
| `sent_at` | timestamptz | |

#### `conversation_history`
| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `phone` | text PK | Telefone do usuário |
| `messages` | jsonb | Array de `{role, content}` |
| `session_id` | text | UUID da sessão atual |
| `updated_at` | timestamptz | |

#### `books`
| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | uuid PK | |
| `title` | text | Título do livro |
| `filename` | text | Nome do arquivo PDF |
| `pages` | int | |
| `chunks` | int | Número de trechos indexados |
| `added_at` | timestamptz | |

#### `book_chunks`
| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | uuid PK | |
| `book_id` | uuid FK → books | |
| `chunk_index` | int | Ordem do trecho |
| `content` | text | Texto do trecho (~1 página) |
| `embedding` | vector(768) | Vetor semântico |
| `created_at` | timestamptz | |

#### `processes`
| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | uuid PK | |
| `name` | text | Ex: `"coletar_roteiros"` |
| `description` | text | |
| `trigger_mode` | enum | `manual` \| `cron` |
| `recurrence_cron` | text | Expressão cron (opcional) |
| `parameters_schema` | jsonb | Schema dos parâmetros |
| `steps` | jsonb | Array de steps |
| `active` | boolean | |
| `created_at` / `updated_at` | timestamptz | |

#### `process_instances`
| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | uuid PK | |
| `process_id` | uuid FK → processes | Pode ser null (inline) |
| `process_name` | text | Nome do processo |
| `status` | enum | `in_progress` \| `done` \| `cancelled` \| `failed` |
| `parameters` | jsonb | Parâmetros usados |
| `notes` | text | |
| `started_at` / `completed_at` | timestamptz | |

#### `tasks`
| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | uuid PK | |
| `process_instance_id` | uuid FK → process_instances | Nullable (tarefa avulsa) |
| `step_id` | text | Referência ao step no processo |
| `title` | text | |
| `type` | enum | Ver abaixo |
| `status` | enum | Ver abaixo |
| `due_at` | timestamptz | Prazo de execução |
| `timing_type` | enum | `immediate` \| `after_hours` \| `at` |
| `timing_value` | text | |
| `depends_on` | jsonb | Array de UUIDs de tasks |
| `on_delay` | enum | `notify` \| `proceed` \| `cascade` |
| `payload` | jsonb | Dados específicos do tipo |
| `contact_phone` | text | Telefone (para collect_from_contact) |
| `notes` | text | Observações manuais |
| `created_at` / `updated_at` / `completed_at` | timestamptz | |

---

## Enums

### `tasks.type`
| Valor | Descrição |
|-------|-----------|
| `reminder` | Lembrete enviado a Hermes |
| `notify_hermes` | Notificação ao Hermes |
| `ask_hermes` | Pergunta que aguarda resposta de Hermes |
| `send_message` | Envio para grupo(s) ou contato direto |
| `collect_from_contact` | Envia mensagem e aguarda resposta de contato externo (com retry) |
| `compile` | LLM compila respostas coletadas e gera texto final |
| `wait` | Aguarda horário antes de prosseguir |

### `tasks.status`
| Valor | Descrição |
|-------|-----------|
| `blocked` | Aguardando `depends_on` serem concluídas |
| `pending` | Pronta para execução, aguardando o scheduler |
| `in_progress` | Sendo executada (ex: aguardando resposta de contato) |
| `done` | Concluída com sucesso |
| `missed` | Não executada a tempo (offline) |
| `cancelled` | Cancelada manualmente |
| `failed` | Falhou na execução |

### `tasks.payload` por tipo
```jsonc
// reminder / notify_hermes
{ "message": "Texto da notificação" }

// send_message
{
  "content": "Texto ou vazio se veio de compile",
  "target_type": "group" | "direct",
  "targets": ["Nome do Grupo"],
  "source_compile_task_id": "uuid"   // quando content vem de uma task compile
}

// collect_from_contact
{
  "message": "Mensagem inicial ao contato",
  "retry_message": "Mensagem de retry",
  "retry_interval_hours": 2,
  "max_retries": 2,
  "retry_count": 0,
  "contact_name": "João",
  "response": "Texto respondido pelo contato"  // preenchido pelo agente ao receber resposta
}

// compile
{
  "instructions": "Monte o roteiro completo...",
  "source_task_ids": ["uuid1", "uuid2"],
  "event_name": "Culto de Domingo",
  "result": "Texto compilado"  // preenchido pelo handler após execução
}

// ask_hermes
{ "question": "Pergunta a fazer ao Hermes" }

// wait
{ "reason": "Aguardando confirmação" }
```

---

## Endpoints a Criar (para o Frontend)

Os endpoints abaixo **não existem ainda** no Flask — são necessários para o painel React:

### Tarefas

```
🔒 GET    /api/tasks                     Lista tarefas (query: status, type, limit, offset)
🔒 POST   /api/tasks                     Cria tarefa avulsa
🔒 GET    /api/tasks/<id>                Detalhe de uma tarefa
🔒 PATCH  /api/tasks/<id>               Atualiza status / payload / due_at / notes
🔒 DELETE /api/tasks/<id>               Cancela tarefa (cascade via query param)
```

### Processos

```
🔒 GET    /api/processes                 Lista templates de processo
🔒 POST   /api/processes/start          Inicia processo (inline: coletar_roteiros / template)
🔒 GET    /api/process-instances         Lista instâncias de processo (query: status)
🔒 GET    /api/process-instances/<id>   Detalhe + tasks vinculadas
```

### Grupos

```
🔒 GET    /api/groups                   Lista grupos (query: active_only)
🔒 POST   /api/groups                   Cadastra grupo
🔒 DELETE /api/groups/<name>            Remove grupo
```

### Histórico de Mensagens

```
🔒 GET    /api/messages                 Histórico de envios (query: limit)
```

### Biblioteca

```
🔒 GET    /api/books                    Lista livros indexados
🔒 DELETE /api/books/<id>              Remove livro e chunks
```

---

## Payload Shapes (para o React)

### Task (criação)
```typescript
interface CreateTaskPayload {
  title: string
  type: 'reminder' | 'notify_hermes' | 'send_message' | 'wait' | 
        'collect_from_contact' | 'ask_hermes' | 'compile'
  payload: Record<string, unknown>
  due_at?: string            // ISO 8601 com timezone
  contact_phone?: string     // obrigatório para collect_from_contact
}
```

### Task (resposta)
```typescript
interface Task {
  id: string
  process_instance_id: string | null
  step_id: string | null
  title: string
  type: string
  status: 'blocked' | 'pending' | 'in_progress' | 'done' | 'missed' | 'cancelled' | 'failed'
  due_at: string | null
  timing_type: string
  depends_on: string[]
  on_delay: string
  payload: Record<string, unknown>
  contact_phone: string | null
  notes: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
}
```

### Contact (admin)
```typescript
interface Contact {
  number: string   // apenas dígitos
  name: string
}
```

### Group
```typescript
interface Group {
  id: string
  name: string
  jid: string      // ex: 120363xxxxxx@g.us
  category: string
  active: boolean
  created_at: string
}
```

---

## Notas de Integração

- **CORS**: Flask não tem CORS configurado — adicionar `flask-cors` antes de subir o frontend separado
- **withCredentials**: obrigatório nas requests do axios para enviar o session cookie
- **Fuso horário**: todos os timestamps são UTC (ISO 8601 com `+00:00`). O frontend deve converter para BRT (UTC-3)
- **Paginação**: ainda não implementada — `limit` e `offset` a serem adicionados nos endpoints REST
- **Scheduler**: roda a cada 60s em background thread — o frontend deve fazer polling ou usar Supabase Realtime para atualizações ao vivo
