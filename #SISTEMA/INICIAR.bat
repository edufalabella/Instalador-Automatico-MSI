@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Iniciador - Instalador MSI
cd /d "%~dp0"

REM --lancador  : (interno) indica que veio do INSTALAR.bat
REM --auto      : instalacao sem menu/perguntas (console visivel)
REM --sem-pausa : nao espera tecla no final (OBRIGATORIO em tarefa agendada/GPO/SCCM)
REM Modo GRAFICO (padrao): a unica janela visivel e a tela Python; o console fica oculto.
set "SEE_MASK_NOZONECHECKS=1"
set "AUTO="
set "NOPAUSE="
echo %* | find /i "--auto" >nul && set "AUTO=1"
echo %* | find /i "--sem-pausa" >nul && set "NOPAUSE=1"
set "GUI=1"
for %%A in (--auto --console --listar --menu --sem-pausa --pastas) do (
    echo %* | find /i "%%A" >nul && set "GUI="
)

REM ---------------------------------------------------------------
REM Protecao: este arquivo so roda quando chamado pelo INSTALAR.bat da raiz
REM ---------------------------------------------------------------
echo %* | find /i "--lancador" >nul
if errorlevel 1 (
    echo.
    echo Este arquivo nao deve ser executado diretamente.
    echo Use o INSTALAR.bat que fica na pasta raiz.
    echo.
    pause
    exit /b 1
)

if not exist "%~dp0logs" mkdir "%~dp0logs" >nul 2>&1

REM ---------------------------------------------------------------
REM 1) Garante privilegios de administrador (a unica janela do Windows que ainda pode aparecer: o UAC)
REM ---------------------------------------------------------------
net session >nul 2>&1
if %errorlevel% neq 0 (
    set "ESTILO=Normal"
    REM o prompt de comando fica VISIVEL: ele mostra a instalacao do Python
    powershell -NoProfile -WindowStyle Hidden -Command "try { Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs -WindowStyle !ESTILO! -ErrorAction Stop } catch { exit 1 }"
    if errorlevel 1 call :falha "A permissao de administrador foi negada. O instalador precisa dela para funcionar."
    exit /b
)

REM Remove a marca de "arquivo baixado da internet" (evita avisos de seguranca e bloqueio das DLLs do WiX)
powershell -NoProfile -WindowStyle Hidden -Command "Get-ChildItem -LiteralPath '%~dp0' -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue" >nul 2>&1

REM ---------------------------------------------------------------
REM 2) Procura o Python; se nao achar, instala a partir da pasta #SISTEMA (com progresso visivel)
REM ---------------------------------------------------------------
call :banner
echo   [1/3] Permissao de administrador ...... OK
echo   [2/3] Verificando o Python
set "PY="
call :achar_python
if defined PY goto :py_achado

echo         Python nao encontrado neste computador.
set "PYINST="
for %%F in ("%~dp0python-*.exe") do set "PYINST=%%~fF"
if not defined PYINST (
    call :falha "Instalador do Python nao encontrado. Coloque o arquivo python-3.x.x-amd64.exe dentro da pasta #SISTEMA."
    exit /b 1
)
echo         Instalador: %PYINST%
echo         Instalando o Python. NAO feche esta janela.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_python.ps1" -Instalador "%PYINST%" -Log "%~dp0logs\python_instalacao.log"
set "RC=!errorlevel!"
echo.

REM O PATH desta janela nao foi atualizado, entao procuramos o python.exe direto
call :achar_python
if not defined PY (
    call :falha "O Python nao pode ser instalado ou localizado, codigo !RC!. Veja logs\python_instalacao.log."
    exit /b 1
)
echo         [OK] Python instalado com sucesso.
goto :py_pronto

:py_achado
echo         [OK] Python ja instalado neste computador.

:py_pronto
set "PYVER="
for /f "delims=" %%V in ('"%PY%" --version 2^>^&1') do set "PYVER=%%V"
if defined PYVER echo         %PYVER%
echo.

REM ---------------------------------------------------------------
REM 3) Executa o instalador de MSIs
REM ---------------------------------------------------------------
:rodar
echo   [3/3] Iniciando a conversao e a validacao dos pacotes
echo         A tela do instalador vai abrir; esta janela fecha sozinha.
set "PYTHONUTF8=1"
set "PYEXE="
for /f "delims=" %%P in ('"%PY%" -c "import sys;print(sys.executable)"') do set "PYEXE=%%P"
if not defined PYEXE set "PYEXE=%PY%"
for %%I in ("%PYEXE%") do set "PYDIR=%%~dpI"
set "PYW=%PYDIR%pythonw.exe"

if defined GUI (
    REM tela grafica exige pythonw.exe + tkinter; sem eles cai no console (janela visivel)
    set "GUI_OK=1"
    if not exist "!PYW!" set "GUI_OK="
    if defined GUI_OK ( "%PYEXE%" -c "import tkinter" >nul 2>&1 || set "GUI_OK=" )
    if defined GUI_OK (
        ping -n 4 127.0.0.1 >nul
        start "" "!PYW!" "%~dp0instalador_msi.py" %*
        exit /b 0
    )
    echo [AVISO] Tela grafica indisponivel neste Python; abrindo o modo console.
    start "Instalador MSI" /wait "%PYEXE%" "%~dp0instalador_msi.py" %* --console
    exit /b !errorlevel!
)

"%PYEXE%" "%~dp0instalador_msi.py" %*
set "RC=%errorlevel%"
echo.
if %RC% equ 0 (
    echo [FIM] Concluido com sucesso.
) else if %RC% equ 3010 (
    echo [FIM] Concluido. REINICIE o computador para finalizar algumas instalacoes.
) else (
    echo [AVISO] O instalador terminou com codigo %RC%. Veja a pasta logs.
)
if defined AUTO if not defined NOPAUSE pause
exit /b %RC%


REM ===============================================================
REM Sub-rotina: cabecalho do prompt de comando
REM ===============================================================
:banner
cls
echo.
echo   ============================================================
echo     INSTALADOR AUTOMATICO MSI
echo     Python  ^>  Conversao EXE-MSI  ^>  Validacao  ^>  Instalacao
echo   ============================================================
echo.
exit /b 0


REM ===============================================================
REM Sub-rotina: mostra um erro (janela de mensagem no modo grafico; texto + pausa nos demais)
REM ===============================================================
:falha
echo.
echo [ERRO] %~1
>>"%~dp0logs\inicio.txt" echo [%date% %time%] %~1
if defined GUI (
    powershell -NoProfile -WindowStyle Hidden -Command "Add-Type -AssemblyName PresentationFramework; [void][System.Windows.MessageBox]::Show('%~1','Instalador MSI','OK','Error')"
) else (
    if not defined NOPAUSE pause
)
exit /b 1


REM ===============================================================
REM Sub-rotina: define a variavel PY com o caminho do python.exe
REM ===============================================================
:achar_python
set "PY="

REM a) Python Launcher (py.exe)
py -3 --version >nul 2>&1
if %errorlevel% equ 0 (
    for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)"') do set "PY=%%P"
    if defined PY exit /b 0
)

REM b) python no PATH (o atalho da Microsoft Store retorna erro e e ignorado)
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PY=python"
    exit /b 0
)

REM c) Pastas padrao de instalacao
for /d %%D in ("%ProgramFiles%\Python3*" "%LocalAppData%\Programs\Python\Python3*") do (
    if exist "%%~D\python.exe" set "PY=%%~D\python.exe"
)
exit /b 0
