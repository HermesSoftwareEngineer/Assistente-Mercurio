# Convenções do Vault Mercúrio

## Nomenclatura de arquivos
- Pessoa: NomeCompleto.md → pasta 04 - Conversas/Pessoas/
- Projeto dev: NomeProjeto.md → pasta 01 - ProjetosDev/
- Grupo WhatsApp: Nome do Grupo.md → 04 - Conversas/
- Evento pontual: YYYY-MM-DD NomeEvento.md → pasta da área
- Contexto permanente: NomeTema.md → pasta da área

## Pastas
- 00 - Contexto Pessoal/ → perfil do Hermes e áreas de vida
- 01 - ProjetosDev/ → projetos de desenvolvimento
- 03 - Tarefas/ → tarefas e pendências
- 04 - Conversas/ → contatos e grupos WhatsApp
- 05 - Trabalho/ → contexto profissional
- 06 - Igreja/ → tudo relacionado à IASDMR
- 07 - Mercurio/ → configurações e instruções do agente

## Frontmatter obrigatório (toda nota nova)
---
tipo: pessoa | projeto | evento | grupo | contexto | tarefa | log
tags: [lista, de, tags]
criado_em: YYYY-MM-DD
atualizado_em: YYYY-MM-DD
---

## Wikilinks
- Toda menção a pessoa, projeto ou grupo → use [[Nome]] sem extensão
- Links "fantasma" são intencionais — sinalizam lacuna no vault
- Nunca use caminho completo no wikilink

## Tipos de nota
- pessoa: alguém mencionado com nome + função/relação
- projeto: iniciativa com escopo e objetivo
- evento: acontecimento pontual com data
- grupo: grupo WhatsApp ou grupo de pessoas
- contexto: informação permanente sobre uma área
- tarefa: item acionável com prazo
- log: registro automático de ações do agente
