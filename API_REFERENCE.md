# API Reference — Assistente Mercúrio

Todos os endpoints REST estão sob o prefixo `/api/`. A autenticação é baseada em sessão Flask — é necessário fazer login via `/admin/login` antes de usar qualquer endpoint.

---

## Autenticação

### `POST /admin/login`
Inicia uma sessão autenticada.

**Body:**
```json
{ "key": "<EVOLUTION_API_KEY>" }
```

**Resposta:** `200 OK` com `{"ok": true}` ou `401` se a chave for inválida.

---

## Contatos (`/api/contacts`)

Gerencia a lista de contatos autorizados a conversar com o Mercúrio. O campo `active` permite desativar temporariamente um contato sem excluí-lo — contatos inativos são ignorados na autorização do webhook.

### `GET /api/contacts`
Lista todos os contatos (ativos e inativos).

**Resposta:**
```json
{
  "contacts": [
    { "id": "uuid", "number": "5585999998888", "name": "João", "active": true, "created_at": "..." }
  ],
  "count": 1
}
```

### `POST /api/contacts`
Adiciona um novo contato autorizado.

**Body:**
```json
{ "number": "5585999998888", "name": "João" }
```

**Resposta:** `201 Created` com `{"ok": true, "number": "...", "name": "..."}`.

### `DELETE /api/contacts/<number>`
Remove permanentemente um contato. Para silenciar sem excluir, use `PATCH` com `active: false`.

**Resposta:** `200 OK` com `{"ok": true}` ou `404` se não encontrado.

### `PATCH /api/contacts/<number>`
Atualiza `active` e/ou `name` de um contato.

**Body** (ao menos um campo):
```json
{ "active": false }
{ "name": "João Silva" }
{ "active": true, "name": "João Silva" }
```

**Resposta:** `200 OK` com `{"ok": true}` ou `404` se não encontrado.

---

## Configurações (`/api/settings`)

Chave/valor do sistema armazenado na tabela `app_settings`.

### `GET /api/settings`
Retorna todas as configurações como objeto.

**Resposta:**
```json
{ "settings": { "allow_all": "false" } }
```

### `PATCH /api/settings`
Atualiza uma ou mais chaves. Booleanos são convertidos para `"true"`/`"false"`.

**Body:**
```json
{ "allow_all": true }
```

**Resposta:** `200 OK` com `{"ok": true}`.

**Chaves conhecidas:**

| Chave | Valores | Descrição |
|---|---|---|
| `allow_all` | `"true"` / `"false"` | Se `true`, qualquer número pode enviar mensagens, ignorando a lista de contatos |

---

## Conversas (`/api/conversations`)

Acesso read-only ao histórico de conversas armazenado na tabela `conversation_history`.

### `GET /api/conversations`
Lista um resumo de todas as conversas existentes, ordenadas pela mais recente.

**Resposta:**
```json
{
  "conversations": [
    {
      "phone": "5585999998888",
      "name": "João",
      "message_count": 14,
      "last_message": "Tudo bem, obrigado!",
      "mode": "bot",
      "transferred_at": null,
      "transferred_by": null,
      "updated_at": "2026-06-19T10:30:00Z"
    }
  ],
  "count": 1
}
```

**Campo `mode`:** `"bot"` (agente ativo) ou `"human"` (conversa em atendimento humano).

### `GET /api/conversations/<phone>`
Retorna o histórico completo de uma conversa.

**Resposta:**
```json
{
  "phone": "5585999998888",
  "session_id": "abc123",
  "mode": "bot",
  "messages": [
    { "role": "user", "content": "Olá" },
    { "role": "assistant", "content": "Olá! Como posso ajudar?" }
  ],
  "count": 2
}
```

### `POST /api/conversations/<phone>/reset`
Limpa o histórico de uma conversa e reinicia a sessão LangSmith.

**Resposta:** `200 OK` com `{"ok": true, "phone": "..."}`.

---

## Sessões e Handoff (`/api/sessions`)

Controla o modo de cada conversa: `"bot"` (agente responde automaticamente) ou `"human"` (agente silencia, Hermes responde diretamente pelo WhatsApp).

**Fluxo de handoff:**
1. O agente chama a tool `transfer_to_human` — ou o admin seta manualmente via `PATCH /api/sessions/<phone>/mode`
2. O usuário recebe uma mensagem informando que será atendido por humano
3. Hermes recebe notificação no WhatsApp com o número e o motivo
4. Mensagens subsequentes do usuário são salvas no histórico mas **não processadas pelo agente**
5. Quando Hermes termina, o admin clica "devolver ao bot" → `PATCH` com `{"mode": "bot"}`
6. A próxima mensagem do usuário volta a ser processada pelo agente normalmente

