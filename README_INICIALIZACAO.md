# Guia de Inicializacao - Mercurio

Este documento explica como configurar e usar o script `iniciar.bat` para subir todo o ambiente do Mercurio automaticamente.

---

## 1. Configurar o dominio estatico do ngrok

No arquivo `iniciar.bat`, localize a linha:

```bat
start "ngrok" cmd /k "ngrok http 5000 --domain=DOMINIO_ESTATICO_AQUI"
```

Substitua `DOMINIO_ESTATICO_AQUI` pelo seu dominio estatico do ngrok:

```bat
start "ngrok" cmd /k "ngrok http 5000 --domain=sulfide-circle-aptly.ngrok-free.dev"
```

> **Importante:** O dominio estatico so funciona com conta paga do ngrok.  
> Caso use a versao gratuita, remova `--domain=...` para usar um dominio aleatorio.

---

## 2. Adicionar o .bat na inicializacao do Windows

1. Pressione `Win + R`, digite `shell:startup` e aperte Enter
2. A pasta **Inicializar** sera aberta
3. Copie um atalho do `iniciar.bat` para esta pasta:
   - Clique com o botao direito no arquivo `iniciar.bat`
   - **Enviar para > Area de trabalho (criar atalho)**
   - Mova o atalho da area de trabalho para a pasta `shell:startup`

Pronto! O ambiente subira automaticamente sempre que o Windows iniciar.

---

## 3. Criar um atalho na Area de Trabalho

1. Clique com o botao direito no arquivo `iniciar.bat`
2. Selecione **Enviar para > Area de trabalho (criar atalho)**
3. (Opcional) Renomeie o atalho na area de trabalho para `Iniciar Mercurio`
4. (Opcional) Clique com o botao direito no atalho > **Propriedades > Alterar icone** para personalizar

---

## Estrutura dos servicos

| Servico       | Porta  | Comando                                      |
|---------------|--------|----------------------------------------------|
| Evolution API | 8080   | `npm run start:prod`                         |
| ngrok         | -      | Expoe a porta 5000 via HTTPS                 |
| Mercurio      | 5000   | `python app/main.py`                         |

---

## Requisitos

- Node.js instalado
- Python 3.10+ instalado
- ngrok instalado e configurado
- `.env` do Evolution API configurado com banco de dados
- `.env` do Mercurio configurado na raiz do projeto
