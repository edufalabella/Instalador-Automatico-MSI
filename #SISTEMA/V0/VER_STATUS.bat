@echo off
chcp 65001 >nul
title Status da instalacao
:loop
cls
if exist "%~dp0logs\status.txt" (
    type "%~dp0logs\status.txt"
) else (
    echo Nenhuma instalacao iniciada ainda ^(logs\status.txt nao existe^).
)
echo.
echo ------------------------------------------------------------
echo Atualiza a cada 3 segundos. Feche a janela ou Ctrl+C para sair.
timeout /t 3 >nul
goto loop
