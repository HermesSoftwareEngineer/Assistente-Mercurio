# PRD — Sistema de Tarefas Proativas do Mercúrio

**Versão:** 1.0  
**Data:** 2026-06-14  
**Status:** Aprovado para implementação

---

## 1. Visão Geral

### Problema
O Mercúrio hoje é 100% reativo — só age quando recebe uma mensagem. Hermes precisa de um assistente que também **aja de forma proativa no momento certo**: cobrar pessoas, enviar mensagens agendadas, coletar roteiros de culto, lembrar compromissos e executar processos recorrentes.

### Solução
Transformar o Mercúrio em um agente com capacidade de **agendamento, dependência entre tarefas e execução assíncrona**, mantendo a interface principal via WhatsApp. Toda a configuração pode ser feita conversacionalmente (WhatsApp) ou via painel admin.

### Princípios de design
- **WhatsApp como interface central**: criar, consultar e gerenciar tarefas/processos via chat
- **Hermes sempre no controle**: decisões não-triviais (ambiguidades, atrasos) sempre passam por ele
- **Execução sem LLM quando possível**: handlers diretos para tarefas simples; LLM só quando necessário
- **Tolerância a máquina offline**: política clara de tarefas atrasadas

---

## 2. Conceitos e Terminologia

### ProcessTemplate (SOP)
Blueprint reutilizável que define um fluxo de trabalho com múltiplos passos. Pode ter nome, parâmetros variáveis e ser disparado manualmente ou por cron.

**Exemplo:** "Coletar Rotários de Culto" — processo que cobra participantes, coleta respostas e compila o rotário final.

### ProcessInstance
Uma execução concreta de um ProcessTemplate, com parâmetros preenchidos (ex: "Rotários Culto 15/06 — João, Maria, Pedro").

### Task (Tarefa)
Unidade atômica de trabalho. Pode ser filha de uma ProcessInstance ou standalone (sem processo pai).

### StandaloneTask
Tarefa avulsa criada diretamente, sem processo pai.

---

## 3. Tipos de Task

| Tipo | Descrição | Espera resposta? | Usa LLM? |
|------|-----------|-----------------|----------|
| `reminder` | Envia lembrete a Hermes no horário | Não | Não |
| `notify_hermes` | Notificação de status/alerta a Hermes | Não | Não |
| `ask_hermes` | Pergunta algo a Hermes e aguarda resposta para prosseguir | Sim | Não |
| `send_message` | Envia mensagem para grupo(s) ou contato(s) | Não | Não |
| `collect_from_contact` | Envia mensagem a um contato e aguarda resposta | Sim | Não (recepção) |
| `compile` | LLM compila dados coletados em documento final | Não | Sim |
| `wait` | Aguarda até horário específico antes de avançar | Não | Não |

---

## 4. Status de uma Task

```
blocked → pending → in_progress → done
                  ↘
               missed | cancelled | failed
```

| Status | Significado |
|--------|------------|
| `blocked` | Dependência ainda não concluiu |
| `pending` | Dependências ok, aguardando `due_at` |
| `in_progress` | Em execução / aguardando resposta externa |
| `done` | Concluída com sucesso |
| `missed` | Prazo passou sem execução (máquina offline > 48h) |
| `cancelled` | Cancelada manualmente |
| `failed` | Tentou executar, encontrou erro |

---

## 5. Dependências entre Tasks

### Declaração
Cada task tem um campo `depends_on: [task_id, ...]`. Uma task só sai de `blocked` para `pending` quando todas as suas dependências estiverem em `done`.

### Tipos de timing para tasks dependentes

| `timing_type` | Comportamento |
|--------------|--------------|
| `immediate` | Executa assim que a dependência conclui |
| `after_hours: N` | Executa N horas após a dependência concluir |
| `at: datetime` | Executa em data/hora fixa, independente da dependência |

### Comportamento em caso de atraso (`on_delay`)

**Padrão para todos os casos:** `notify`

| `on_delay` | O que acontece quando deadline chega com dependência incompleta |
|-----------|---------------------------------------------------------------|
| `notify` | Notifica Hermes com estado completo e aguarda decisão (padrão) |
| `proceed` | Avança com o que tem (útil para compilação com respostas parciais) |
| `cascade` | Empurra o `due_at` dos dependentes pelo mesmo tempo de atraso |