### `GET /api/sessions`
Lista todas as sessões registradas com seu modo atual.

**Resposta:**
```json
{
  "sessions": [
    {
      "phone": "5585999998888",
      "name": "João",
      "mode": "human",
      "transferred_at": "2026-06-19T10:00:00Z",
      "transferred_by": "agent",
      "handoff_msg_sent": true
    }
  ],
  "count": 1
}
```

**Campo `transferred_by`:** `"agent"` (tool chamada pelo LLM) ou `"admin"` (alterado manualmente via dashboard).

### `PATCH /api/sessions/<phone>/mode`
Altera o modo de uma conversa. Use `"bot"` para devolver ao agente, `"human"` para assumir manualmente.

**Body:**
```json
{ "mode": "bot" }
```

ou

```json
{ "mode": "human" }
```

**Resposta:** `200 OK` com `{"ok": true, "phone": "...", "mode": "..."}`.

> Ao setar `"human"` via admin, o usuário **não** recebe mensagem automática (diferente da tool `transfer_to_human`). Para notificar o usuário, envie uma mensagem manualmente pelo WhatsApp.

---

## Prompts (`/api/prompts`)

Prompts do agente editáveis e persistidos no banco. Sobrevivem a redeploys. Alterações entram em vigor na próxima mensagem processada — sem necessidade de reiniciar o servidor.

Existem dois prompts:
- `owner` — usado quando o número é o do Hermes (`AUTHORIZED_NUMBER`)
- `non_owner` — usado para todos os outros contatos

O prompt `non_owner` suporta dois placeholders substituídos em runtime:
- `{caller}` — número de telefone do usuário atual
- `{owner_phone}` — número do Hermes (de `AUTHORIZED_NUMBER`)

As seções de formatação WhatsApp e regras de memória são **sempre** acrescentadas pelo código após o conteúdo editável — não é necessário repeti-las no prompt.

### `GET /api/prompts`
Retorna os dois prompts com conteúdo e data de atualização.

**Resposta:**
```json
{
  "prompts": [
    { "key": "non_owner", "content": "Você é o Mercúrio...", "updated_at": "2026-06-19T..." },
    { "key": "owner",     "content": "Você é o Mercúrio...", "updated_at": "2026-06-19T..." }
  ]
}
```

### `PUT /api/prompts/<key>`
Substitui o conteúdo de um prompt. `key` deve ser `"owner"` ou `"non_owner"`.

**Body:**
```json
{ "content": "Novo conteúdo do prompt..." }
```

**Resposta:** `200 OK` com `{"ok": true, "key": "..."}` ou `400` se o conteúdo for vazio.

---

## Grupos (`/api/groups`)

### `GET /api/groups`
Lista grupos. Por padrão retorna apenas grupos ativos.

**Query params:** `active_only=false` para incluir inativos.

**Resposta:**
```json
{
  "groups": [
    { "id": "uuid", "name": "Jovens", "jid": "120363...@g.us", "category": "Igreja", "active": true }
  ]
}
```

### `POST /api/groups`
Cadastra um novo grupo.

**Body:**
```json
{ "name": "Jovens", "jid": "120363xxxxxx@g.us", "category": "Igreja" }
```

**Resposta:** `201 Created`.

### `DELETE /api/groups/<name>`
Marca o grupo como inativo (soft delete).

---

## Mensagens Enviadas (`/api/messages`)

Auditoria de mensagens enviadas pelo agente para grupos.

### `GET /api/messages`
**Query params:** `limit=20` (padrão).

**Resposta:**
```json
{
  "messages": [
    { "content": "Aviso...", "groups_sent": ["Jovens"], "approved_by": "5585...", "sent_at": "..." }
  ],
  "count": 1
}
```

---

## Livros (`/api/books`)

### `GET /api/books`
Lista livros indexados com título, páginas e número de trechos vetorizados.

### `DELETE /api/books/<book_id>`
Remove um livro e todos os seus chunks do banco.

---

## Webhook

### `POST /webhook/whatsapp`
Recebe eventos da Evolution API. Não requer autenticação de sessão.

Eventos processados: `messages.upsert`, `message.received`.

Mensagens de grupos (`@g.us`) são ignoradas. O webhook verifica automaticamente se a conversa está em modo `"human"` — nesse caso, a mensagem é salva no histórico mas o agente não é acionado.

### `GET /health`
Health check. Retorna `{"status": "healthy"}`.
