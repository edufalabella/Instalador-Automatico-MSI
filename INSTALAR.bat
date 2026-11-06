@echo off
REM ===============================================================
REM  INSTALAR.bat  -  unico arquivo para executar
REM
REM    INSTALAR.bat                      converte/repara e abre a TELA GRAFICA de selecao
REM    INSTALAR.bat --auto               instala tudo, sem perguntas
REM    INSTALAR.bat --pastas A,B         so as pastas indicadas (sem perguntas)
REM    INSTALAR.bat --listar             simula: lista o que seria feito
REM    INSTALAR.bat --status             acompanha o progresso
REM    INSTALAR.bat --sem-pausa          para tarefa agendada / GPO / SCCM
REM    INSTALAR.bat --manter-exe         converte EXE sem apagar o original
REM    INSTALAR.bat --console            usa o menu de texto em vez da tela grafica
REM    INSTALAR.bat --via-msiexec        roda os MSI gerados via msiexec (padrao: .exe embutido direto)
REM    INSTALAR.bat --validacao-rapida   valida so estrutura/tamanhos (nao le cada instalador por inteiro)
REM    INSTALAR.bat --sem-validar        NAO valida os pacotes (nao recomendado)
REM    INSTALAR.bat --ignorar-bloqueio   instala mesmo pacotes reprovados na validacao (emergencia)
REM    INSTALAR.bat --ver-janelas        diagnostico: NAO oculta/encerra telas dos instaladores, so registra
REM ===============================================================
setlocal

echo %* | "%SystemRoot%\System32\find.exe" /i "--status" >nul
if not errorlevel 1 (
    call "%~dp0#SISTEMA\VER_STATUS.bat"
    exit /b 0
)

REM Padrao: INTERATIVO (converte/repara e depois mostra a tela para escolher o que instalar).
REM Automatico (sem perguntas) somente com --auto, --sem-pausa, --pastas ou --listar.
set "MODO="
for %%A in (--auto --sem-pausa --pastas --listar) do (
    echo %* | "%SystemRoot%\System32\find.exe" /i "%%A" >nul
    if not errorlevel 1 set "MODO=--auto"
)

call "%~dp0#SISTEMA\INICIAR.bat" --lancador %MODO% %*
exit /b %errorlevel%