### Execução paralela
Tasks que dependem do mesmo pai mas não dependem entre si são executadas em paralelo. Visualmente aparecem como tasks individuais na lista.

---

## 6. Política de Tarefas Atrasadas (Máquina Offline)

| Atraso | Comportamento |
|--------|--------------|
| ≤ 48h | Executa imediatamente ao ligar a máquina |
| > 48h | Notifica Hermes: _"Tinha tarefa pendente que não consegui executar: [título], vencida em [data]. O que faço?"_ e aguarda instrução |

O scheduler verifica tarefas atrasadas na inicialização do Flask.

---

## 7. Fluxo de Disambiguação de Respostas (Opção C)

Quando uma mensagem chega de um contato que tem task `in_progress` do tipo `collect_from_contact` ou `ask_hermes`:

1. O webhook injeta o contexto da task no prompt do agente para aquela conversa
2. O agente usa julgamento para determinar se a mensagem é resposta à task
3. Se **claramente é resposta** → atualiza task (`status: done`, salva resposta no payload)
4. Se **claramente não é** → processa como conversa normal, task permanece `in_progress`
5. Se **ambíguo** → notifica Hermes: _"[Nome] mandou: '[mensagem]'. Isso é sobre [assunto da task]?"_ e aguarda decisão

---

## 8. Exemplos de Processos

### 8.1 Coletar Rotários de Culto

```
Trigger: manual (Hermes pede via WhatsApp)
Parâmetros: event_name, participants[], deadline

Passo 1 — ask_hermes
  "Quem vai participar do {event_name}? Me informe nome e número de cada um."
  → aguarda Hermes confirmar lista
  → depende_de: nenhum | timing: immediate

Passo 2a..N — collect_from_contact (um por participante, em paralelo)
  "Oi {name}! Você vai participar do {event_name}. Pode me enviar seu roteiro?"
  → aguarda até {deadline}
  → on_delay: notify (Hermes decide se avança sem a resposta)
  → depende_de: Passo 1 | timing: immediate

Passo 3 — compile
  "Monte um roteiro completo do {event_name} com os roteiros recebidos, na ordem [instrução]"
  → depende_de: todos os Passo 2 concluídos | timing: immediate
  → on_delay: notify

Passo 4 — send_message
  Envia rotário compilado para o(s) grupo(s) configurados
  → depende_de: Passo 3 | timing: immediate

Passo 5 — notify_hermes
  "✅ Rotário do {event_name} enviado no grupo!"
  → depende_de: Passo 4 | timing: immediate
```

### 8.2 Sequência de Follow-up

```
Trigger: manual
Parâmetros: contact_name, contact_phone, subject, message, interval_hours, max_retries

Passo 1 — collect_from_contact
  Envia {message} para {contact_phone}
  → aguarda {interval_hours}h
  → on_delay: cascade (repete até max_retries)

Passo 2 — notify_hermes (condicional — só se respondeu)
  "{contact_name} respondeu sobre {subject}! Resposta: [...]"

OU (se max_retries atingido sem resposta):
  notify_hermes: "{contact_name} não respondeu após {max_retries} tentativas sobre {subject}."
```

### 8.3 Mensagem Agendada

```
Trigger: manual ou cron
Parâmetros: content, target_type (group|direct), targets[], scheduled_at

Passo 1 — wait
  Aguarda até {scheduled_at}

Passo 2 — send_message
  Envia {content} para {targets}
  → depende_de: Passo 1
```

### 8.4 Lembrete Pessoal

```
Trigger: manual
Parâmetros: message, due_at

Passo 1 — reminder
  Envia {message} para Hermes em {due_at}
```

---

## 9. Schema do Banco de Dados (Supabase)

### Tabela `processes`
```sql
CREATE TABLE processes (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT NOT NULL,
  description   TEXT,
  trigger_mode  TEXT NOT NULL DEFAULT 'manual'
                CHECK (trigger_mode IN ('manual', 'cron')),
  recurrence_cron TEXT,             -- ex: "0 18 * * 5" (sextas às 18h)
  parameters_schema JSONB DEFAULT '{}', -- definição dos parâmetros esperados
  steps         JSONB NOT NULL DEFAULT '[]', -- array de StepDefinition
  active        BOOLEAN DEFAULT TRUE,
  created_at    TIMESTAMPTZ DEFAULT now(),
  updated_at    TIMESTAMPTZ DEFAULT now()
);
```

