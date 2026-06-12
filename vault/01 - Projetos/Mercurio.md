# Projeto Mercúrio

Assistente pessoal de WhatsApp para comunicação de uma igreja evangélica.

## Stack
- **Interface:** WhatsApp via Evolution API (baileys)
- **Backend:** Python + Flask
- **Agente:** LangGraph (StateGraph)
- **LLM:** DeepSeek V4 Flash
- **Memória:** Obsidian vault via mcp-obsidian
- **Banco:** Supabase (grupos + histórico)
- **Infra:** Docker Compose (gunicorn --workers 1)

## Funcionalidades MVP
- Gerar avisos formatados para WhatsApp a partir de linguagem natural
- Enviar para grupos cadastrados com aprovação de rascunho
- Envio direto com "envia direto"
- Gerenciar grupos (cadastrar / listar / remover)
- Histórico de envios no Supabase
- Memória persistente: vault Obsidian lido antes de gerar e atualizado após enviar

## Repositório
`C:\Users\Hermes\projetos_dev\Assistente-Mercurio`

## Fluxo do Agente
```
recall_memory → classify_intent → generate_draft | send_to_groups | manage_groups
                                                  | query_history  | handle_unknown
                                                  | save_memory
```

## Status
Em desenvolvimento ativo.
