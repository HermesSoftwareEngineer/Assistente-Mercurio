@echo off
chcp 65001 >nul
title Mercurio - Inicializacao

echo ============================================
echo  Iniciando todos os servicos do Mercurio...
echo ============================================
echo.

echo Encerrando servicos anteriores (se houver)...
taskkill /f /im node.exe >nul 2>&1
taskkill /f /im ngrok.exe >nul 2>&1
taskkill /f /im flask.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo.
echo [1/3] Iniciando Evolution API...
start "Evolution API" cmd /k "cd /d C:\Users\Hermes\projetos_dev\evolution-api\evolution-api && npm run start:prod"

echo Aguardando 10 segundos para inicializacao da Evolution API...
timeout /t 10 /nobreak >nul

echo.
echo [2/3] Iniciando ngrok...
start "ngrok" cmd /k "ngrok http 5000 --domain=sulfide-circle-aptly.ngrok-free.dev"

echo Aguardando 5 segundos...
timeout /t 5 /nobreak >nul

echo.
echo [3/3] Iniciando Mercurio (Agente Python)...
start "Mercurio" cmd /k "cd /d %~dp0 && .venv\Scripts\flask --app app.main run --host 0.0.0.0 --port 5000"

echo.
echo ============================================
echo  Todos os servicos foram iniciados!
echo ============================================
echo.
echo Evolution API : http://localhost:8080
echo Evolution Mgr : http://localhost:3000
echo ngrok         : https://sulfide-circle-aptly.ngrok-free.dev
echo Mercurio      : http://localhost:5000
echo ============================================
echo.
pause