**Estrutura de `steps` (array de objetos):**
```json
[
  {
    "step_id": "step_1",
    "type": "ask_hermes",
    "title": "Confirmar participantes",
    "message_template": "Quem vai participar do {event_name}?",
    "depends_on": [],
    "timing_type": "immediate",
    "timing_value": null,
    "on_delay": "notify",
    "for_each": null
  },
  {
    "step_id": "step_2",
    "type": "collect_from_contact",
    "title": "Coletar rotário de {name}",
    "message_template": "Oi {name}! Pode me enviar seu rotário para {event_name}?",
    "depends_on": ["step_1"],
    "timing_type": "immediate",
    "timing_value": null,
    "on_delay": "notify",
    "for_each": "participants"
  }
]
```

### Tabela `process_instances`
```sql
CREATE TABLE process_instances (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  process_id    UUID REFERENCES processes(id) ON DELETE SET NULL,
  process_name  TEXT NOT NULL,     -- snapshot do nome no momento de criação
  status        TEXT NOT NULL DEFAULT 'in_progress'
                CHECK (status IN ('in_progress', 'done', 'cancelled', 'failed')),
  parameters    JSONB DEFAULT '{}', -- valores preenchidos na hora de disparar
  notes         TEXT,
  started_at    TIMESTAMPTZ DEFAULT now(),
  completed_at  TIMESTAMPTZ,
  created_at    TIMESTAMPTZ DEFAULT now()
);
```

### Tabela `tasks`
```sql
CREATE TABLE tasks (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  process_instance_id UUID REFERENCES process_instances(id) ON DELETE CASCADE,
  step_id             TEXT,            -- referência ao step_id dentro do template
  title               TEXT NOT NULL,
  type                TEXT NOT NULL
                      CHECK (type IN (
                        'reminder', 'notify_hermes', 'ask_hermes',
                        'send_message', 'collect_from_contact', 'compile', 'wait'
                      )),
  status              TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN (
                        'blocked', 'pending', 'in_progress',
                        'done', 'missed', 'cancelled', 'failed'
                      )),
  due_at              TIMESTAMPTZ,
  timing_type         TEXT DEFAULT 'immediate'
                      CHECK (timing_type IN ('immediate', 'after_hours', 'at')),
  timing_value        TEXT,            -- horas (after_hours) ou ISO datetime (at)
  depends_on          JSONB DEFAULT '[]', -- array de task UUIDs
  on_delay            TEXT DEFAULT 'notify'
                      CHECK (on_delay IN ('notify', 'proceed', 'cascade')),
  payload             JSONB DEFAULT '{}',
  contact_phone       TEXT,            -- para collect_from_contact / follow_up
  notes               TEXT,
  created_at          TIMESTAMPTZ DEFAULT now(),
  updated_at          TIMESTAMPTZ DEFAULT now(),
  completed_at        TIMESTAMPTZ
);

-- Índices para o scheduler
CREATE INDEX idx_tasks_status_due ON tasks (status, due_at)
  WHERE status IN ('pending', 'in_progress');
CREATE INDEX idx_tasks_contact ON tasks (contact_phone)
  WHERE status = 'in_progress';
CREATE INDEX idx_tasks_process ON tasks (process_instance_id);
```

**Estrutura de `payload` por tipo:**

```json
// reminder / notify_hermes
{ "message": "Texto do lembrete" }

// ask_hermes
{
  "question": "Quem vai participar do culto de domingo?",
  "response": null,          // preenchido quando Hermes responde
  "context_key": "participants"  // chave que outros passos lerão
}

// send_message
{
  "content": "Texto da mensagem",
  "target_type": "group",     // "group" | "direct"
  "targets": ["Jovens", "Sede"]
}

// collect_from_contact
{
  "contact_name": "João",
  "message": "Oi João! Pode me enviar seu rotário?",
  "response": null,           // preenchido quando João responde
  "retry_count": 0,
  "max_retries": 3,
  "retry_interval_hours": 1
}

// compile
{
  "instructions": "Monte o rotário completo na ordem: louvor, oração, palavra",
  "source_task_ids": ["uuid-1", "uuid-2"],  // IDs das collect tasks com as respostas
  "result": null              // preenchido após compilação
}

// wait
{ "reason": "Aguardando horário de envio" }
```

