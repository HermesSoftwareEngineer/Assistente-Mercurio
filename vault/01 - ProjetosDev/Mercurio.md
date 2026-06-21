# Projeto Mercúrio

Assistente pessoal de Hermes Barbosa via WhatsApp.
Github: https://github.com/HermesSoftwareEngineer/Assistente-Mercurio 
Frotend: https://github.com/HermesSoftwareEngineer/Mercurio-Front
Instruções ao Bot: [[RegrasGerais]]

## Stack
- **Interface:** WhatsApp via Evolution API (baileys)
- **Backend:** Python + Flask
- **Agente:** Tool Use loop (OpenAI SDK + DeepSeek)
- **LLM:** DeepSeek V4 Flash
- **Transcrição de áudio:** Google Gemini 2.5 Flash
- **Rastreamento:** LangSmith
- **Memória:** Obsidian vault
- **Banco:** Supabase (grupos + histórico)
- **Tunnel:** ngrok (domínio estático)

## Funcionalidades
- Responde mensagens de texto e áudio (transcrição automática)
- Gera mensagens formatadas para WhatsApp a partir de linguagem natural
- Envia para grupos cadastrados com aprovação de rascunho ou envio direto
- Envia mensagem direta para qualquer contato
- Gerencia grupos (cadastrar / listar / remover)
- Histórico de envios no Supabase
- Memória persistente no vault (notas, tarefas, contexto)
- Busca semântica no vault
- Painel admin web em `/admin` (login com API key, gerenciar números autorizados)
- Múltiplos números autorizados (arquivo `data/authorized_numbers.json`)
- Histórico de conversa por número (últimas 20 mensagens)
- `/reset` para reiniciar a conversa
- Distinção dono (Hermes) × outros autorizados (acesso restrito a tools)

## Fluxo do Agente
```
mensagem (texto ou áudio)
  → [áudio] transcreve com Gemini 2.5 Flash
  → LLM (DeepSeek) com tools disponíveis
  → executa tools em loop até resposta final
  → responde via Evolution API
```

## Tools disponíveis
| Tool | Descrição |
|---|---|
| `generate_draft` | Gera rascunho formatado para WhatsApp |
| `send_message` | Envia para grupos |
| `send_direct_message` | Envia mensagem direta para um contato |
| `list_groups` | Lista grupos cadastrados |
| `add_group` | Cadastra grupo |
| `remove_group` | Remove grupo |
| `query_history` | Histórico de envios |
| `save_note` | Salva no vault |
| `search_vault` | Busca no vault |

## Repositório
`C:\Users\Hermes\projetos_dev\Assistente-Mercurio`

## Status
Em desenvolvimento ativo.
