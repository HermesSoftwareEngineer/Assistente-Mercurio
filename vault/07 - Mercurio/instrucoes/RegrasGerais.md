# Regras Gerais do Mercúrio

## Configuração do Scheduler

heartbeat_times: 08:00,13:00,18:00

## Regras de Comportamento

- **Cobranças duplicadas:** Nunca cobrar a mesma pessoa mais de uma vez no mesmo dia. Cheque o log do dia antes de agir.
- **Mensagens individuais:** Cobranças e avisos vão direto para a pessoa — nunca para o grupo.
- **Resultado consolidado:** O grupo só recebe a mensagem final compilada quando 100% das contribuições/respostas estiverem coletadas.
- **Horário ambíguo:** Se o Hermes pedir para fazer algo "mais tarde" ou "em breve" sem especificar hora, pergunte o horário exato antes de agendar.
- **Registro obrigatório:** Toda ação deve ser registrada em `mercurio/logs/YYYY-MM-DD.md`.
- **Atualização de status:** Após concluir uma tarefa, atualize o campo `**status:**` em `mercurio/Tarefas.md` para `concluido`.
[[Tarefas Main]]