---

## 10. Arquitetura de Componentes

### Diagrama geral

```
[WhatsApp — Hermes]
        ↓ mensagem
[Webhook Flask — main.py]
        ↓ verifica tasks ativas do remetente (context injection)
[Agente Conversacional — agent.py]
        ↓ usa novas tools
[app/services/tasks.py]  ←→  [Supabase: tasks, processes, process_instances]
        ↑ polling 60s
[Task Runner — scheduler.py]
        ↓ dispatcher por tipo
  ┌─────┬──────────────┬────────────────┬───────────┬──────────┐
reminder notify_hermes send_message collect_from compile    wait
(direto) (direto)      (direto)     _contact     (LLM call) (no-op)
                                    (direto)
        ↓
[Evolution API — WhatsApp]
```

### Novos arquivos e responsabilidades

| Arquivo | Responsabilidade |
|---------|-----------------|
| `migrations/006_tasks.sql` | Schema das 3 novas tabelas |
| `app/services/tasks.py` | CRUD de tasks, process_instances, processes |
| `app/services/processes.py` | Instanciar templates, criar cadeia de tasks |
| `app/agent/scheduler.py` | APScheduler: polling, dispatcher, late-task check |
| `app/agent/handlers.py` | Handler por tipo de task (sem LLM exceto compile) |

### Modificações em arquivos existentes

| Arquivo | O que muda |
|---------|-----------|
| `app/agent/tools.py` | +6 tools: `create_task`, `update_task`, `list_tasks`, `cancel_task`, `start_process`, `list_processes` |
| `app/agent/prompts.py` | Seção no system prompt descrevendo capacidades de tarefas e processos |
| `app/main.py` | Iniciar scheduler no startup + injetar contexto de tasks ativas no webhook |

---

## 11. Novas Ferramentas do Agente

### `create_task`
Cria uma task standalone (sem processo pai).
```json
{
  "title": "string",
  "type": "reminder | notify_hermes | ask_hermes | send_message | collect_from_contact | compile | wait",
  "due_at": "ISO datetime (opcional)",
  "payload": "object — varia por tipo",
  "contact_phone": "string (opcional — para collect_from_contact)"
}
```

### `update_task`
Atualiza status, prazo ou notas de uma task existente.
```json
{
  "task_id": "UUID",
  "status": "done | cancelled | pending (opcional)",
  "due_at": "novo prazo (opcional)",
  "notes": "observação (opcional)",
  "payload_patch": "object — merge no payload existente (opcional)"
}
```

### `list_tasks`
Lista tasks com filtros.
```json
{
  "status": "pending | in_progress | done | ... (opcional)",
  "type": "tipo (opcional)",
  "limit": "número (padrão: 10)"
}
```

### `cancel_task`
Cancela uma task e opcionalmente suas dependentes.
```json
{
  "task_id": "UUID",
  "cascade": "boolean — cancela dependentes também (padrão: false)"
}
```

### `start_process`
Instancia e dispara um ProcessTemplate pelo nome.
```json
{
  "process_name": "nome do template",
  "parameters": "object — valores dos parâmetros do template"
}
```

### `list_processes`
Lista ProcessTemplates disponíveis.
```json
{
  "active_only": "boolean (padrão: true)"
}
```

---

## 12. Task Runner (Scheduler)

### Configuração
- Biblioteca: `APScheduler` (BackgroundScheduler)
- Polling interval: 60 segundos
- Inicia junto com o Flask no `main.py`

### Fluxo de polling

```
1. Busca tasks com (status='pending' AND due_at <= now())
2. Para cada task:
   a. Verifica se todas as dependências estão 'done'
      → Se não: mantém 'blocked', segue
   b. Atualiza status para 'in_progress'
   c. Chama handler correspondente ao tipo
   d. Handler atualiza status final (done/failed)
   e. Verifica tasks 'blocked' que dependiam desta → desbloqueia (→ pending) se elegível

3. Verifica tasks com (status='in_progress' AND due_at <= now() AND on_delay='notify')
   → Notifica Hermes com estado do processo e aguarda instrução

4. Verifica tasks atrasadas na inicialização:
   - due_at entre (now() - 48h) e now(): executa imediatamente
   - due_at < (now() - 48h): notifica Hermes, marca como 'missed'
```

### Handlers

**`reminder_handler(task)`**
```
→ send_direct(OWNER_PHONE, payload["message"])
→ task.status = "done"
```

**`notify_hermes_handler(task)`**
```
→ send_direct(OWNER_PHONE, payload["message"])
→ task.status = "done"
```

**`send_message_handler(task)`**
```
→ if target_type == "group": send_group_message(targets, content)
→ if target_type == "direct": send_direct(target, content)
→ task.status = "done"
```

**`collect_from_contact_handler(task)`**
```
→ send_direct(contact_phone, payload["message"])
→ task.status = "in_progress"  (aguarda resposta via webhook)
→ Scheduler monitora: se due_at passado e sem resposta → on_delay logic
```

**`compile_handler(task)`**
```
→ Busca tasks filhas referenciadas em payload["source_task_ids"]
→ Monta contexto com respostas coletadas
→ Chama LLM (mini-agente, sem histórico) com payload["instructions"]
→ Salva resultado em payload["result"]
→ task.status = "done"
→ Unblocks dependentes
```

**`wait_handler(task)`**
```
→ Só verifica se due_at chegou
→ Se sim: task.status = "done" → unblocks dependentes
```

**`ask_hermes_handler(task)`**
```
→ send_direct(OWNER_PHONE, payload["question"])
→ task.status = "in_progress"  (aguarda resposta de Hermes via webhook)
```

---

## 13. Context Injection no Webhook

Quando chega mensagem de qualquer remetente, antes de chamar `run_agent()`:

```python
# Busca tasks in_progress que esperam resposta desse número
active_tasks = get_active_tasks_for_phone(phone)

if active_tasks:
    # Injeta contexto no prompt do agente para esse turn
    task_context = format_task_context(active_tasks)
    # Agent usa julgamento para decidir se é resposta à task
    # Se sim: chama update_task(task_id, status="done", payload_patch={"response": text})
```

**Formato do contexto injetado:**
```
[Sistema — Tarefas Ativas]
Este contato tem as seguintes tarefas aguardando resposta:
- [UUID] Coletar rotário do Culto de Dom 15/06 (collect_from_contact) — sobre: rotário do culto
Se a mensagem deste contato for claramente a resposta para uma dessas tarefas, 
chame update_task com status "done" e a resposta no payload_patch.
Se for ambíguo, pergunte a Hermes.
```

---

## 14. Regras de Negócio

### Criação de tarefas
- Toda task deve ter `title` e `type`
- Tasks do tipo `collect_from_contact` e `ask_hermes` são automaticamente `in_progress` após execução (aguardam resposta)
- Tasks sem `due_at` são executadas imediatamente (ou logo que dependências concluírem)
- Tasks com dependências começam como `blocked`

### Cadeia de dependência
- Uma task só passa de `blocked` para `pending` quando TODAS as suas dependências estão `done`
- Cancelar uma task com `cascade=true` propaga `cancelled` para todas as dependentes diretas e indiretas
- `failed` em uma task obrigatória notifica Hermes com estado completo da cadeia

### Processos
- Um ProcessTemplate pode ser instanciado múltiplas vezes simultaneamente
- Parâmetros do template são interpolados com `{param}` nos `message_template`s de cada passo
- `for_each` em um passo cria uma task filha por item da lista referenciada
- SOPs com cron: ao disparar, Hermes é notificado e confirmado antes da execução se houver parâmetros variáveis

### Segurança / controle
- Apenas o owner (Hermes) pode criar, cancelar ou modificar tarefas via chat
- Tarefas críticas (compilação, envio a grupos) notificam Hermes antes de executar quando acionadas por cron
- Nenhuma task pode enviar para grupos sem conteúdo validado

---

## 15. Plano de Implementação

### Fase 1 — Fundação
**Entrega:** lembretes e mensagens agendadas funcionando

- [ ] Migration `006_tasks.sql` (tabelas `processes`, `process_instances`, `tasks`)
- [ ] `app/services/tasks.py` — CRUD básico de tasks
- [ ] `app/agent/scheduler.py` — APScheduler, polling 60s, late-task check
- [ ] `app/agent/handlers.py` — `reminder_handler`, `notify_hermes_handler`, `send_message_handler`
- [ ] `app/agent/tools.py` — tools: `create_task`, `update_task`, `list_tasks`, `cancel_task`
- [ ] `app/agent/prompts.py` — seção sobre capacidades de tarefas
- [ ] `app/main.py` — iniciar scheduler no startup
- [ ] `requirements.txt` — adicionar `APScheduler`

**Teste de validação:**
1. "Me lembra de checar os avisos amanhã às 8h" → lembrete criado → bot manda na hora certa
2. "Envia esse aviso no grupo Jovens domingo às 10h" → mensagem enviada no horário
3. "Quais tarefas tenho pendentes?" → lista correta
4. Desligar máquina, religar antes de 48h → tasks executam ao religar

### Fase 2 — Follow-up
**Entrega:** cobranças com retry automático

- [ ] `collect_from_contact_handler` no `handlers.py`
- [ ] Lógica de retry (incrementa retry_count, reagenda, para no max_retries)
- [ ] Context injection no webhook para captura de respostas
- [ ] Notificação ao atingir max_retries
- [ ] Tool `create_task` com suporte a follow-up

**Teste de validação:**
1. "Cobra João sobre o rotário, se não responder em 1h cobra de novo, até 3 vezes"
2. João responde → task encerrada, Hermes notificado
3. João não responde 3x → Hermes notificado do esgotamento

### Fase 3 — Collection (Rotários)
**Entrega:** coleta automática de rotários com compilação

- [ ] `compile_handler` com mini-agente LLM
- [ ] `ask_hermes_handler` e captura de resposta de Hermes no webhook
- [ ] `wait_handler`
- [ ] `start_process` tool (versão simplificada — sem template, cria cadeia inline)
- [ ] `app/services/processes.py` — instanciar cadeia de tasks a partir de parâmetros
- [ ] Notificação quando todos responderam vs deadline com parciais

**Teste de validação:**
1. "Cobra os rotários do culto de domingo com João, Maria e Pedro — prazo sábado às 18h, compila e manda no grupo Jovens"
2. João e Maria respondem → bot armazena
3. Pedro não responde até sábado às 18h → Hermes notificado, decide avançar
4. Hermes diz "manda sem o dele" → compilação executada → rotário enviado no grupo

### Fase 4 — ProcessTemplates
**Entrega:** processos nomeados e reutilizáveis

- [ ] CRUD de `processes` no `tasks.py`
- [ ] `app/services/processes.py` — instanciar template com parâmetros, `for_each`
- [ ] Tools `list_processes`, `start_process` (agora com lookup por nome)
- [ ] Criação de template conversacional ("crie um processo chamado X que faz Y")
- [ ] Suporte a `recurrence_cron` no scheduler

**Teste de validação:**
1. Criar processo "Coletar Rotários" via WhatsApp
2. Semana seguinte: "dispara o processo Coletar Rotários para [novos participantes]"
3. Configurar cron "toda sexta às 18h dispara [processo]"

### Fase 5 — Admin Panel
**Entrega:** visibilidade operacional completa

- [ ] Página de tasks: lista por status, tipo, processo
- [ ] Detalhe de ProcessInstance: visualizar cadeia com status de cada passo
- [ ] Página de processos: CRUD de templates, enable/disable cron
- [ ] Progresso de coleta: quem respondeu, quem não respondeu, ação manual

---

## 16. Dependências Técnicas

| Pacote | Uso |
|--------|-----|
| `APScheduler>=3.10` | Background scheduler para tasks |
| `supabase` (já existe) | Persistência de tasks, processes, instances |

---

## 17. Referências ao Código Atual

| Componente | Arquivo atual | Relação com este PRD |
|-----------|--------------|---------------------|
| Webhook Flask | `app/main.py` | Modificado: context injection, startup scheduler |
| Agente LLM | `app/agent/agent.py` | Modificado: recebe task context injetado |
| Tools | `app/agent/tools.py` | Expandido: +6 tools |
| Prompts | `app/agent/prompts.py` | Expandido: seção de tarefas |
| Supabase client | `app/services/supabase.py` | Base para `tasks.py` |
| Evolution API | `app/services/evolution.py` | Usado pelos handlers para envio |
